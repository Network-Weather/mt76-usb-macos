# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research.icap_capture_probe import (
    capture_request,
    channel_request,
    data_request,
    summarize_data,
)


@pytest.mark.parametrize("count", [64, 256])
def test_capture_is_bounded_onchip_no_dma(count):
    body = capture_request(count)
    assert len(body) == 88
    action, function = struct.unpack_from("<B3xI", body)
    assert action == 1
    assert function == 11
    words = struct.unpack_from("<20I", body, 8)
    assert words[:6] == (1, 0, 0, 0, count, count)
    assert words[6:] == (0,) * 14
    stopped = capture_request(count, trigger=False)
    assert stopped[:8] == body[:8]
    assert stopped[8:12] == bytes(4)
    assert stopped[12:] == body[12:]


@pytest.mark.parametrize("count", [0, -1, 1, 257, 65536])
def test_unbounded_or_unknown_sizes_rejected(count):
    with pytest.raises(ValueError, match="bounded sample count"):
        capture_request(count)


def test_data_request_only_one_bank_one_kib():
    assert len(data_request()) == 88
    assert struct.unpack_from("<B3x7I", data_request()) == (1, 17, 0, 4, 1, 1, 0, 0)
    assert data_request()[32:] == bytes(56)


def test_channel_setup_never_starts_tx():
    assert channel_request(1, 13) == struct.pack("<B3xII", 1, 1, 13)
    with pytest.raises(ValueError, match="only fixed ICAP"):
        channel_request(1, 1)


def test_iq_statistics_never_include_samples():
    body = struct.pack("<12I4i", 17, 0, 1, 4, 1, 4, 0, 0, 0, 0, 0, 0, -2, 0, 1, 1)
    result = summarize_data(body)
    assert result["decoded_words"] == 4
    assert result["nonzero_words"] == 3
    assert result["unique_values"] == 3
    assert result["min_value"] == -2
    assert result["max_value"] == 1
    assert "samples" not in result
    assert summarize_data(body[:-1])["unexpected_data_shape"]
    assert summarize_data(b"") is None
