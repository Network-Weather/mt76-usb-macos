# SPDX-License-Identifier: BSD-3-Clause-Clear
import sys

import pytest

from research import normal_phy_counter_probe as p


@pytest.mark.parametrize("original", [0, 0xA00, 0xE00, 0xDEADBEEF, 0x7FFFFFFF])
def test_counter_control_changes_only_traced_bits(original):
    assert p.control_value(original, False) == original & ~0xE00
    assert p.control_value(original, True) == (original & ~0xE00) | 0xA00


@pytest.mark.parametrize("original", [-1, 0xFFFFFFFF, True, 1.0])
def test_counter_control_rejects_unmapped_or_invalid(original):
    with pytest.raises(ValueError, match="mapped"):
        p.control_value(original, True)


def test_both_opt_ins_required_before_usb(monkeypatch):
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("USB opened"))
    for flags in ([], ["--enable-counters"], ["--acknowledge-experimental-transmit"]):
        monkeypatch.setattr(sys, "argv", ["normal_phy", *flags])
        with pytest.raises(SystemExit) as exc:
            p.main()
        assert exc.value.code == 2
