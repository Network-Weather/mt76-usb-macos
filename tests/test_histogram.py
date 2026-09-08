# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import mt76_histogram as hist
from tests.test_csi_measurements import event


def histogram_event(values=None):
    if values is None:
        values = [0xFFFFFFFF] * 11 + list(range(11))
    return event(struct.pack("<4xHH22I", 2, 92, *values), eid=0x36)


def bad_histogram_events():
    raw = histogram_event()
    for size in range(len(raw)):
        yield raw[:size]
        changed = bytearray(raw)
        struct.pack_into("<H", changed, 0, size)
        yield bytes(changed)
    for index in (2, 3, 36, 37, 44, 45, 46, 47, 48, 49, 50, 51):
        changed = bytearray(raw)
        changed[index] ^= 8 if index == 3 else 1
        yield bytes(changed)
    yield event(raw[44:] + bytes(4), eid=0x36)
    yield event(raw[44:-4], eid=0x36)


def test_histogram_profile_distinct_views_and_large_totals():
    report = hist.parse_histogram_event("mt7925", histogram_event())
    assert report.bins == ((0xFFFFFFFF,) * 11, tuple(range(11)))
    assert report.totals == (11 * 0xFFFFFFFF, 55)
    assert report.source == "firmware_timer"
    assert report.threshold_labels_raw == (-92, -89, -86, -83, -80, -75, -70, -65, -60, -55)
    assert hist.parse_histogram_event("mt7925", histogram_event() + b"padding") == report
    assert hist.parse_histogram_event("mt7925", histogram_event([0] * 22)).totals == (0, 0)
    legacy = hist.parse_legacy_histogram("mt7921", struct.pack("<11I", *range(11)))
    assert legacy.bins == (tuple(range(11)),)
    assert legacy.source == "legacy_ordinary"


def test_histogram_rejects_malformed_and_wrong_chip():
    for raw in bad_histogram_events():
        with pytest.raises(ValueError, match="histogram"):
            hist.parse_histogram_event("mt7925", raw)
    for chip in ("mt7921", "mt7996", "", None):
        with pytest.raises(ValueError, match="histogram"):
            hist.parse_histogram_event(chip, histogram_event())
        with pytest.raises(ValueError, match="histogram"):
            hist.build_histogram_request(chip)
    for chip, raw in [("mt7925", bytes(44)), ("mt7921", bytes(43)), ("mt7921", bytes(45))]:
        with pytest.raises(ValueError, match="histogram"):
            hist.parse_legacy_histogram(chip, raw)


@pytest.mark.parametrize("status", [0, 1, 0xC00000BB, 0xFFFFFFFF])
def test_histogram_ack_actual_status_and_request(status):
    raw = event(struct.pack("<II", 0x36, status), eid=1, sequence=9)
    assert hist.parse_histogram_ack("mt7925", raw, 9) == status
    assert hist.build_histogram_request("mt7925") == bytes.fromhex("0000000002000400")
    for sequence in (0, 8, 16, True, None):
        with pytest.raises(ValueError, match="histogram"):
            hist.parse_histogram_ack("mt7925", raw, sequence)
    for bad in (raw[:-1], event(bytes(8), eid=1, sequence=9), histogram_event()):
        with pytest.raises(ValueError, match="histogram"):
            hist.parse_histogram_ack("mt7925", bad, 9)


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--chip", "bad"],
        ["--chip", "mt7925", "--fw", "/unused"],
        ["--chip", "mt7925", "--fw", "/unused", "--channel", "149"],
    ],
)
def test_histogram_probe_refuses_before_usb(extra):
    probe = Path(__file__).resolve().parents[1] / "research/histogram_session_probe.py"
    result = subprocess.run(  # noqa: S603 -- fixed local probe and refusal fixtures
        [sys.executable, str(probe), *extra], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
