# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import spatial_reuse_query_probe as p


def event(tag, data):
    header = bytearray(44)
    struct.pack_into("<I", header, 0, p.m.PKT_TYPE_RX_EVENT << 27 | 72)
    header[36] = 0x25
    return bytes(header) + struct.pack("<4xHH", tag, 24) + data + b"private tail"


def test_request_event_tag_asymmetry_and_typed_fields():
    assert p.request(0xCB) == bytes.fromhex("00000000cb00080000000000")
    result = p.summarize(event(0xC9, struct.pack("<6H2I", 1, 2, 3, 4, 5, 6, 70000, 80000)), 7, 0xCB)
    assert result["indicators_raw"]["inter_bss_ppdu"] == 4
    assert result["indicators_raw"]["sr_ampdu_mpdu_acked"] == 80000
    assert result["sequence"] == 0
    assert "private" not in repr(result)
    flags = p.summarize(event(0xC0, bytes([1, 0] * 10)), 7, 0xC0)
    assert len(flags["capabilities_raw"]) == 20


@pytest.mark.parametrize("tag", [0xC9, 1, 0xCA, True, 192.0, -1])
def test_never_send_reset_or_enable_tags(tag):
    with pytest.raises(ValueError, match="read-only"):
        p.request(tag)


def test_wrong_shape_sequence_and_packet_class_not_interpreted():
    raw = bytearray(event(0xC0, bytes(20)))
    assert p.summarize(raw, 7, 0xCB)["unrecognized_shape"]
    raw[37] = 7
    assert p.summarize(raw, 7, 0xC0) is None
    struct.pack_into("<I", raw, 0, 2 << 27 | 72)
    raw[37] = 0
    assert p.summarize(raw, 7, 0xC0) is None


def test_non_boolean_capability_is_not_silently_named():
    with pytest.raises(ValueError, match="capability"):
        p.summarize(event(0xC0, bytes([2] * 20)), 7, 0xC0)


@pytest.mark.parametrize(("chip", "option"), [(p.m.CHIP_MT7921, 3), (p.m.CHIP_MT7925, 7)])
def test_wrong_chip_and_set_framing_rejected_before_io(chip, option):
    class Device:
        CHIP = chip

        def uni_option(self, *_):
            return option

    with pytest.raises(ValueError, match="QUERY_ACK3"):
        p.query(Device(), 0xC0)
