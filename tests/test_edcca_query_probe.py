# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import edcca_query_probe as p


def event(tag, data, tail=bytes(20)):
    body = struct.pack("<4xHH", tag - 5, 8) + data
    raw = bytearray(44)
    struct.pack_into("<I", raw, 0, (p.m.PKT_TYPE_RX_EVENT << 27) | (44 + len(body)))
    raw[36:38] = bytes((0x21, 7))
    return bytes(raw) + body + tail


def test_requests_and_renumbered_reply_tags():
    assert p.request(5) == bytes.fromhex("000000000500080000000000")
    assert p.summarize(event(5, bytes((1, 0, 0, 0))), 7, 5)["enable_raw"] == 1
    result = p.summarize(event(6, bytes.fromhex("bbbec100")), 7, 6)
    assert result["threshold_signed"] == [-69, -66, -63]
    assert result["event_tag"] == 1


@pytest.mark.parametrize("tag", [0, 1, 7, -1, True, 5.0])
def test_no_other_queries(tag):
    with pytest.raises(ValueError, match="only EDCCA"):
        p.request(tag)


def test_usb_padding_is_outside_event_and_not_exported():
    result = p.summarize(event(6, bytes(4), tail=b"private" + bytes(13)), 7, 6)
    assert result["body_bytes"] == 12
    assert result["recognized_config"]
    assert "private" not in repr(result)


def test_wrong_sequence_and_normal_frame_refused():
    raw = event(5, bytes(4))
    with pytest.raises(ValueError, match="matching"):
        p.summarize(raw, 8, 5)
    with pytest.raises(ValueError, match="short"):
        p.summarize(bytes(20), 7, 5)
    raw = bytearray(raw)
    struct.pack_into("<I", raw, 0, (2 << 27) | len(raw))
    with pytest.raises(ValueError, match="matching"):
        p.summarize(raw, 7, 5)


@pytest.mark.parametrize(("chip", "option"), [(p.m.CHIP_MT7921, 7), (p.m.CHIP_MT7925, 7)])
def test_set_framing_rejected_before_command(chip, option):
    class Device:
        CHIP = chip

        def uni_option(self, *_):
            return option

        def mcu_uni(self, *_args, **_kwargs):
            pytest.fail("must not send SET")

    with pytest.raises(ValueError, match="QUERY_ACK"):
        p.query(Device(), 5)
