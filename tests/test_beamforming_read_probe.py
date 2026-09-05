# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import beamforming_read_probe as p


def event(tag=5, seq=0, payload=None):
    size = p.EXPECTED_TLV_SIZE[tag]
    body = bytearray(size + 4)
    struct.pack_into("<HH", body, 4, tag, size)
    if payload is not None:
        body[12:] = payload
    raw = bytearray(44) + body
    struct.pack_into("<I", raw, 0, len(raw) | p.m.PKT_TYPE_RX_EVENT << 27)
    raw[36:38] = bytes((0x33, seq))
    return raw


def test_request_shapes_and_read_fields():
    data = p.read_request(5, 1, 1)
    assert len(data) == 72
    assert struct.unpack_from("<HHBBB", data, 4) == (5, 68, 1, 1, 0)
    assert data[11:] == bytes(61)
    data = p.read_request(7, 1, 0)
    assert len(data) == 16
    assert struct.unpack_from("<HHBBHB", data, 4) == (7, 12, 1, 0, 0, 0)


def test_candidate_tag_bits_and_snr_bytes():
    payload = bytearray(56)
    struct.pack_into(
        "<I", payload, 0, 1 | 1 << 10 | 2 << 11 | 4 << 14 | 1 << 17 | 2 << 18 | 1 << 21 | 1 << 28
    )
    payload[16:24] = bytes(range(8))
    fields = p.candidate_tag_fields(payload)
    assert fields == {
        "profile_id_raw": 1,
        "explicit_bf_raw": 1,
        "bandwidth_code_raw": 2,
        "mode_code_raw": 4,
        "mu_raw": 1,
        "nrow_raw": 2,
        "ncol_raw": 1,
        "invalid_profile_bit": True,
        "snr_sts_bytes_raw": list(range(8)),
    }
    with pytest.raises(ValueError, match="exactly two"):
        p.candidate_tag_fields(payload[:-1])


@pytest.mark.parametrize("tag", [0, 1, 3, 4, 6, 8, 0x16, 0x17, True])
def test_no_sounding_profile_writes_or_allocations(tag):
    with pytest.raises(ValueError, match="only PFMU read"):
        p.read_request(tag)


@pytest.mark.parametrize("value", [-1, 2, 255, True, 0.0])
def test_profile_and_direction_are_bounded(value):
    with pytest.raises(ValueError, match="only profile"):
        p.read_request(5, profile=value)
    with pytest.raises(ValueError, match="BFer selector"):
        p.read_request(5, bfer=value)


@pytest.mark.parametrize("tag", [5, 7])
def test_exact_reply_and_unsolicited_sequence(tag):
    raw = event(tag)
    out = p.event_summary(raw, 4, tag)
    assert out["recognized_profile_reply"]
    assert not out["sequence_matches"]
    assert out["payload_nonzero_bytes"] == 0
    assert out["payload_bytes"] == p.EXPECTED_TLV_SIZE[tag] - 8
    assert not any("hex" in key or "words" in key for key in out)
    assert p.event_summary(event(tag, 4), 4, tag)["sequence_matches"]
    assert p.event_summary(event(tag, 3), 4, tag) is None


def test_truncation_wrong_tag_and_size_not_recognized():
    raw = event()
    assert p.event_summary(raw[:-1], 4, 5) is None
    assert "recognized_profile_reply" not in p.event_summary(raw, 4, 7)
    struct.pack_into("<H", raw, 50, 63)
    assert "recognized_profile_reply" not in p.event_summary(raw, 4, 5)


def test_ambient_frames_and_status_not_treated_as_profiles():
    raw = event()
    struct.pack_into("<I", raw, 0, len(raw) | p.m.PKT_TYPE_NORMAL << 27)
    assert p.event_summary(raw, 4, 5) is None
    raw = event()
    struct.pack_into(
        "<I",
        raw,
        0,
        len(raw) | p.m.PKT_TYPE_RX_EVENT << 27 | p.m.PKT_FLAG_NORMAL_MCU << p.m.RXD0_PKT_FLAG_SHIFT,
    )
    assert p.event_summary(raw, 4, 5) is None
    raw = event()
    raw[36] = 1
    struct.pack_into("<II", raw, 44, 0x33, 0xC00000BB)
    out = p.event_summary(raw, 4, 5)
    assert out["command_result_status"] == 0xC00000BB
    assert "recognized_profile_reply" not in out
