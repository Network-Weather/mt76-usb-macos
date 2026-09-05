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
    result = p.own_ics_observation(raw, {4: (header + b"payload", b"")})
    assert result["sequence"] == 4
    assert result["rcpi_bytes_at40"] == [30, 31]
    assert result["source_prxv2_at104_hypothesis"] == {"cfo_signed20": -1, "snr_bits": 29}
    assert p.own_ics_observation(raw, {}) is None
    assert p.own_ics_observation(raw, {4: (header, b""), 5: (header, b"")}) is None
    struct.pack_into("<I", raw, 0, (12 << 27) | (2 << 16) | 272)
    assert p.own_ics_observation(raw, {4: (header, b"")}) is None


def test_hardware_collection_rejects_unbounded_packets():
    with pytest.raises(ValueError, match="four or eight"):
        p.acquire(None, None, {})
