# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import legacy_ics_own_probe as p


def test_hypotheses_require_exact_shape_and_known_header():
    raw = bytearray(272)
    struct.pack_into("<I", raw, 0, (12 << 27) | (3 << 16) | 272)
    header = b"synthetic-private-header"
    raw[120:144] = header
    struct.pack_into("<I", raw, 16, 2 << 4)
    struct.pack_into("<I", raw, 40, 30 | (31 << 8))
    struct.pack_into("<II", raw, 104, (0x1FFF << 19) | (29 << 13), 127)
    struct.pack_into("<II", raw, 44, 0x8081, (0xBC << 5) | (0xB9 << 14))
    result = p.own_ics_observation(raw, {4: (header + b"payload", b"")})
    assert result["sequence"] == 4
    assert result["rcpi_bytes_at40"] == [30, 31]
    assert result["source_prxv2_at104_hypothesis"] == {"cfo_signed20": -1, "snr_bits": 29}
    assert result["firmware_fagc_fields"] == {
        "fagc_ib0_raw_s8": -127,
        "fagc_ib1_raw_s8": -128,
        "fagc_wb0_raw_s8": -68,
        "fagc_wb1_raw_s8": -71,
    }
    assert p.own_ics_observation(raw, {}) is None
    assert p.own_ics_observation(raw, {4: (header, b""), 5: (header, b"")}) is None
    struct.pack_into("<I", raw, 0, (12 << 27) | (2 << 16) | 272)
    assert p.own_ics_observation(raw, {4: (header, b"")}) is None


def test_hardware_collection_rejects_unbounded_packets():
    with pytest.raises(ValueError, match="four or eight"):
        p.acquire(None, None, {})


def test_only_fixed_previously_qualified_rate_and_ltf_choices():
    assert p.PHY_SETTINGS == {
        "ht8": {"code": 0x488, "ltf": 0},
        "he2ss0": {"code": 0x600, "ltf": 0},
        "he2ss0-ltf1": {"code": 0x600, "ltf": 1},
        "cck1": {"code": 0, "ltf": 0},
    }
