# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
import sys

import pytest

from research import tx_power_offset_probe as p


@pytest.mark.parametrize("offset", [0, -4, -8])
def test_only_six_power_bits_change_and_no_ack_nav(offset):
    dev = p.m.device_class_for(p.m.CHIP_MT7925)()
    txd, payload = p.descriptor(dev, offset, 7, b"nonce123")
    baseline = p.p.descriptor(dev, payload, 7, 0x488, fixed_bw=True)
    words, before = struct.unpack("<16I", txd), struct.unpack("<16I", baseline)
    assert ((words[2] >> 26) & 63) == offset & 63
    assert words[2] & ~(63 << 26) == before[2] & ~(63 << 26)
    assert words[:2] + words[3:] == before[:2] + before[3:]
    assert words[3] & 1
    assert words[3] & (1 << 28)
    assert payload[2:4] == bytes(2)
    assert payload[4:10] == b"\xff" * 6


@pytest.mark.parametrize("offset", [1, 4, 31, 32, -1, -32, -64, True, -4.0])
def test_positive_and_unplanned_offsets_refused(offset):
    dev = p.m.device_class_for(p.m.CHIP_MT7925)()
    with pytest.raises(ValueError, match="bounded negative"):
        p.descriptor(dev, offset, 0, b"nonce123")


def test_other_chip_refused():
    dev = p.m.device_class_for(p.m.CHIP_MT7921)()
    with pytest.raises(ValueError, match="MT7925 power"):
        p.descriptor(dev, 0, 0, b"nonce123")


def test_plan_brackets_each_negative_offset():
    assert p.PLAN == (0, -4, 0, -8, 0)
    assert len(p.PLAN) * 4 == 20


def test_signal_uses_g5_word6_when_present(monkeypatch):
    g5 = [0] * 18
    g5[6] = 0x78563412
    monkeypatch.setattr(p, "vectors", lambda *_: {"g3": (0, 0xFFFFFFFF), "g5": g5})
    row = p.signal(b"", {"rssi": -50, "chain_signal": [-50, -51]})
    assert row["rcpi_raw"] == [0x12, 0x34, 0x56, 0x78]
    assert row["rcpi_source"] == "g5_word6"
    assert row["rssi_driver_units"] == -50


def test_signal_falls_back_to_g3_or_missing(monkeypatch):
    monkeypatch.setattr(p, "vectors", lambda *_: {"g3": (0, 0x04030201)})
    assert p.signal(b"", {})["rcpi_raw"] == [1, 2, 3, 4]
    monkeypatch.setattr(p, "vectors", lambda *_: {})
    assert p.signal(b"", {})["rcpi_raw"] is None


def test_opt_in_before_usb(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["probe"])
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("unexpected USB"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2
