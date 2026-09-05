# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import station_testmode_probe as p
from research.testmode_receiver_probe import rx_setting


@pytest.mark.parametrize("selector", p.QUERIES)
def test_read_only_at_queries(selector):
    assert p.at_query(selector) == struct.pack("<B3xII", 2, selector, 0)


@pytest.mark.parametrize("selector", [1, 2, 45, 64, 67, 255])
def test_no_tx_configuration_or_efuse(selector):
    with pytest.raises(ValueError, match="not allowlisted"):
        p.at_query(selector)


@pytest.mark.parametrize("tag", [8, 9])
def test_rx_stat_tags(tag):
    assert p.rx_query(tag) == struct.pack("<4xHH4x", tag, 8)


def test_shapes_and_unrelated_replies():
    assert "value_u32" not in p.summarize(struct.pack("<II", 99, 123), 34)
    assert p.summarize(struct.pack("<II", 34, 123), 34)["value_u32"] == 123
    assert p.summarize(b"", 34)["reply_bytes"] == 0
    result = p.summarize(struct.pack("<II24x", 0x32, 0xC00000BB))
    assert result["status_u32"] == 0xC00000BB
    assert "recognized_v2" not in result


def test_v2_requires_exact_layout():
    body = bytearray(528)
    struct.pack_into("<HHHHH2xI", body, 4, 7, 524, 1, 2, 3, 4)
    assert p.summarize(body)["band"] == {
        "fcs_error": 1,
        "length_mismatch": 2,
        "fcs_ok": 3,
        "mdrdy": 4,
    }
    assert "recognized_v2" not in p.summarize(body[:-1])


@pytest.mark.parametrize(("selector", "value"), [(1, 1), (1, 10), (18, 0), (18, 2412000), (15, 2)])
def test_receiver_settings_exclude_transmit_and_other_channels(selector, value):
    with pytest.raises(ValueError, match="only fixed-channel receive"):
        rx_setting(selector, value)


@pytest.mark.parametrize(("selector", "value"), [(1, 0), (1, 2), (18, 5180000), (15, 0)])
def test_receiver_settings_encoding(selector, value):
    assert rx_setting(selector, value) == struct.pack("<B3xII", 1, selector, value)
