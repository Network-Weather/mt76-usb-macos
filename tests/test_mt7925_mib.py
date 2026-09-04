# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Offline tests for the MT7925 UNI MIB characterization helpers."""

import argparse
import struct

import pytest

from research import mt7925_mib_characterize as mib
from research import mt7925_mib_perturb as perturb


def _entry(offset: int, value: int, length: int = mib.UNI_MIB_ENTRY_LEN) -> bytes:
    return struct.pack("<HHIQ", mib.UNI_CMD_MIB_DATA, length, offset, value)


def test_uni_mib_request_batches_offsets_behind_one_band_header():
    request = mib.build_request(1, (2, 19, 20))

    assert request[:4] == b"\x01\x00\x00\x00"
    assert len(request) == 4 + 3 * mib.UNI_MIB_ENTRY_LEN
    assert struct.unpack_from("<HHI", request, 4) == (mib.UNI_CMD_MIB_DATA, 8, 2)
    assert struct.unpack_from("<HHI", request, 12) == (mib.UNI_CMD_MIB_DATA, 8, 19)
    assert struct.unpack_from("<HHI", request, 20) == (mib.UNI_CMD_MIB_DATA, 8, 20)


def test_uni_mib_parser_finds_echoed_64_bit_values_in_a_reply():
    body = bytes(12) + _entry(2, 0x1_0000_0002) + _entry(19, 987_654)

    assert mib.parse_counter(body, 2) == 0x1_0000_0002
    assert mib.parse_counter(body, 19) == 987_654
    assert mib.parse_counter(body, 20) is None


def test_uni_mib_parser_rejects_an_entry_with_the_wrong_length():
    assert mib.parse_counter(_entry(19, 1234, length=7), 19) is None


def test_sample_reads_every_offset_in_one_mcu_round_trip():
    class FakeDevice:
        def __init__(self):
            self.calls = []

        def mcu_uni(self, command, payload, query=False):
            self.calls.append((command, payload, query))
            return _entry(2, 123) + _entry(19, 456)

        def reply_body(self, reply):
            return reply

    dev = FakeDevice()
    values, sampled_at = mib.sample(dev, (2, 19), 0)

    assert values == {2: 123, 19: 456}
    assert sampled_at > 0
    assert len(dev.calls) == 1
    assert dev.calls[0][0] == mib.MCU_UNI_CMD_GET_MIB_INFO
    assert dev.calls[0][2] is True


def test_characterization_target_accepts_an_explicit_wide_channel():
    assert mib.parse_target("5GHz:36:42:80") == ("5GHz", 36, 42, 80)


@pytest.mark.parametrize("target", ["5GHz:36:42:33", "9GHz:1", "5GHz:not-a-channel"])
def test_characterization_target_rejects_invalid_input(target):
    with pytest.raises(argparse.ArgumentTypeError):
        mib.parse_target(target)


def test_injected_airtime_includes_the_hardware_appended_fcs():
    assert perturb.expected_airtime_us(frame_len=32, count=60) == 28_800


def test_legacy_reference_delta_handles_a_32_bit_wrap():
    before = {"p_cca_time_us": (1 << 32) - 100}
    after = {"p_cca_time_us": 50}

    result = perturb.legacy_result(before, after, 1.0, 2.0)

    assert result["values"]["p_cca_time_us"]["delta"] == 150
    assert result["values"]["p_cca_time_us"]["fraction_if_us"] == 0.00015
