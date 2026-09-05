# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import rtt_capability_probe as p
from tests.test_rdd_stop_probe import event


def test_only_capability_queries():
    assert p.request(p.m.CHIP_MT7921) == b""
    assert p.request(p.m.CHIP_MT7925) == bytes.fromhex("0000000000000400")
    with pytest.raises(ValueError, match="pinned"):
        p.request("unknown")


@pytest.mark.parametrize("chip", [p.m.CHIP_MT7921, p.m.CHIP_MT7925])
@pytest.mark.parametrize("seq", [0, 7])
def test_exact_capability_shape_and_no_usb_tail(chip, seq):
    body = bytes(range(8))
    eid = 0x2D
    if chip == p.m.CHIP_MT7925:
        body = struct.pack("<4xHH", 0, 12) + body
        eid = 0x5D
    result = p.summarize(event(chip, eid, body, seq=seq), chip, 7)
    assert result["capability_bytes_raw"] == list(range(8))
    assert "private" not in repr(result)
    assert p.summarize(event(chip, eid, body, seq=8), chip, 7) is None
    wrong = p.summarize(event(chip, eid, body + b"private"), chip, 7)
    assert wrong["unrecognized_capability_shape"]
    assert "capability_bytes_raw" not in wrong


def test_malformed_length_type_and_wrong_tag():
    chip = p.m.CHIP_MT7925
    raw = bytearray(event(chip, 0x5D, bytes(16)))
    assert p.summarize(raw, chip, 7)["unrecognized_capability_shape"]
    struct.pack_into("<H", raw, 0, 65535)
    assert p.summarize(raw, chip, 7) is None
    struct.pack_into("<I", raw, 0, len(raw))
    assert p.summarize(raw, chip, 7) is None
    assert p.summarize(bytes(20), chip, 7) is None


@pytest.mark.parametrize(("chip", "cid"), [(p.m.CHIP_MT7921, 0x44), (p.m.CHIP_MT7925, 0x5D)])
def test_status_and_not_found_metadata(chip, cid):
    result = p.summarize(event(chip, 1, struct.pack("<II", cid, 0xC00000BB)), chip, 7)
    assert result["command_result_status"] == 0xC00000BB
    assert p.summarize(event(chip, 0xFD, b"private"), chip, 7)["command_not_found_event"]


def test_wrong_uni_option_before_send():
    class Device:
        CHIP = p.m.CHIP_MT7925

        def uni_option(self, cid, query):
            assert cid == 0x5D
            assert query is True
            return 7

    with pytest.raises(ValueError, match="QUERY_ACK3"):
        p.query(Device())


@pytest.mark.parametrize("value", [None, b"\x01", b"\x01\0\0\0"])
def test_location_only_not_device_identity(value):
    caps = {7: b"private MAC"}
    if value is not None:
        caps[12] = value
    result = p.location_capability(caps)
    assert "private" not in repr(result)
    assert ("toa_engine_advertised_raw" in result) == (value is not None and len(value) == 4)
