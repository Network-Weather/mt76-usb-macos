# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Opt-in reporting-bit lifetime, including uncertain write failures."""

import pytest

from mt76_measurements import Group5Guard


class Register:
    CHIP = "mt7921"

    def __init__(self, initial=0, fail=0, mismatch=0):
        self.value = initial
        self.step = 0
        self.fail = fail
        self.mismatch = mismatch

    def check(self, address):
        assert address == Group5Guard.REGISTER
        self.step += 1
        if self.step == self.fail:
            raise OSError("synthetic register failure")

    def rr(self, address):
        self.check(address)
        return self.value ^ (Group5Guard.BIT if self.step == self.mismatch else 0)

    def wr(self, address, value):
        self.value = value  # Write can reach hardware even when transport reports failure.
        self.check(address)


@pytest.mark.parametrize("initial", [0x42, Group5Guard.BIT | 0x42])
@pytest.mark.parametrize("failure", range(7))
def test_guard_preserves_other_bits_and_retries(initial, failure):
    dev = Register(initial, failure)
    guard = Group5Guard(dev)
    if failure in (1, 2, 3):
        with pytest.raises(OSError, match="synthetic register failure"):
            guard.begin()
        assert guard.active == (failure != 1)
    else:
        guard.begin()
        assert guard.active
        assert dev.value & guard.BIT
        with pytest.raises(RuntimeError, match="already active"):
            guard.begin()
    dev.value ^= 1  # Another field changes: restore only owns the Group5 bit.
    if failure in (4, 5, 6):
        with pytest.raises(OSError, match="synthetic register failure"):
            guard.restore()
        assert guard.active
    guard.restore()
    assert not guard.active
    assert dev.value == initial ^ 1
    step = dev.step
    guard.restore()
    assert dev.step == step


@pytest.mark.parametrize("mismatch", [3, 6])
def test_readback_mismatch_keeps_guard_for_cleanup(mismatch):
    dev = Register(mismatch=mismatch)
    guard = Group5Guard(dev)
    if mismatch == 3:
        with pytest.raises(RuntimeError, match="enable readback"):
            guard.begin()
    else:
        guard.begin()
        with pytest.raises(RuntimeError, match="restore readback"):
            guard.restore()
    assert guard.active
    dev.mismatch = 0
    guard.restore()
    assert not guard.active
    assert not dev.value & guard.BIT


def test_other_chips_refused_before_io():
    dev = Register()
    dev.CHIP = "mt7925"
    guard = Group5Guard(dev)
    with pytest.raises(ValueError, match="MT7921 only"):
        guard.begin()
    guard.restore()
    assert dev.step == 0
