# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Deterministic USB boundary replay; no firmware or radio required."""

import queue
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import usb.core

import mt7921u as m
from mt76_session import AcquisitionSession, SessionError, packet_kind
from mt7925u import Mt7925uDevice


def packet(kind=2, *, seq=0, chip="mt7921", marker=0, size=64):
    raw = bytearray(size)
    struct.pack_into("<I", raw, 0, size | kind << 27)
    raw[37 if chip == "mt7925" else 29] = seq
    raw[-1] = marker
    return bytes(raw)


class FakeUsb:
    def __init__(self, dev):
        self.device = dev
        self.rx = queue.Queue()
        self.writes = []
        self.owners = set()
        self.on_write = lambda: self.rx.put(packet(7, seq=dev.msg_seq, chip=dev.CHIP))
        self.short = False
        self.timeouts = []

    def read(self, ep, length, timeout):
        self.owners.add(threading.get_ident())
        self.timeouts.append(timeout)
        assert length == 16384
        try:
            item = self.rx.get(timeout=timeout / 1000)
        except queue.Empty as exc:
            raise usb.core.USBTimeoutError("quiet") from exc
        if isinstance(item, Exception):
            raise item
        return item

    def write(self, ep, data, timeout):
        self.owners.add(threading.get_ident())
        self.writes.append(bytes(data))
        self.on_write()
        return len(data) - int(self.short)


@pytest.fixture(params=[m.Mt7921uDevice, Mt7925uDevice])
def dev(request):
    device = request.param()
    device.dev = FakeUsb(device)
    device.evt_ep4 = True
    device._session_ready = True
    return device


def eventually(predicate):
    end = time.monotonic() + 2
    while not predicate():
        if time.monotonic() > end:
            pytest.fail("worker did not reach expected state")
        time.sleep(0.001)


def test_command_routes_frames_status_and_stale_reply(dev):
    def replay():
        for raw in [
            packet(marker=1),
            packet(0),
            packet(7, seq=15, chip=dev.CHIP),
            packet(marker=2),
            packet(7, seq=dev.msg_seq, chip=dev.CHIP),
        ]:
            dev.dev.rx.put(raw)

    dev.dev.on_write = replay
    with AcquisitionSession(dev) as session:
        reply = session.call(lambda d: d.mcu_send(0x44))
        assert reply[dev.RXD_SEQ_OFFSET] == dev.msg_seq
        a, b = session.read(), session.read()
        assert [a.raw[-1], b.raw[-1]] == [1, 2]
        assert a.received_ns <= b.received_ns
        assert a.epoch_ns == b.epoch_ns == session.epoch_ns
        assert [session.read(events=True).kind for _ in range(2)] == ["status", "reply"]
        counts = session.snapshot()["counts"]
        assert counts["replies_matched"] == counts["unmatched_replies"] == 1
        assert dev.mcu_wait_dropped_frames == 0
    assert len(dev.dev.owners) == 1
    assert session.snapshot()["state"] == "closed"


def test_overflow_is_bounded_and_never_blocks_reply(dev):
    def replay():
        for i in range(10):
            dev.dev.rx.put(packet(marker=i))
            dev.dev.rx.put(packet(0))
        dev.dev.rx.put(packet(7, seq=dev.msg_seq, chip=dev.CHIP))

    dev.dev.on_write = replay
    with AcquisitionSession(dev, frame_capacity=2, event_capacity=1) as session:
        session.call(lambda d: d.mcu_send(0x44))
        stats = session.snapshot()
        assert stats["frame_depth"] == 2
        assert stats["event_depth"] == 1
        assert stats["counts"]["frames_dropped"] == 8
        assert stats["counts"]["events_dropped"] == 9
        assert [session.read().raw[-1] for _ in range(2)] == [0, 1]


def test_timeout_faults_before_sequence_can_be_reused(dev):
    dev.dev.on_write = lambda: None
    session = AcquisitionSession(dev).start()
    try:
        with pytest.raises(SessionError):
            session.call(lambda d: d.mcu_send(0x44), timeout=0.1)
        dev.dev.rx.put(packet(7, seq=dev.msg_seq, chip=dev.CHIP))
        with pytest.raises(SessionError):
            session.call(lambda d: d.mcu_send(0x44))
        assert len(dev.dev.writes) == 1
        assert max(dev.dev.timeouts) <= 100
    finally:
        session.stop()
    with pytest.raises(SessionError):
        AcquisitionSession(dev).start()


def test_sequence_wrap_serialized_concurrent_callers(dev):
    with AcquisitionSession(dev) as session, ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: session.call(lambda d: d.mcu_send(0x44)), range(32)))
        seqs = [reply[dev.RXD_SEQ_OFFSET] for reply in results]
        assert seqs.count(1) == 3
        assert seqs.count(15) == 2
        assert session.snapshot()["counts"]["commands_completed"] == 32
    assert len(dev.dev.owners) == 1


def test_swallowed_reply_timeout_still_invalidates_session(dev):
    dev.dev.on_write = lambda: None

    def catches_error(d):
        try:
            d.mcu_send(0x44, timeout=10)
        except SessionError:
            return None

    with AcquisitionSession(dev) as session:
        with pytest.raises(SessionError):
            session.call(catches_error)
        assert session.state == "failed"
        with pytest.raises(SessionError):
            session.call(lambda d: d.mcu_send(0x44))


def test_owner_guards_and_retune_metadata(dev):
    def replay():
        dev.dev.rx.put(packet(marker=1))
        dev.dev.rx.put(packet(7, seq=dev.msg_seq, chip=dev.CHIP))

    dev.dev.on_write = replay
    with AcquisitionSession(dev) as session:
        for operation in [
            lambda: dev.rx_read(),
            lambda: dev.mcu_send(0x44),
            lambda: dev.rr(0),
            dev.close,
            lambda: dev.bringup(b"", b""),
        ]:
            with pytest.raises((SessionError, RuntimeError)):
                operation()
        session.call(lambda d: d.mcu_send(0x44), retune=True)
        during = session.read()
        assert during.transitioning
        assert during.channel_generation == 0
        dev.dev.rx.put(packet(marker=2))
        after = session.read()
        assert not after.transitioning
        assert after.channel_generation == 1


def test_idle_events_never_reused_as_command_reply(dev):
    dev.dev.rx.put(packet(7, seq=1, chip=dev.CHIP, marker=9))
    with AcquisitionSession(dev) as session:
        assert session.read(events=True).raw[-1] == 9
        assert session.call(lambda d: d.mcu_send(0x44))[-1] == 0


def test_short_write_and_transport_loss_fail_closed(dev):
    dev.dev.short = True
    session = AcquisitionSession(dev).start()
    try:
        with pytest.raises(m.McuError):
            session.call(lambda d: d.mcu_send(0x44))
        eventually(lambda: session.state == "failed")
    finally:
        session.stop()
    dev._session_ready = True  # explicit fake firmware reset
    dev.dev.rx = queue.Queue()
    dev.dev.rx.put(usb.core.USBError("sensitive device identifier"))
    with AcquisitionSession(dev) as session:
        eventually(lambda: session.state == "failed")
        assert "sensitive" not in session.snapshot()["error"]


def test_stop_wakes_queued_commands_and_preserves_frames(dev):
    entered, release = threading.Event(), threading.Event()

    def blocked(d):
        entered.set()
        release.wait(1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        session = AcquisitionSession(dev).start()
        dev.dev.rx.put(packet(marker=3))
        eventually(lambda: session.snapshot()["frame_depth"] == 1)
        first = pool.submit(session.call, blocked)
        assert entered.wait(1)
        second = pool.submit(session.call, lambda d: d.mcu_send(0x44))
        eventually(lambda: session.commands.qsize() == 1)
        with pytest.raises(SessionError, match="still owns"):
            session.stop(timeout=0.01)
        assert dev._session is session
        release.set()
        session.stop()
        for result in [first, second]:
            with pytest.raises(SessionError):
                result.result()
        assert session.read().raw[-1] == 3
        assert session.read(timeout=0) is None


@pytest.mark.parametrize("chip", ["mt7921", "mt7925"])
def test_classifier_dma_bounds(chip):
    assert packet_kind(b"", chip) == "malformed"
    assert packet_kind(packet()[:20], chip) == "malformed"
    assert packet_kind(packet(7, chip=chip), chip) == "reply"
    assert packet_kind(packet(0), chip) == "status"
    assert packet_kind(packet() + b"padding", chip) == "frame"
    raw = bytearray(packet())
    struct.pack_into("<I", raw, 0, (0x3801 << 16) | len(raw))
    assert packet_kind(bytes(raw), chip) == "frame"


@pytest.mark.parametrize("capacity", [0, -1, 65537, 1.5])
def test_capacity_validation(capacity):
    with pytest.raises(ValueError, match="queue capacities"):
        AcquisitionSession(None, frame_capacity=capacity)


def test_command_queue_full_does_not_send_or_fault(dev):
    entered, release = threading.Event(), threading.Event()

    def blocked(d):
        entered.set()
        release.wait(1)
        return 7

    with (
        AcquisitionSession(dev, command_capacity=1) as session,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        first = pool.submit(session.call, blocked)
        assert entered.wait(1)
        second = pool.submit(session.call, lambda d: 8)
        eventually(lambda: session.commands.qsize() == 1)
        with pytest.raises(queue.Full):
            session.call(lambda d: d.mcu_send(0x44))
        assert session.state == "running"
        release.set()
        assert first.result() == 7
        assert second.result() == 8
        assert dev.dev.writes == []


def test_failed_retune_clears_requested_channel(dev):
    dev._capture_channel = ("5GHz", 36, 36, 20)

    def retune(d):
        d._capture_channel = ("5GHz", 149, 149, 20)

    with AcquisitionSession(dev) as session:
        assert session.snapshot()["requested_channel"] == ("5GHz", 36, 36, 20)
        session.call(retune, retune=True)
        assert session.snapshot()["requested_channel"] == ("5GHz", 149, 149, 20)
        with pytest.raises(ValueError, match="synthetic"):
            session.call(lambda d: (_ for _ in ()).throw(ValueError("synthetic")), retune=True)
        assert session.snapshot()["requested_channel"] is None


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_stop_deadline_validation(value):
    with pytest.raises(ValueError, match="stop timeout"):
        AcquisitionSession(None).stop(value)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--usb-id", "ffff:ffff"],
        ["--usb-id", "0e8d:7961", "--seconds", "0"],
        ["--usb-id", "0e8d:7961", "--named-counters", "--band", "6GHz"],
        ["--usb-id", "0e8d:7961", "--hop-seconds", "-1"],
        ["--usb-id", "0e8d:7961", "--mib-seconds", "99999"],
    ],
)
def test_python_probe_invalid_arguments_refuse_before_usb(args):
    script = Path(__file__).resolve().parents[1] / "scripts/session_probe.py"
    result = subprocess.run([sys.executable, str(script), *args], capture_output=True, timeout=5)  # noqa: S603 -- local CLI refusal test
    assert result.returncode == 2
    assert not result.stdout
