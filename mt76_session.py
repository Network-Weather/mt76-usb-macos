# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded, single-owner acquisition after explicit firmware bring-up.

The worker owns USB; consumers own decoding/output. No warm adoption, automatic
recovery, transmission, or physical gap-free retuning is implied by this API.
"""

from __future__ import annotations

import math
import queue
import struct
import threading
import time
from collections import Counter, deque
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass

import usb.core

import mt7921u as m


class SessionError(RuntimeError):
    """Session stopped or faulted; a fresh bring-up is needed before restarting."""


@dataclass(frozen=True)
class Packet:
    raw: bytes
    received_ns: int
    epoch_ns: int
    channel_generation: int
    transitioning: bool
    kind: str


def packet_kind(raw: bytes, chip: str) -> str:
    """Classify bounded DMA records using the existing connac2/3 RX layouts.

    mt7921_queue_rx_skb / mt7925_queue_rx_skb at the pinned mt76 baseline;
    this is routing, not a replacement for full RX or MCU payload validation.
    """
    if len(raw) < 4:
        return "malformed"
    word = struct.unpack_from("<I", raw)[0]
    size = word & 0xFFFF
    if size < 4 or size > len(raw):
        return "malformed"
    kind = (word >> 27) & 31
    flag = (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK
    if kind == m.PKT_TYPE_NORMAL or (kind == m.PKT_TYPE_RX_EVENT and flag == m.PKT_FLAG_NORMAL_MCU):
        return "frame" if size >= 32 else "malformed"
    if chip == "mt7925" and ((word >> 16) & 0x380F) == 0x3801:
        return "frame" if size >= 32 else "malformed"
    if kind == m.PKT_TYPE_RX_EVENT:
        return "reply" if size >= (44 if chip == "mt7925" else 36) else "malformed"
    return "status"


class AcquisitionSession:
    """One worker, bounded drop-newest queues, and serialized command callbacks.

    Start only after bringup/monitor/sniffer/tune on a caller-owned device. Then
    use call(lambda dev: ...) for short driver operations and read() for packets.
    Callbacks must not sleep, perform output, reenter the session, or reset/close
    the device. Python cannot forcibly cancel arbitrary user callback code.
    Stop the session before closing its device. Each new session requires bringup.
    """

    def __init__(self, dev, *, frame_capacity=256, event_capacity=64, command_capacity=16):
        for value in (frame_capacity, event_capacity, command_capacity):
            if not isinstance(value, int) or not 1 <= value <= 65536:
                raise ValueError("queue capacities must be integers in 1..65536")
        self.dev = dev
        self.frames = deque()
        self.events = deque()
        self.frame_capacity = frame_capacity
        self.event_capacity = event_capacity
        self.commands = queue.Queue(command_capacity)
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.counts = Counter()
        self.state = "new"
        self.error = None
        self.epoch_ns = 0
        self.generation = 0
        self.requested_channel = None
        self.transitioning = False
        self.deadline = None
        self.worker = None
        self.read_size = 16384
        self.poll_ms = 50

    def start(self):
        if self.state != "new" or getattr(self.dev, "_session", None) is not None:
            raise SessionError("device/session already owned")
        if not getattr(self.dev, "_session_ready", False) or not self.dev.evt_ep4:
            raise SessionError("explicit fresh bringup required before session start")
        self.epoch_ns = time.monotonic_ns()
        self.requested_channel = getattr(self.dev, "_capture_channel", None)
        self.dev._session = self
        self.dev._session_ready = False
        self.state = "running"
        self.worker = threading.Thread(target=self._run, name="mt76-acquisition", daemon=True)
        try:
            self.worker.start()
        except BaseException:
            self.dev._session = None
            self.state = "failed"
            raise
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()

    def check_owner(self):
        if threading.current_thread() is not self.worker:
            raise SessionError("USB is owned by the acquisition worker; use session.call/read")
        if self.stop_event.is_set():
            raise SessionError("session stopping")

    def io_timeout(self, requested_ms):
        self.check_owner()
        if self.deadline is None:
            return min(requested_ms, self.poll_ms)
        left = self.deadline - time.monotonic()
        if left <= 0:
            self._fail("command deadline expired; fresh bringup required")
            raise SessionError("command deadline expired; resynchronization required")
        return max(1, min(requested_ms, math.ceil(left * 1000)))

    def call(self, operation, *, timeout=3.0, retune=False):
        """Execute one short driver callback; timeout includes queueing and all USB I/O.

        Set retune=True for operations changing channel. Failure invalidates the
        session, not just the callback. Operation results may contain identifiers.
        """
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if threading.current_thread() is self.worker:
            raise SessionError("session.call cannot be reentered from a callback")
        future = Future()
        with self.condition:
            if self.state != "running":
                raise SessionError(self.error or "session is not running")
            self.commands.put_nowait((future, operation, time.monotonic() + timeout, retune))
        try:
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            self._fail("command deadline expired; fresh bringup required")
            raise SessionError(self.error) from exc

    def tune(self, band, control, center=None, width=20, *, timeout=3.0):
        return self.call(
            lambda dev: dev.tune(band, control, center, width), timeout=timeout, retune=True
        )

    def read(self, *, timeout=1.0, events=False):
        """Return a Packet, or None on quiet timeout/after queued data is drained.

        Queued packets remain readable after stop/failure. snapshot() distinguishes
        end of session from a quiet channel. Raw frames are sensitive, never logged.
        """
        if threading.current_thread() is self.worker:
            raise SessionError("worker callbacks cannot consume their own session queues")
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be nonnegative and finite")
        end = time.monotonic() + timeout
        with self.condition:
            packets = self.events if events else self.frames
            while not packets:
                left = end - time.monotonic()
                if left <= 0 or self.state in ("closed", "failed", "new"):
                    return None
                self.condition.wait(left)
            packet = packets.popleft()
            self.counts["events_delivered" if events else "frames_delivered"] += 1
            return packet

    def snapshot(self):
        with self.condition:
            return {
                "state": self.state,
                "error": self.error,
                "epoch_ns": self.epoch_ns,
                "channel_generation": self.generation,
                "requested_channel": self.requested_channel,
                "frame_depth": len(self.frames),
                "event_depth": len(self.events),
                "counts": dict(self.counts),
            }

    def stop(self, timeout=2.0):
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("stop timeout must be nonnegative and finite")
        if threading.current_thread() is self.worker:
            raise SessionError("worker cannot join itself")
        with self.condition:
            if self.state == "new":
                self.state = "closed"
            elif self.state == "running":
                self.state = "stopping"
            self.stop_event.set()
            self.condition.notify_all()
        if self.worker is not None:
            self.worker.join(timeout)
            if self.worker.is_alive():
                raise SessionError("worker still owns USB; do not close device")
        if getattr(self.dev, "_session", None) is self:
            self.dev._session = None

    def _fail(self, message):
        with self.condition:
            self.error = message
            self.state = "failed"
            self.requested_channel = None
            self.stop_event.set()
            self.condition.notify_all()

    def _count(self, key):
        with self.condition:
            self.counts[key] += 1

    def _receive(self, timeout):
        try:
            raw = bytes(self.dev.bulk_in(self.dev.ep_in_pkt_rx, self.read_size, timeout))
        except usb.core.USBTimeoutError:
            self._count("read_timeouts")
            return None
        except usb.core.USBError:
            self._count("usb_errors")
            self._fail("USB read failed; fresh bringup required")
            raise
        self._count("transfers")
        kind = packet_kind(raw, self.dev.CHIP)
        if kind == "malformed":
            self._count("malformed")
            return None
        # USB padding is not part of the DMA record.
        raw = raw[: struct.unpack_from("<H", raw)[0]]
        return Packet(
            raw, time.monotonic_ns(), self.epoch_ns, self.generation, self.transitioning, kind
        )

    def _enqueue(self, packet):
        frame = packet.kind == "frame"
        prefix = "frames" if frame else "events"
        with self.condition:
            self.counts[prefix + "_received"] += 1
            packets = self.frames if frame else self.events
            capacity = self.frame_capacity if frame else self.event_capacity
            if len(packets) == capacity:
                self.counts[prefix + "_dropped"] += 1
            else:
                packets.append(packet)
                self.counts[prefix + "_high_water"] = max(
                    self.counts[prefix + "_high_water"], len(packets)
                )
                self.condition.notify_all()

    def wait_reply(self, seq, cid, timeout):
        """Called only by the existing MCU encoder on the owner thread.

        Payload-specific validation remains in the command helper; event IDs do
        not generally equal command IDs. Never queue replies for future matching.
        A timeout faults the session before another sequence can be allocated.
        """
        self.check_owner()
        end = min(self.deadline, time.monotonic() + timeout / 1000)
        while time.monotonic() < end:
            self.check_owner()
            packet = self._receive(
                max(1, min(self.poll_ms, math.ceil((end - time.monotonic()) * 1000)))
            )
            if packet is None:
                continue
            if packet.kind == "reply":
                if packet.raw[self.dev.RXD_SEQ_OFFSET] == seq:
                    self._count("replies_matched")
                    return packet.raw
                self._count("unmatched_replies")
            self._enqueue(packet)
        self._fail("MCU reply deadline expired; fresh bringup required")
        raise SessionError(f"MCU command 0x{cid:02x} timed out; fresh bringup required")

    def _run(self):
        active = None
        try:
            while not self.stop_event.is_set():
                try:
                    active, operation, self.deadline, retune = self.commands.get_nowait()
                except queue.Empty:
                    packet = self._receive(self.poll_ms)
                    if packet:
                        if packet.kind == "reply":
                            self._count("unmatched_replies")
                        self._enqueue(packet)
                    continue
                self.check_owner()
                self.io_timeout(self.poll_ms)
                with self.condition:
                    self.transitioning = retune
                    if retune:
                        self.requested_channel = None
                result = operation(self.dev)
                self.io_timeout(self.poll_ms)
                with self.condition:
                    if retune:
                        self.generation += 1
                        self.requested_channel = getattr(self.dev, "_capture_channel", None)
                    self.transitioning = False
                self.deadline = None
                self._count("commands_completed")
                active.set_result(result)
                active = None
        except BaseException as exc:
            # Do not serialize exception text: user callbacks/USB errors may carry
            # identifiers. The original exception is returned only to the caller.
            if not self.stop_event.is_set():
                self._fail(f"{type(exc).__name__}: session failed; fresh bringup required")
            if active is not None:
                active.set_exception(exc)
        finally:
            with self.condition:
                if self.state != "failed":
                    self.state = "closed"
                while not self.commands.empty():
                    future, *_ = self.commands.get_nowait()
                    future.set_exception(SessionError("session ended before command ran"))
                self.condition.notify_all()
