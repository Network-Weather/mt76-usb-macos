# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import mt7921u as m
from research.icap_status_probe import event_summary, status_request


def test_status_only_payload():
    body = status_request()
    assert len(body) == 88
    assert body[:8] == struct.pack("<B3xI", 1, 12)
    assert body[8:] == bytes(80)


def test_event_shape_and_candidate_not_claimed_as_valid_status():
    raw = bytearray(104)
    struct.pack_into("<I", raw, 0, len(raw) | (m.PKT_TYPE_RX_EVENT << 27))
    raw[28], raw[29], raw[32] = 0xED, 0, 4
    struct.pack_into("<II", raw, 36, 12, 1)
    value = event_summary(raw, 2)
    assert value["unsolicited_sequence"]
    assert not value["sequence_matches"]
    assert value["candidate_capture_done_raw"] == 1
    assert event_summary(raw[:-1], 2) is None
    assert event_summary(b"", 2) is None
    raw[32] = 0x46
    assert "candidate_capture_done_raw" not in event_summary(raw, 2)
    struct.pack_into("<I", raw, 0, len(raw) | (m.PKT_TYPE_NORMAL << 27))
    assert event_summary(raw, 2) is None
