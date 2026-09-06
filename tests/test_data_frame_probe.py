# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
import sys

import pytest

from research import data_frame_probe as p


@pytest.mark.parametrize("chip", [p.m.CHIP_MT7921, p.m.CHIP_MT7925])
@pytest.mark.parametrize("kind", ["probe", "data", "qos-data"])
def test_bounded_descriptor_matches_frame_without_ack_or_aggregation(chip, kind):
    dev = p.m.device_class_for(chip)()
    txd, payload = p.descriptor(dev, kind, 7, b"nonce123")
    words = struct.unpack("<16I", txd)
    assert len(txd) == 64
    assert words[0] & 65535 == 64 + len(payload)
    assert payload[4:10] == b"\xff" * 6
    assert struct.unpack_from("<H", payload, 2)[0] == 0  # no NAV reservation
    assert words[3] & 1  # TXD no-ACK
    assert words[3] & (1 << 28)  # BA disabled
    assert not words[3] & (1 << 5)  # no hardware A-MSDU
    shift = 16 if chip == p.m.CHIP_MT7925 else 11
    assert (words[1] >> shift) & 31 == (13 if kind == "qos-data" else 12)
    assert words[2] & 63 == (4 if kind == "probe" else 0x28 if kind == "qos-data" else 0x20)
    if kind == "qos-data":
        assert payload[:2] == b"\x88\x00"
        assert payload[24:26] == b"\x20\x00"
        assert payload[26:34] == b"\xaa\xaa\x03\x00\x00\x00\x88\xb5"
    if chip == p.m.CHIP_MT7921:
        assert words[8] & 63 == words[2] & 63


@pytest.mark.parametrize(
    ("kind", "seq", "nonce"),
    [("deauth", 0, b"nonce123"), ("data", 20, b"nonce123"), ("data", 0, b"short")],
)
def test_invalid_frame_refused(kind, seq, nonce):
    with pytest.raises(ValueError, match=r"only synthetic|bounded sequence|eight-byte"):
        p.frame(kind, seq, nonce)


def test_plan_brackets_each_new_frame_class_with_probes():
    assert p.PLAN == ("probe", "data", "probe", "qos-data", "probe")
    assert len(p.PLAN) * 4 == 20


def test_opt_in_required_before_usb(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["probe", "--transmitter", "mt7925"])
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("unexpected USB"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2


def test_old_status_sequence_uses_txs1_not_payload_or_txs2():
    raw = struct.pack("<10I", 40, 0, 0, (17 << 20) | 42, 999, 3 << 24, 0, 0, 0, 0)
    rows = p.old_tx_status(raw)
    assert rows[0]["sequence"] == 17
    assert rows[0]["pid"] == 3
    assert p.old_tx_status(b"short") == []
