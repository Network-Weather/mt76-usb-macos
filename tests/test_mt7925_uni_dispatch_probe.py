# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research import mt7925_uni_dispatch_probe as p


class Device:
    CHIP = p.m.CHIP_MT7925

    def __init__(self, count=2):
        self.count = count
        self.reads = []

    def rr(self, address):
        self.reads.append(address)
        if address == p.COUNT_ADDRESS:
            return self.count
        if address == p.TABLE_ADDRESS:
            return 0xAAAA002B
        if address == p.TABLE_ADDRESS + 4:
            return 0xE00A1564
        return 0


def test_exact_table_stride_and_u16_key():
    dev = Device()
    result = p.table(dev)
    assert result["count"] == 2
    assert result["records"][0] == {
        "address": hex(p.TABLE_ADDRESS),
        "cid": 0x2B,
        "handler": "0xe00a1564",
    }
    assert dev.reads == [
        p.COUNT_ADDRESS,
        p.TABLE_ADDRESS,
        p.TABLE_ADDRESS + 4,
        p.TABLE_ADDRESS + 8,
        p.TABLE_ADDRESS + 12,
        p.COUNT_ADDRESS,
    ]
    assert p.COUNT_ADDRESS == 0x02212800 + 112160
    assert p.TABLE_ADDRESS == 0x02212800 + 38716


@pytest.mark.parametrize("count", [0, 62, 255, 0xFFFFFFFF])
def test_count_cap_before_table_read(count):
    dev = Device(count)
    with pytest.raises(ValueError, match="fixed read bound"):
        p.table(dev)
    assert dev.reads == [p.COUNT_ADDRESS]


def test_maximum_read_bound():
    dev = Device(61)
    assert len(p.table(dev)["records"]) == 61
    assert len(dev.reads) == 124
    assert max(a for a in dev.reads if a != p.COUNT_ADDRESS) == 0x0221C120


def test_fixed_hash_windows():
    dev = Device()
    assert not any(row["matches"] for row in p.verify(dev))
    assert len(dev.reads) == 1100
    assert len(set(dev.reads)) == 1100
