# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import legacy_ics_rf_probe as p


def test_cache_match_requires_stability_and_known_header():
    cache = bytearray(96)
    struct.pack_into("<I", cache, 0, 2 << 4)
    struct.pack_into("<II", cache, 80, (123 << 19) | (29 << 13), 0)
    raw = bytearray(272)
    struct.pack_into("<I", raw, 0, (12 << 27) | (3 << 16) | 272)
    raw[16:88] = cache[:72]
    raw[120:144] = b"synthetic-private-header"
    raw[176:192] = cache[80:96]
    packets = {4: (bytes(raw[120:144]) + b"payload", b"")}
    result = p.compare_cache(cache, cache, [raw], packets)
    assert result["matched_own_crxv_sequences"] == [4]
    assert {"sequence": 4, "offset": 176, "cfo_and_snr_masks_match": True} in result[
        "candidate_fields"
    ]
    assert result["prxv2_16byte_matches"] == [{"sequence": 4, "offsets": [176]}]
    assert not p.compare_cache(cache, cache, [raw], {})["candidate_fields"]
    assert not p.compare_cache(cache, bytes(96), [raw], packets)["candidate_fields"]


def test_zero_cache_and_bounds_are_not_evidence():
    assert not p.compare_cache(bytes(96), bytes(96), [], {})["candidate_fields"]
    with pytest.raises(ValueError, match="bounded"):
        p.compare_cache(bytes(92), bytes(96), [], {})
    with pytest.raises(ValueError, match="four"):
        p.rf_collect(None, None, {})


def test_frequency_units_and_two_channel_allowlist():
    assert struct.unpack("<B3xII", p.frequency_request(6)) == (1, 18, 2437000)
    assert struct.unpack("<B3xII", p.frequency_request(36)) == (1, 18, 5180000)
    with pytest.raises(ValueError, match="channel6/36"):
        p.frequency_request(52)
