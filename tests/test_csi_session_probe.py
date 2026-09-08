# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Host-side filtering remains authoritative during CSI configuration/STOP."""

from types import SimpleNamespace

import pytest

from mt76_csi import CsiAction
from research.csi_session_probe import Window, send
from tests.test_csi_measurements import event, report, report_fields


def test_queued_wrong_source_receiver_and_stopped_reports_are_not_delivered():
    source = bytes.fromhex("020000000001")
    window = Window(source, 1, 100)
    packet = SimpleNamespace(raw=report(), received_ns=99)
    window.event(packet)
    packet.received_ns = 100
    window.event(packet)
    packet.raw = report(report_fields() | {18: b"\x01\x00\x00\x00"})
    window.event(packet)
    packet.raw = report(report_fields() | {10: bytes.fromhex("0200000000020000")})
    window.event(packet)
    assert window.counts["accepted_reports"] == 1
    assert window.counts["preconfiguration_discarded"] == 1
    assert window.counts["receiver_discarded"] == 1
    assert window.counts["unselected_discarded"] == 1
    window.stopped = True
    packet.raw = report()
    window.event(packet)
    assert window.counts["reports_after_stop"] == 1
    assert "transmitter" not in repr(window.export())
    assert "32768" not in repr(window.export())


@pytest.mark.parametrize("status", [0, 1])
def test_send_checks_ack_status(status):
    dev = SimpleNamespace(
        CHIP="mt7925",
        msg_seq=9,
        uni_option=lambda _cid: 7,
        mcu_uni=lambda *_a, **_kw: event(bytes([0x4A, 0, 0, 0, status, 0, 0, 0]), 1, 9),
    )
    if status:
        with pytest.raises(RuntimeError, match="rejected"):
            send(dev, CsiAction.START)
    else:
        send(dev, CsiAction.START)
