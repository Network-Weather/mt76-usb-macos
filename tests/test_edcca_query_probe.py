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
    enable = p.summarize(event(5, bytes((1, 0, 0, 0))), 7, 5)
    assert enable["enable_hardware_verified"] is False
    assert enable["enable_provenance"] == "pinned_firmware_stub_synthesizes_one"


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


def test_exact_hardware_fields_and_fourth_not_in_reply():
    class Device:
        CHIP = p.m.CHIP_MT7925

        def rr(self, address):
            return {0x83088554: 0xAAC1BEBB, 0x83088608: 0x123456C4}[address]

    result = p.hardware_thresholds(Device())
    assert result["field_signed"] == [-69, -66, -63, -60]
    assert result["fourth_field_not_in_uni_reply"]


@pytest.mark.parametrize("word", [0xFFFFFFFF, -1, 0x100000000, True])
def test_hardware_read_failure_rejected(word):
    class Device:
        CHIP = p.m.CHIP_MT7925

        def rr(self, _):
            return word

    with pytest.raises(ValueError, match="invalid threshold"):
        p.hardware_thresholds(Device())


def test_hardware_map_refuses_wrong_chip_before_read():
    class Device:
        CHIP = p.m.CHIP_MT7921

        def rr(self, _):
            pytest.fail("wrong chip must not read")

    with pytest.raises(ValueError, match="MT7925 threshold map"):
        p.hardware_thresholds(Device())
