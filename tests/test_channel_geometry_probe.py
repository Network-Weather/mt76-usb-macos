# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

import mt7921u as m
from research.channel_geometry_probe import (
    FRAMES,
    PHASES,
    phase_sequence,
    probe_frame,
    status_records,
)


def test_plan_bounds_and_paired_primary_controls():
    assert len(PHASES) * FRAMES == 84
    assert PHASES[0] == PHASES[-1]
    assert all(tx in (36, 44) for tx, _, _, _ in PHASES)
    assert (36, 36, 42, 80) in PHASES
    assert (44, 36, 42, 80) in PHASES
    assert (44, 44, 42, 80) in PHASES
    assert (36, 44, 42, 80) in PHASES


def test_phase_sequences_reject_previous_and_next_dwell():
    assert phase_sequence(12, 1)
    assert phase_sequence(23, 1)
    assert not phase_sequence(11, 1)
    assert not phase_sequence(24, 1)
    frame = probe_frame(23)
    assert struct.unpack_from("<H", frame, 22)[0] >> 4 == 23
    assert frame[-3:] == bytes((1, 1, 0x8C))


@pytest.mark.parametrize(
    ("chip", "prefix", "stride"), [(m.CHIP_MT7921, 8, 32), (m.CHIP_MT7925, 16, 48)]
)
def test_status_geometry_for_both_chips(chip, prefix, stride):
    raw = struct.pack("<I", prefix + stride) + bytes(prefix - 4)
    raw += struct.pack("<II", 0x4B, (23 << 20) | 26) + bytes(stride - 8)
    assert status_records(raw, chip) == [
        {"sequence": 23, "rate_raw": 75, "power_raw": 26, "error_bits": 0}
    ]
    assert status_records(raw[:-1], chip) == []
