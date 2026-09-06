# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import ics_control_probe as p


class Device:
    CHIP = p.m.CHIP_MT7925

    def __init__(self, value=0x403):
        self.value = value
        self.writes = []

    def rr(self, address):
        return self.value

    def wr(self, address, value):
        self.writes.append((address, value))
        self.value = value


def test_request_exact_source_layout_and_no_partition_writes():
    raw = p.request(True)
    assert len(raw) == 92
    assert raw[:8] == struct.pack("<4xHH", 0, 88)
    assert raw[8:16] == bytes([0, 1, 0, 0, 3, 0, 0, 0])
    assert struct.unpack_from("<7H", raw, 16) == (3, 0, 0, 0, 0, 0, 5000)
    assert raw[30:] == bytes(62)
    stop = p.request(False)
    assert [i for i, (a, b) in enumerate(zip(raw, stop, strict=True)) if a != b] == [9]


def test_timer_cycle_changes_only_delay():
    a, b = p.request(True), p.request(True, True)
    assert a[:28] == b[:28]
    assert a[30:] == b[30:]
    assert struct.unpack_from("<H", b, 28)[0] == 500
    with pytest.raises(ValueError, match="timer cycle"):
        p.request(True, 1)


@pytest.mark.parametrize("value", [0, 1, None, "start"])
def test_only_boolean_request(value):
    with pytest.raises(ValueError, match="boolean"):
        p.request(value)


def test_stop_both_indices_preserves_nontrigger_bits():
    dev = Device()
    assert all(p.stop_triggers(dev).values())
    assert dev.writes == [(0x82023090, 0x401), (0x82024090, 0x401)]


def test_bad_read_never_written():
    dev = Device(0xFFFFFFFF)
    with pytest.raises(ValueError, match="readback"):
        p.stop_triggers(dev)
    assert dev.writes == []


def test_restore_mask_is_narrow():
    dev = Device(0x12345678)
    assert p.masked_restore(dev, 0x830A1004, 0xAB)
    assert dev.writes == [(0x830A1004, 0x123456AB)]


@pytest.mark.parametrize(("address", "bits"), [(0xDEADBEEF, 0), (0x830A1004, 0x100)])
def test_restore_rejects_other_targets(address, bits):
    dev = Device()
    with pytest.raises(ValueError, match="traced ICS masks"):
        p.masked_restore(dev, address, bits)
    assert dev.writes == []


def test_wrong_chip_never_written():
    dev = Device()
    dev.CHIP = p.m.CHIP_MT7921
    with pytest.raises(ValueError, match="MT7925 only"):
        p.stop_triggers(dev)
    with pytest.raises(ValueError, match="traced ICS masks"):
        p.masked_restore(dev, 0x830A1004, 0)
    assert dev.writes == []
