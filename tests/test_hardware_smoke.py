# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Network Weather, Inc.
"""Offline tests for the redacted hardware smoke report helpers."""

from scripts import hardware_smoke as smoke


def test_all_plan_covers_expected_tri_band_channels():
    assert len(smoke.PLANS["all"]) == 43
    assert {band for band, _ in smoke.PLANS["all"]} == {"2.4GHz", "5GHz", "6GHz"}


def test_frame_family_uses_80211_frame_control_type():
    assert smoke.frame_family(b"\x80\x00") == "management"
    assert smoke.frame_family(b"\xd4\x00") == "control"
    assert smoke.frame_family(b"\x08\x00") == "data"
    assert smoke.frame_family(b"\x0c\x00") == "other"
    assert smoke.frame_family(b"") == "other"
