# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import legacy_rdd_state_probe as p


def table():
    raw = bytearray(432)
    struct.pack_into("<6I", raw, 24, 0, 0, 3, 0x401C00, 1024, 0)
    return raw


def test_exact_unique_allocation():
    assert p.allocation(table()) == {"base": "0x401c00", "bytes": 1024}
    bad = table()
    bad[48:72] = bad[24:48]
    with pytest.raises(ValueError, match="unique"):
        p.allocation(bad)
    with pytest.raises(ValueError, match="exact"):
        p.allocation(bytes(400))


@pytest.mark.parametrize(("offset", "value"), [(32, 4), (36, 0), (40, 0), (44, 1)])
def test_wrong_selector_address_size_or_partition(offset, value):
    raw = table()
    struct.pack_into("<I", raw, offset, value)
    with pytest.raises(ValueError, match="allocation"):
        p.allocation(raw)


def test_exact_stop_start_and_no_emulation():
    assert p.request(False) == bytes(8)
    assert p.request(True) == bytes.fromhex("0100000100000000")
    for value in (0, 1, 2, 3, 20, None):
        with pytest.raises(ValueError, match="boolean"):
            p.request(value)


def test_state_word_and_wrong_chip():
    class Device:
        CHIP = p.m.CHIP_MT7921

        def rr(self, address):
            assert address == 0x02037214
            return 0x101

    assert p.snapshot(Device())["host_enabled_byte"] == 1
    assert p.snapshot(Device())["detector_region_byte"] == 1
    Device.CHIP = p.m.CHIP_MT7925
    with pytest.raises(ValueError, match="MT7961"):
        p.snapshot(Device())


def test_no_start_when_allocation_missing():
    class Device:
        CHIP = p.m.CHIP_MT7921

        def rr(self, address):
            assert address == p.STATE or p.TABLE <= address < p.TABLE + 432
            return 0

    with pytest.raises(ValueError, match="allocation"):
        p.control(Device(), True)
