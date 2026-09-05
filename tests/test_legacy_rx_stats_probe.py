# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research.legacy_rx_stats_probe import request, summarize


def test_fixed_bounded_request():
    assert request(1) == struct.pack("<III", 1, 72, 0)
    assert request(1, 1) == struct.pack("<III", 1, 72, 1)
    assert len(request(5)) == 12
    for sequence in (0, 6, -1, True, 1.0):
        with pytest.raises(ValueError, match="five bounded"):
            request(sequence)
    for band in (-1, 2, True, 0.0):
        with pytest.raises(ValueError, match="band"):
            request(1, band)


def test_mixed_endian_statistics_prefix():
    body = struct.pack("<II", 2, 72) + struct.pack(">72I", *range(72))
    assert summarize(body, 2)["prefix_words_be"] == list(range(66))
    assert summarize(body + bytes(4), 2)["prefix_words_be"] == list(range(66))
    for invalid in (body[:-1], body + b"\0", struct.pack("<II", 2, 73) + body[8:]):
        assert "prefix_words_be" not in summarize(invalid, 2)
    assert "prefix_words_be" not in summarize(body, 3)
    assert summarize(b"", 1) == {"body_bytes": 0}


def test_measured_candidate_layout_does_not_replace_reference_hypothesis():
    body = struct.pack("<III72I", 1, 72, 0, *range(72))
    result = summarize(body, 1)
    assert result["reported_band_u32"] == 0
    assert result["uninterpreted_tail_bytes"] == 24
    assert result["candidate_prefix_words_le"] == list(range(66))
    assert result["prefix_words_be"][:3] == [0, 0, 1 << 24]


def test_extra_reply_word_is_band_not_status():
    body = struct.pack("<III72I", 2, 72, 1, *range(72))
    result = summarize(body, 2)
    assert result["reported_band_u32"] == 1
    assert "candidate_status_u32" not in result
