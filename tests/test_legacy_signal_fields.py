# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import legacy_signal_fields as p
from research import signal_field_crosscheck_probe as cross


def test_instantaneous_uses_only_two_signed_upper_bytes():
    assert p.instantaneous(0x91BC4359) == {"inst_ib_raw_s8": -111, "inst_wb_raw_s8": -68}
    assert p.instantaneous(0x91BC0000) == p.instantaneous(0x91BCFFFF)


def test_fagc_fractional_bits_are_discarded_before_signed_decode():
    a = (0x80 << 8) | 0x7F
    b = (0xFF << 5) | (0x81 << 14)
    expected = {
        "fagc_ib0_raw_s8": 127,
        "fagc_ib1_raw_s8": -128,
        "fagc_wb0_raw_s8": -1,
        "fagc_wb1_raw_s8": -127,
    }
    assert p.fagc_band0(a, b) == expected
    assert p.fagc_band0(a, b | (1 << 4) | (1 << 13) | 3) == expected


@pytest.mark.parametrize("word", [-1, True, None, 1 << 32])
def test_unsigned_word_validation(word):
    with pytest.raises(ValueError, match="unsigned32"):
        p.instantaneous(word)


def test_query_comparison_only_claims_stable_fields():
    before = {
        "fagc": p.fagc_band0(0x8081, 0),
        "bank0": p.instantaneous(0x91BC0000),
        "bank1": p.instantaneous(0xA0AA0000),
    }
    words = [0] * 66
    for index, value in p.expected_statistics(**before).items():
        words[index] = value & 0xFFFFFFFF
    after = {**before, "bank0": p.instantaneous(0x92BC0000)}
    rows = cross.compare(before, after, words)
    for row in rows:
        if row["word_index"] in (11, 34):
            assert not row["source_endpoints_equal"]
            assert "exact_match" not in row
        else:
            assert row["exact_match"]
    with pytest.raises(ValueError, match="exact66"):
        cross.compare(before, after, [])


def test_query_requires_matching_event_sequence_and_band():
    def event(sequence=7, band=0, kind=7):
        raw = bytearray(336)
        struct.pack_into("<I", raw, 0, (kind << 27) | 336)
        raw[28:30] = bytes((0x45, sequence))
        struct.pack_into("<III72I", raw, 36, 1, 72, band, *range(72))
        return bytes(raw)

    class Device:
        msg_seq = 7

        def __init__(self):
            self.frames = iter((event(kind=2), event(sequence=8), event(band=1), event()))

        def mcu_cmd_word(self, command, payload, wait):
            assert payload == cross.request(1, 0)
            assert not wait

        def rx_read(self, timeout):
            return next(self.frames)

    assert cross.query(Device(), 1) == list(range(66))


def test_query_bounds_nonmatching_records():
    class Device:
        msg_seq = 7
        reads = 0

        def mcu_cmd_word(self, *args, **kwargs):
            pass

        def rx_read(self, timeout):
            self.reads += 1
            return b"short"

    dev = Device()
    with pytest.raises(RuntimeError, match="matched band0"):
        cross.query(dev, 1)
    assert dev.reads <= 128
