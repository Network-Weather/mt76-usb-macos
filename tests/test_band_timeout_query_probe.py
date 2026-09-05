# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import band_timeout_query_probe as p


def event(selector=1, value=231):
    raw = bytearray(44)
    struct.pack_into("<I", raw, 0, p.m.PKT_TYPE_RX_EVENT << 27 | 60)
    raw[36:38] = bytes((0x21, 7))
    return bytes(raw) + struct.pack("<4xHHB3xI", 7, 12, selector, value) + b"private USB tail"


def test_exact_request_and_bounded_reply():
    assert p.request(2) == bytes.fromhex("0000000007000c000200000000000000")
    result = p.summarize(event(), 7, 1)
    assert result["value_u16"] == 231
    assert result["body_bytes"] == 16
    assert "private" not in repr(result)


@pytest.mark.parametrize("selector", [-1, 3, True, 1.0, None])
def test_no_arbitrary_selectors(selector):
    with pytest.raises(ValueError, match="three traced"):
        p.request(selector)


def test_sequence_selector_length_and_value_guards():
    with pytest.raises(ValueError, match="matching"):
        p.summarize(event(), 8, 1)
    with pytest.raises(ValueError, match="unexpected"):
        p.summarize(event(), 7, 2)
    with pytest.raises(ValueError, match="sixteen-bit"):
        p.summarize(event(value=65536), 7, 1)
    with pytest.raises(ValueError, match="short"):
        p.summarize(bytes(12), 7, 1)


@pytest.mark.parametrize(("chip", "option"), [(p.m.CHIP_MT7921, 3), (p.m.CHIP_MT7925, 7)])
def test_wrong_chip_or_set_refused_before_io(chip, option):
    class Device:
        CHIP = chip

        def uni_option(self, *_):
            return option

    with pytest.raises(ValueError, match="QUERY_ACK"):
        p.query(Device(), 0)


def test_query_reads_only_exact_selected_register_and_queries():
    class Device:
        CHIP = p.m.CHIP_MT7925
        msg_seq = 7

        def uni_option(self, *_):
            return 3

        def rr(self, address):
            assert address == 0x820E40CC
            return 0xAABB00E7

        def mcu_uni(self, cid, payload, **kwargs):
            assert cid == 8
            assert payload == p.request(1)
            assert kwargs == {"query": True, "timeout": 1000}
            return event()

    result = p.query(Device(), 1)
    assert result["query_matches_register"]
    assert result["register_stable"]
