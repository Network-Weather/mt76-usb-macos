# SPDX-License-Identifier: BSD-3-Clause-Clear
from types import SimpleNamespace

import pytest

from research.fixed_rate_readback import ITCR, ITDR0, ITDR1, read_slot


@pytest.mark.parametrize("index", [18, 25])
def test_read_selector_has_no_write_op_and_reads_only_data(index):
    calls = []
    dev = SimpleNamespace(
        CHIP="mt7925",
        wr=lambda a, v: calls.append(("write", a, v)),
        rr=lambda a: calls.append(("read", a)) or {ITDR0: 0x80, ITDR1: 0xC00}[a],
    )
    assert read_slot(dev, index) == (0x80, 0xC00)
    assert calls == [("write", ITCR, 0x80000000 | index), ("read", ITDR0), ("read", ITDR1)]


@pytest.mark.parametrize(
    ("chip", "index"), [("mt7921", 18), ("mt7925", 0), ("mt7925", 64), ("mt7925", True)]
)
def test_read_rejects_other_chips_and_slots_before_io(chip, index):
    with pytest.raises(ValueError, match="slots"):
        read_slot(SimpleNamespace(CHIP=chip), index)


@pytest.mark.parametrize("value", [None, True, -1, 0x100000000, 0xFFFFFFFF])
def test_invalid_bus_data_not_promoted_to_table_entry(value):
    dev = SimpleNamespace(CHIP="mt7925", wr=lambda *_: None, rr=lambda _: value)
    with pytest.raises(ValueError, match="table data"):
        read_slot(dev, 18)
