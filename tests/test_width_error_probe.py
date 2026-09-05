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


def test_frequency_control_is_bounded_and_bracketed():
    assert len(p.FREQUENCY_PLAN) == len(p.RX_CHANNELS) == 6
    assert p.RX_CHANNELS == (6, 6, 8, 10, 6, 6)
    assert [width for _, _, width in p.FREQUENCY_PLAN] == [20, 40, 40, 40, 40, 20]
    assert {rate for _, rate, _ in p.FREQUENCY_PLAN} == {0x488}


def test_secondary_control_holds_receiver_fixed_across_width_alternation():
    assert len(p.SECONDARY_PLAN) == len(p.SECONDARY_CHANNELS) == 6
    assert p.SECONDARY_CHANNELS == (6, 10, 10, 10, 10, 6)
    assert [width for _, _, width in p.SECONDARY_PLAN] == [20, 20, 40, 20, 40, 20]
    assert {rate for _, rate, _ in p.SECONDARY_PLAN} == {0x488}


def test_receive_path_control_is_bounded_and_bracketed():
    assert len(p.RXPATH_PLAN) * 4 == 16
    assert [width for _, _, width in p.RXPATH_PLAN] == [20, 40, 40, 20]
    assert {rate for _, rate, _ in p.RXPATH_PLAN} == {0x488}


def test_error_history_has_matched_no_error_no_retune_control():
    assert len(p.STABILITY_PLAN) == len(p.ERROR_HISTORY_PLAN) == 6
    assert [width for _, _, width in p.STABILITY_PLAN] == [20, 40, 20, 40, 40, 20]
    assert [width for _, _, width in p.ERROR_HISTORY_PLAN] == [20, 40, 20, 40, 40, 20]
    assert {rate for _, rate, _ in p.STABILITY_PLAN} == {0x488}
    assert [rate for _, rate, _ in p.ERROR_HISTORY_PLAN] == [
        0x488,
        0x488,
        0x48F,
        0x488,
        0x488,
        0x488,
    ]


@pytest.mark.parametrize("plan", p.PLANS.values())
def test_all_suites_have_bounded_submissions_and_narrow_brackets(plan):
    assert len(plan) * 4 <= 28
    assert plan[0][2] == 20
    assert plan[-1][2] == 20
