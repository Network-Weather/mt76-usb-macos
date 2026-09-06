# SPDX-License-Identifier: BSD-3-Clause-Clear
import json
import struct

import pytest

from research import rmac_ics_match as p


def normal(timestamp=0x12345678):
    raw = bytearray(88)
    struct.pack_into("<II", raw, 0, (2 << 27) | len(raw), (1 << 17) | (1 << 18))
    struct.pack_into("<I", raw, 32, timestamp)
    raw[48:64] = bytes(range(1, 17))
    raw[64:] = b"synthetic-private-header"
    return bytes(raw)


def aggregate(body):
    return struct.pack("<II", (12 << 27) | (3 << 16) | (8 + len(body)), 0) + body


def test_source_group_offsets_and_no_trailing_usb_bytes():
    values = p.signatures(normal() + b"trailing")
    assert values["timestamp4"] == struct.pack("<I", 0x12345678)
    assert values["prxv16"] == bytes(range(1, 17))
    assert values["mac_header24"] == b"synthetic-private-header"
    assert p.signatures(normal()[:70]) == {}


def test_aggregate_reducer_never_exports_private_signatures():
    n = normal()
    a = aggregate(n[32:36] + bytes(4) + n[48:64] + n[64:])
    out = p.reduce_matches([n], [a])
    assert out["unique_timestamp_plus_second_signature"] == {"mac_header24": 1, "prxv16": 1}
    assert {"signature": "timestamp4", "offset": 8, "matches": 1} in out["offset_match_counts"]
    assert "synthetic-private" not in json.dumps(out)
    assert str(0x12345678) not in json.dumps(out)
    # Neither timestamp nor payload added outside the declared DMA count matches.
    assert not p.reduce_matches([n], [aggregate(bytes(16)) + a])["records_with_signature_match"]


def test_repeated_signature_does_not_qualify_unique_frame():
    n = normal()
    a = aggregate(n[32:36] + n[48:64])
    assert not p.reduce_matches([n, n], [a])["unique_timestamp_plus_second_signature"]
    assert not p.reduce_matches([n], [aggregate(n[32:36])])[
        "unique_timestamp_plus_second_signature"
    ]


def test_bad_fcs_and_capture_caps():
    raw = bytearray(normal())
    struct.pack_into("<I", raw, 12, 1 << 24)
    assert p.signatures(raw) == {}
    with pytest.raises(ValueError, match="bounded"):
        p.reduce_matches([normal()] * 129, [])


def test_paired_fields_require_varied_references_not_constant_words():
    pairs = []
    for i in range(8):
        sig = {
            "prxv16": struct.pack("<4I", 0, i + 100, 0, 0),
            "timestamp4": struct.pack("<I", 1000 + i * 4000),
        }
        raw = bytearray(64)
        struct.pack_into("<I", raw, 16, 3000 + i * 4000)
        struct.pack_into("<I", raw, 36, i + 100)
        pairs.append((sig, bytes(raw)))
    result = p.paired_fields(pairs)
    assert result["vector_candidates"] == [
        {
            "source": "prxv16",
            "source_word": 1,
            "source_shift": 0,
            "bits": 32,
            "offset": 36,
            "shift": 0,
            "distinct_reference_values": 8,
        }
    ]
    assert result["clock_candidates"] == [
        {
            "offset": 16,
            "relative_minus_rxd_min": 0,
            "relative_minus_rxd_max": 0,
        }
    ]
    assert not p.paired_fields(pairs[:7])["vector_candidates"]


def test_legacy_signatures_respect_two_word_prxv_and_eighteen_word_crxv():
    raw = bytearray(136)
    struct.pack_into("<II", raw, 0, (2 << 27) | len(raw), (2 | 4 | 16) << 11)
    struct.pack_into("<I", raw, 24, 123456)
    raw[32:40] = bytes(range(1, 9))
    raw[40:112] = bytes(range(1, 73))
    raw[112:] = b"synthetic-private-header"
    result = p.legacy_signatures(raw)
    assert len(result["prxv8"]) == 8
    assert len(result["crxv72"]) == 72
    assert result["mac_header24"] == b"synthetic-private-header"
    out = p.reduce_matches([raw], [aggregate(raw[112:])], legacy=True)
    assert out["records_with_signature_match"] == {"mac_header24": 1}
    assert p.legacy_signatures(raw[:135]) == {}
