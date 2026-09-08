# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Experimental, session-bound lifetime for the pinned beacon CSI profile.

The acquisition session owns USB and bounded queues; this object owns only CSI
configuration and host acceptance. The caller routes packets and serializes all
capture methods. Use exactly one CSI controller per device, no out-of-band CSI
commands or retunes, and stop CSI before stopping/destroying its session.
"""

from __future__ import annotations

import time

from mt76_csi import CsiAction, build_csi_request, parse_beacon_csi, parse_csi_ack


class CsiCaptureError(RuntimeError):
    """CSI lifetime invalid; stop the session and freshly bring up the device."""


class BeaconCsiCapture:
    """One selected transmitter on MT7925 channel36/20MHz, receivers1 or2.

    Construct/start/accept/stop on one control thread. Session must outlive this
    capture. start and stop submit bounded callbacks; do not call them from a
    session callback. A failed start may have changed firmware: active remains
    true, ready false, and needs_reload true. stop disables acceptance immediately,
    even if its firmware command fails. It does not clear needs_reload: explicitly
    reload firmware after the experiment, after the USB worker has stopped.
    """

    def __init__(self, session, transmitter: bytes, *, receivers: int = 1):
        chip = session.dev.CHIP
        # Validate the entire configuration before any command can be queued.
        self._requests = (
            build_csi_request(chip, CsiAction.STOP),
            build_csi_request(chip, CsiAction.BEACON_SELECTOR),
            build_csi_request(chip, CsiAction.START),
            build_csi_request(chip, CsiAction.ADD_TRANSMITTER, transmitter=transmitter),
            build_csi_request(chip, CsiAction.RECEIVER_COUNT, receivers=receivers),
        )
        self.session = session
        self._transmitter = transmitter
        self.receivers = receivers
        self.active = self.ready = self.needs_reload = False
        self.epoch_ns = self.channel_generation = self.configured_ns = 0

    def _context(self):
        snapshot = self.session.snapshot()
        if snapshot["state"] != "running" or snapshot["requested_channel"] != ("5GHz", 36, 36, 20):
            raise CsiCaptureError("CSI requires a running channel36/20MHz session")
        return snapshot

    @staticmethod
    def _send(dev, payload):
        if dev.uni_option(0x4A) != 7:
            raise CsiCaptureError("CSI requires SET_ACK option7")
        raw = dev.mcu_uni(0x4A, payload, timeout=1000)
        if parse_csi_ack(dev.CHIP, raw, dev.msg_seq):
            raise CsiCaptureError("CSI control rejected")

    def start(self):
        if self.active:
            raise CsiCaptureError("CSI capture already active")
        before = self._context()

        def begin(dev):
            current = self._context()
            if any(current[key] != before[key] for key in ("epoch_ns", "channel_generation")):
                raise CsiCaptureError("CSI context changed before configuration")
            self.active = self.needs_reload = True
            self.ready = False
            self.epoch_ns = current["epoch_ns"]
            self.channel_generation = current["channel_generation"]
            for payload in self._requests:
                self._send(dev, payload)
            self.configured_ns = time.monotonic_ns()

        self.session.call(begin, timeout=6)
        # Publish readiness only after the worker has completed its own deadline check.
        self.ready = True

    def stop(self):
        self.ready = False
        if not self.active:
            return
        self.session.call(lambda dev: self._send(dev, self._requests[0]), timeout=2)
        self.active = False

    def accept(self, packet):
        """Return an owned report or None for filtered/non-CSI/late packets.

        Never reads USB or removes another consumer's queue entry. Parse errors
        raise ValueError; session/epoch/retune invalidation raises CsiCaptureError
        and disables further acceptance. Preserve loss counters from the session.
        """
        if not self.ready:
            return None
        try:
            current = self._context()
            if (
                current["epoch_ns"] != self.epoch_ns
                or current["channel_generation"] != self.channel_generation
            ):
                raise CsiCaptureError("CSI epoch or channel generation changed")
        except CsiCaptureError:
            self.ready = False
            raise
        if (
            packet.epoch_ns != self.epoch_ns
            or packet.channel_generation != self.channel_generation
            or packet.transitioning
            or packet.received_ns < self.configured_ns
        ):
            return None
        raw = packet.raw
        if packet.kind != "reply" or len(raw) < 44 or raw[36] != 0x4A:
            return None
        report = parse_beacon_csi("mt7925", raw)
        if report.transmitter != self._transmitter or report.rx_index >= self.receivers:
            return None
        return report
