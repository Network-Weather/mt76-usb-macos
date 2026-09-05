# SPDX-License-Identifier: BSD-3-Clause-Clear
import sys

import pytest

from research import width_error_probe as p


@pytest.mark.parametrize("bits", range(7))
def test_every_opt_in_required_before_usb(monkeypatch, bits):
    flags = ("--acknowledge-experimental-transmit", "--enable-error-capture", "--enable-counters")
    monkeypatch.setattr(
        sys, "argv", ["probe", *(flag for i, flag in enumerate(flags) if bits & (1 << i))]
    )
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("unexpected USB open"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2


def test_fixed_plan_has_narrow_and_error_controls():
    assert len(p.PLAN) * 4 == 28
    assert [(rate, width) for _, rate, width in p.PLAN] == [
        (0x488, 20),
        (0x48F, 20),
        (0x488, 40),
        (0x488, 20),
        (0x600, 20),
        (0x600, 40),
        (0x600, 20),
    ]


def test_failed_metadata_never_authenticates_or_exports_payload():
    decoded = {
        "fcs_err": True,
        "frame": b"private-frame-identifier",
        "phy": {"mode_name": "HT", "mcs": 15, "nss": 2},
        "rssi": -100,
    }
    meta = p.failed_metadata(decoded)
    assert not meta["own_frame_identity_verified"]
    assert "private-frame" not in repr(meta)
    assert "frame" not in meta
