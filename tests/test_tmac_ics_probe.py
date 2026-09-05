# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import tmac_ics_probe as p


def test_tmac_source_layout_differs_only_selector():
    tx, rx = p.request(True), p.mac.request(True)
    assert len(tx) == 92
    assert [i for i, (a, b) in enumerate(zip(tx, rx, strict=True)) if a != b] == [16]
    assert struct.unpack_from("<7H", tx, 16) == (0, 0, 0, 0, 0, 0, 0)


def test_matching_is_exact_and_declared_length_bounded():
    payload, descriptor = b"own synthetic packet", bytes(range(64))
    wire = bytes(4) + descriptor + payload
    body = descriptor + payload
    raw = struct.pack("<I", (12 << 27) | (1 << 16) | (8 + len(body))) + bytes(4) + body
    assert p.own_matches(raw, {5: (payload, wire)}) == [
        {"sequence": 5, "kind": "frame", "offset": 72},
        {"sequence": 5, "kind": "descriptor", "offset": 8},
    ]
    no_body = struct.pack("<I", (12 << 27) | 8) + bytes(4) + body
    assert p.own_matches(no_body, {5: (payload, wire)}) == []


def test_no_match_does_not_export_any_content():
    raw = struct.pack("<I", (12 << 27) | 16) + bytes(4) + b"private!"
    assert p.own_matches(raw, {5: (b"own synthetic", b"a" * 80)}) == []


def test_own_field_match_requires_two_sequences_and_two_lengths():
    raw = bytearray(288)
    struct.pack_into("<I", raw, 0, (12 << 27) | (2 << 16) | 288)
    struct.pack_into("<I", raw, 124, 5 << 20)
    struct.pack_into("<I", raw, 272, 5)
    struct.pack_into("<I", raw, 48, 69)
    struct.pack_into("<I", raw, 96, 69)
    struct.pack_into("<I", raw, 24, 32 << 16)
    struct.pack_into("<I", raw, 88, 1)
    packets = {5: (bytes(65), b"")}
    assert p.own_field_match(raw, packets) == {
        "sequence": 5,
        "matched_frame_bytes_with_fcs": 69,
        "power_raw_candidate": 32,
        "rate_raw_candidate": 1,
    }
    assert p.own_field_match(raw, {}) is None
    struct.pack_into("<I", raw, 272, 6)
    assert p.own_field_match(raw, packets) is None
    struct.pack_into("<I", raw, 272, 5)
    struct.pack_into("<I", raw, 96, 70)
    assert p.own_field_match(raw, packets) is None


def test_prepared_packet_cap():
    with pytest.raises(ValueError, match="four"):
        p.acquire(None, None, {})


def test_bounded_rate_patterns():
    assert [p.planned_rate(i, "fixed") for i in range(4)] == [0, 0, 0, 0]
    assert [p.planned_rate(i, "blocks") for i in range(4)] == [0, 0, 1, 1]
    assert [p.planned_rate(i, "alternating") for i in range(4)] == [0, 1, 0, 1]
    with pytest.raises(ValueError, match="CCK1/2"):
        p.planned_rate(0, "sweep")


def test_tmac_field_pair_and_masks():
    assert p.TMAC_WORDS[0x84C810] & 0xFFFF == 0
    assert p.TMAC_WORDS[0x84C270] & 0xFFFF == 0x120
    assert p.MASKS == {0x820E4120: 1, 0x820E705C: 1 << 24}


@pytest.mark.parametrize("sequence", range(4, 8))
def test_power_and_length_differentials_are_independent(sequence):
    class Device:
        CHIP = p.m.CHIP_MT7925

    plain, plain_wire = p.prepared_packet(Device(), sequence, bytes(8))
    changed, wire = p.prepared_packet(Device(), sequence, bytes(8), True)
    assert plain == changed
    assert len(changed) == (65 if sequence % 2 == 0 else 193)
    assert wire[:12] == plain_wire[:12]
    assert wire[16:] == plain_wire[16:]
    word, old = struct.unpack_from("<I", wire, 12)[0], struct.unpack_from("<I", plain_wire, 12)[0]
    assert word & ~(63 << 26) == old & ~(63 << 26)
    assert word >> 26 == (60 if sequence % 4 >= 2 else 0)


def test_restore_rejects_other_addresses():
    class Device:
        CHIP = p.m.CHIP_MT7925

    with pytest.raises(ValueError, match="TMAC ICS masks"):
        p.restore(Device(), {0x820E4124: 0})


def test_differential_candidates_export_no_record_words():
    packets, records, statuses = {}, [], []
    for i in range(36, 40):
        payload = bytes(65 if i % 2 == 0 else 193)
        packets[i] = payload, b""
        timestamp = 100000 + (i - 36) * 30000
        raw = bytearray(288)
        struct.pack_into("<III", raw, 8, i << 20, len(payload) + 4, timestamp + 40)
        power = 36 if i % 4 < 2 else 32
        struct.pack_into("<I", raw, 24, power << 16)
        rate = i % 2
        struct.pack_into("<I", raw, 28, rate << 8)
        records.append((i, bytes(raw)))
        statuses.append(
            {"sequence": i, "timestamp_raw": timestamp, "power_raw": power, "rate_raw": rate}
        )
    result = p.candidate_fields(records, packets, statuses)
    assert result["qualified_temporal_pairing"]
    assert {"offset": 8, "shift": 20, "bits": 12} in result["sequence_candidates"]
    assert {"offset": 12, "shift": 0, "bits": 16, "bytes_added_to_frame": 4} in result[
        "length_candidates"
    ]
    assert result["clock_candidates"] == [{"offset": 16, "minus_txs_timestamp_raw": [40] * 4}]
    assert result["relative_clock_candidates"] == [{"offset": 16, "relative_minus_txs": [0] * 4}]
    assert {"offset": 24, "shift": 16, "bits": 8, "matches_txs_power_raw": True} in result[
        "power_candidates"
    ]
    assert {"offset": 28, "shift": 8, "bits": 14, "matches_txs_rate_raw": True} in result[
        "rate_candidates"
    ]
    assert "record_words" not in result
    assert not p.candidate_fields(records[:3], packets, statuses)["qualified_temporal_pairing"]
    assert not p.candidate_fields(records, packets, statuses[:3])["qualified_temporal_pairing"]
