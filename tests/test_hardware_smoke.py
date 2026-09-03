# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
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


def test_reference_reports_match_the_schema_shape():
    """Both redacted reference reports carry every required key and a valid status."""
    import json
    from pathlib import Path

    docs = Path(__file__).resolve().parent.parent / "docs"
    schema = json.loads((docs / "hardware-smoke.schema.json").read_text())
    required = set(schema["required"])
    statuses = set(schema["properties"]["status"]["enum"])
    for name in ("hardware-smoke-reference.json", "hardware-smoke-reference-mt7925.json"):
        report = json.loads((docs / name).read_text())
        assert required <= set(report), name
        assert set(report) - required <= {"error"}, name  # additionalProperties: false
        assert report["status"] in statuses, name
        assert report["device"]["usb_id"] in {"0e8d:7961", "0846:9072"}, name
