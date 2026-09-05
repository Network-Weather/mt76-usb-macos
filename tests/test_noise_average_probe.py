# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from mt7925u import Mt7925uDevice
from research import noise_average_probe as p


def event(chip, values=(-95, -96), debug_words=False):
    if chip == p.m.CHIP_MT7925:
        body = struct.pack("<4xHHIhh", 0, 12, p.GET_NOISE, *values)
        header, eid_at, eid = 44, 36, 7
    else:
        body = struct.pack("<Ihh", p.GET_NOISE, *values)
        if debug_words:
            body += b"x" * 256
        header, eid_at, eid = 36, 28, 0x17
    raw = bytearray(header)
    struct.pack_into("<I", raw, 0, (p.m.PKT_TYPE_RX_EVENT << 27) | (header + len(body)))
    raw[eid_at : eid_at + 2] = bytes((eid, 9))
    return bytes(raw) + body + b"private USB padding"


def test_fixed_query_layouts():
    assert p.request(p.m.CHIP_MT7925).hex() == "0000000000000c00010026b100000000"
    old = p.request(p.m.CHIP_MT7921)
    assert len(old) == 264
    assert old[:4] == bytes.fromhex("010026b1")
    assert old[4:] == bytes(260)
    with pytest.raises(ValueError, match="pinned"):
        p.request("unknown")


def test_actual_library_query_option():
    assert Mt7925uDevice.uni_option(None, 0x0E, True) == 2


def test_diagnostic_does_not_export_unknown_debug_values():
    raw = bytearray(event(p.m.CHIP_MT7921, debug_words=True))
    raw[36:40] = bytes(4)
    exc = p.UnexpectedNoiseEvent(raw, p.m.CHIP_MT7921, "noise-average query ID mismatch")
    assert exc.diagnostic["returned_query_id"] == "0x0"
    assert "xxxx" not in repr(exc.diagnostic)
    assert "private" not in repr(exc.diagnostic)


@pytest.mark.parametrize("chip", [p.m.CHIP_MT7921, p.m.CHIP_MT7925])
def test_signed_values_only_no_debug_or_padding(chip):
    row = p.summarize(event(chip, debug_words=True), chip, 9)
    assert row["average_power_raw_i16"] == [-95, -96]
    assert row["calibrated"] is False
    assert "private" not in repr(row)
    assert "xxxx" not in repr(row)


@pytest.mark.parametrize("chip", [p.m.CHIP_MT7921, p.m.CHIP_MT7925])
def test_truncated_wrong_sequence_and_wrong_id(chip):
    for raw, sequence in ((b"", 9), (event(chip), 8), (event(chip)[:40], 9)):
        with pytest.raises(ValueError, match="noise-average"):
            p.summarize(raw, chip, sequence)
    raw = bytearray(event(chip))
    raw[52 if chip == p.m.CHIP_MT7925 else 36] ^= 1
    with pytest.raises(ValueError, match="query ID mismatch"):
        p.summarize(raw, chip, 9)


@pytest.mark.parametrize("offset", [44, 48, 50])
def test_bad_uni_shape(offset):
    raw = bytearray(event(p.m.CHIP_MT7925))
    raw[offset] ^= 1
    with pytest.raises(ValueError, match="UNI noise-average body"):
        p.summarize(raw, p.m.CHIP_MT7925, 9)


def test_query_only_envelopes():
    class Device:
        msg_seq = 9

        def uni_option(self, cid, query):
            assert cid == 0x0E
            assert query is True
            return 2

        def mcu_uni(self, cid, payload, **kwargs):
            assert cid == 0x0E
            assert payload == p.request(self.CHIP)
            assert kwargs["query"] is True
            return event(self.CHIP)

        def mcu_cmd_word(self, cid, payload, **kwargs):
            assert cid == p.m.MCU_CE_CMD(0xC4) | p.m.MCU_CMD_FIELD_QUERY
            assert payload == p.request(self.CHIP)
            return event(self.CHIP)

    dev = Device()
    for dev.CHIP in (p.m.CHIP_MT7921, p.m.CHIP_MT7925):
        assert p.query(dev)["average_power_raw_i16"] == [-95, -96]
