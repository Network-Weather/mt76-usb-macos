# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Public CSI lifetime through the real acquisition worker with fake USB."""

import struct
from dataclasses import replace

import pytest

import mt7921u as m
from mt76_csi_session import BeaconCsiCapture, CsiCaptureError
from mt76_session import AcquisitionSession, Packet
from mt7925u import Mt7925uDevice
from tests.test_csi_measurements import event, report, report_fields
from tests.test_session import FakeUsb

SOURCE = bytes.fromhex("020000000001")


def device(chip=Mt7925uDevice):
    dev = chip()
    dev.dev = FakeUsb(dev)
    dev.evt_ep4 = True
    dev._session_ready = True
    dev._capture_channel = ("5GHz", 36, 36, 20)
    dev.dev.on_write = lambda: dev.dev.rx.put(event(struct.pack("<II", 0x4A, 0), 1, dev.msg_seq))
    return dev


def packet(capture, raw=None):
    return Packet(
        report() if raw is None else raw,
        capture.configured_ns,
        capture.epoch_ns,
        capture.channel_generation,
        False,
        "reply",
    )


def test_start_stop_order_and_host_acceptance():
    dev = device()
    with AcquisitionSession(dev) as session:
        capture = BeaconCsiCapture(session, SOURCE)
        assert capture.accept(packet(capture)) is None
        capture.start()
        assert capture.active
        assert capture.ready
        assert capture.needs_reload
        assert [data[4 + m.MCU_UNI_TXD_LEN + 4] for data in dev.dev.writes] == [0, 2, 1, 4, 3]
        with pytest.raises(CsiCaptureError, match="already active"):
            capture.start()
        raw = packet(capture)
        assert capture.accept(raw).transmitter == SOURCE
        for changed in (
            replace(raw, epoch_ns=0),
            replace(raw, channel_generation=1),
            replace(raw, received_ns=capture.configured_ns - 1),
            replace(raw, transitioning=True),
            replace(raw, kind="frame"),
        ):
            assert capture.accept(changed) is None
        for fields in ({18: struct.pack("<I", 1)}, {10: bytes.fromhex("0200000000020000")}):
            assert capture.accept(packet(capture, report(report_fields() | fields))) is None
        with pytest.raises(ValueError, match="CSI"):
            capture.accept(packet(capture, report()[:-1]))
        capture.stop()
        assert capture.accept(raw) is None
        assert not capture.active
        assert not capture.ready
        assert capture.needs_reload  # STOP is not full firmware configuration restoration.
        count = len(dev.dev.writes)
        capture.stop()
        assert len(dev.dev.writes) == count
        capture.start()
        assert capture.accept(raw) is None  # Previous cycle's queued packet is too old.
        capture.stop()


@pytest.mark.parametrize("stage", range(1, 7))
@pytest.mark.parametrize("failure", ["status", "shape", "write"])
def test_each_start_and_stop_stage_failure_is_not_ready(stage, failure):
    dev = device()

    def respond():
        failed = len(dev.dev.writes) == stage
        dev.dev.short = failed and failure == "write"
        raw = event(struct.pack("<II", 0x4A, int(failed and failure == "status")), 1, dev.msg_seq)
        if failed and failure == "shape":
            raw = event(bytes(4), 1, dev.msg_seq)
        dev.dev.rx.put(raw)

    dev.dev.on_write = respond
    with AcquisitionSession(dev) as session:
        capture = BeaconCsiCapture(session, SOURCE)
        if stage == 6:
            capture.start()
        operation = capture.stop if stage == 6 else capture.start
        with pytest.raises((RuntimeError, ValueError), match=r"CSI|short|bulk"):
            operation()
        assert session.snapshot()["state"] == "failed"
        assert capture.active
        assert not capture.ready
        assert capture.needs_reload
        assert capture.accept(packet(capture)) is None
        assert len(dev.dev.writes) == stage


@pytest.mark.parametrize(
    ("field", "value"),
    [("generation", 1), ("epoch_ns", 0), ("requested_channel", ("5GHz", 149, 149, 20))],
)
def test_changed_context_invalidates_acceptance(field, value):
    dev = device()
    with AcquisitionSession(dev) as session:
        capture = BeaconCsiCapture(session, SOURCE)
        capture.start()
        with session.condition:
            setattr(session, field, value)
        with pytest.raises(CsiCaptureError, match="CSI"):
            capture.accept(packet(capture))
        assert not capture.ready
        capture.stop()


def test_unsupported_or_invalid_configuration_never_queues_commands():
    for chip, ta, receivers in (
        (m.Mt7921uDevice, SOURCE, 1),
        (Mt7925uDevice, bytes(6), 1),
        (Mt7925uDevice, SOURCE, 0),
        (Mt7925uDevice, SOURCE, True),
    ):
        dev = device(chip)
        with AcquisitionSession(dev) as session:
            with pytest.raises(ValueError, match="CSI"):
                BeaconCsiCapture(session, ta, receivers=receivers)
            assert session.snapshot()["state"] == "running"
            assert not dev.dev.writes
