# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import txpower_info_probe as p


def event(chip, body):
    header, eid_offset, eid = (44, 36, 0x2A) if chip == p.m.CHIP_MT7925 else (36, 28, 0xD0)
    raw = bytearray(header)
    struct.pack_into("<I", raw, 0, (header + len(body)) | (7 << 27))
    raw[eid_offset : eid_offset + 2] = bytes((eid, 3))
    return bytes(raw) + body + b"unparsed USB tail"


def new_body():
    return (
        struct.pack("<4xHH4B", 5, 841, 5, 0, 0, 1)
        + bytes((36, 0)) * 417
        + struct.pack("<bbB", 63, -128, 6)
    )


def old_body():
    return struct.pack("<BBHB3x", 0, 0, 494, 6) + b"".join(
        bytes((6,)) + bytes((i,)) * 161 for i in (127, 44, 42)
    )


def test_exact_read_only_requests_and_counts():
    assert p.request(p.m.CHIP_MT7921) == bytes(8)
    assert p.request(p.m.CHIP_MT7925) == bytes.fromhex("000000000700080000020000")
    assert sum(n for _, n in p.LEGACY_GROUPS) == 161
    assert sum(n for _, n in p.EHT_GROUPS) == 256
    assert len(p.PLAN) == 6
    assert len(p.WIDTH_CACHE_PLAN) == 7
    assert p.WIDTH_CACHE_PLAN[2] == (36, 38, 40)
    assert p.WIDTH_CACHE_PLAN[3:5] == ((6, 6, 20), (6, 8, 40))


def test_new_report_signed_values_and_usb_tail_excluded():
    body = bytearray(new_body())
    body[12:14] = bytes((250, 127))
    result = p.summarize(event(p.m.CHIP_MT7925, body), p.m.CHIP_MT7925, 3)
    assert result["body_bytes"] == 849
    assert result["selected_band_power_raw"]["cck"] == [-6, 36, 36, 36]
    assert result["other_band_distinct_raw"] == [0, 127]
    assert len(result["selected_band_power_raw"]["eht996x3_484"]) == 16
    assert result["min_bound_raw"] == -128
    assert result["tail_byte_raw"] == 6


def test_old_report_separates_three_source_planes():
    result = p.summarize(event(p.m.CHIP_MT7921, old_body()), p.m.CHIP_MT7921, 3)
    assert result["reported_channel"] == 6
    for name, value in (("user", 127), ("eeprom", 44), ("mac", 42)):
        assert result["planes"][name]["power_raw_u8"]["ht40"] == [value] * 9
        assert result["planes"][name]["reported_channel"] == 6


@pytest.mark.parametrize("chip", [p.m.CHIP_MT7921, p.m.CHIP_MT7925])
def test_wrong_sequence_and_short_event_refused(chip):
    body = old_body() if chip == p.m.CHIP_MT7921 else new_body()
    with pytest.raises(ValueError, match="matching power-report"):
        p.summarize(event(chip, body), chip, 4)
    with pytest.raises(ValueError, match="short power-report"):
        p.summarize(b"short", chip, 3)


@pytest.mark.parametrize("offset", [0, 4, 6, 8, 9, 11])
def test_new_wrong_shape_refused(offset):
    body = bytearray(new_body())
    body[offset] ^= 1
    with pytest.raises(ValueError, match="MT7925 power-report shape"):
        p.summarize(event(p.m.CHIP_MT7925, body), p.m.CHIP_MT7925, 3)


@pytest.mark.parametrize("offset", [0, 1, 2, 5])
def test_old_wrong_shape_refused(offset):
    body = bytearray(old_body())
    body[offset] ^= 1
    with pytest.raises(ValueError, match="MT7961 power-report shape"):
        p.summarize(event(p.m.CHIP_MT7921, body), p.m.CHIP_MT7921, 3)


def test_table_length_and_other_chip_refused():
    with pytest.raises(ValueError, match="table length"):
        p.groups(bytes(160), p.LEGACY_GROUPS)
    with pytest.raises(ValueError, match="power-report layouts"):
        p.request("unknown")


@pytest.mark.parametrize("chip", [p.m.CHIP_MT7921, p.m.CHIP_MT7925])
@pytest.mark.parametrize("kind", ["packet_type", "eid", "declared_length"])
def test_bad_event_envelope_refused(chip, kind):
    raw = bytearray(event(chip, old_body() if chip == p.m.CHIP_MT7921 else new_body()))
    if kind == "packet_type":
        word = struct.unpack_from("<I", raw)[0]
        struct.pack_into("<I", raw, 0, (word & ~(31 << 27)) | (2 << 27))
    elif kind == "eid":
        raw[36 if chip == p.m.CHIP_MT7925 else 28] ^= 1
    else:
        struct.pack_into("<H", raw, 0, len(raw) + 1)
    with pytest.raises(ValueError, match="matching power-report"):
        p.summarize(raw, chip, 3)
