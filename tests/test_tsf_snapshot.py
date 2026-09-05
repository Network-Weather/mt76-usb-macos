# SPDX-License-Identifier: BSD-3-Clause-Clear
from types import SimpleNamespace

import pytest

from research.tsf_snapshot import TCR0, UTTR0, UTTR1, snapshot


@pytest.mark.parametrize("chip", ["mt7921", "mt7925"])
def test_snapshot_requests_only_mode3_and_never_sets_tsf(chip):
    calls = []
    values = iter((0x100, 0x89ABCDEF, 1, 0x100))

    def read(address):
        calls.append(("read", address))
        return next(values)

    dev = SimpleNamespace(CHIP=chip, rr=read, wr=lambda a, v: calls.append(("write", a, v)))
    out = snapshot(dev)
    assert out["tsf_raw"] == 0x189ABCDEF
    assert calls == [
        ("read", TCR0),
        ("write", TCR0, 0x103),
        ("read", UTTR0),
        ("read", UTTR1),
        ("read", TCR0),
    ]
    assert out["host_before_seconds"] <= out["host_write_done_seconds"] <= out["host_after_seconds"]


@pytest.mark.parametrize("before", [None, True, -1, 0xFFFFFFFF, 1, 2])
def test_invalid_or_busy_snapshot_rejected_before_write(before):
    with pytest.raises(ValueError, match="control"):
        snapshot(SimpleNamespace(CHIP="mt7925", rr=lambda _: before))


def test_other_mode_not_used_as_clock_sample():
    values = iter((0, 100, 0, 1))
    with pytest.raises(ValueError, match="read mode"):
        snapshot(SimpleNamespace(CHIP="mt7925", rr=lambda _: next(values), wr=lambda *_: None))


def test_read_mode_can_remain_set_and_zero_is_not_invented_as_advancing_clock():
    values = iter((0x1640003, 0, 0, 0x1640003))
    out = snapshot(SimpleNamespace(CHIP="mt7925", rr=lambda _: next(values), wr=lambda *_: None))
    assert out["tsf_raw"] == 0
    assert out["read_mode_retained"] is True
