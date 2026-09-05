# SPDX-License-Identifier: BSD-3-Clause-Clear
import sys

import pytest

from research import rxv_report_probe as p


def test_only_rx_report_bit_changes():
    off = p.request(False)
    on = p.request(True)
    assert off == bytes.fromhex("000000000100080000000000")
    assert on == bytes.fromhex("000000000100080001000000")
    assert on[9] == 0  # TX-vector reporting never enabled.


@pytest.mark.parametrize("value", [0, 1, 2, None, "True"])
def test_no_arbitrary_enable_values(value):
    with pytest.raises(ValueError, match="boolean"):
        p.request(value)


def test_opt_in_required_before_usb(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["rxv_report", "--chip", "mt7925"])
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("USB opened"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2
