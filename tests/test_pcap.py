# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Offline tests for the example's radiotap/pcap serialization."""

import struct

import pytest

from examples import sniff_to_pcap as capture


def test_channel_to_frequency_conversion():
    assert capture.freq_for("2.4GHz", 1) == 2412
    assert capture.freq_for("2.4GHz", 14) == 2484
    assert capture.freq_for("5GHz", 149) == 5745
    assert capture.freq_for("6GHz", 53) == 6215


def test_unknown_band_is_rejected():
    with pytest.raises(ValueError, match="unknown band"):
        capture.freq_for("60GHz", 1)


def test_radiotap_layout_and_bad_fcs_flag():
    header = capture.radiotap(6215, "6GHz", -42, True)

    version, pad, length, present = struct.unpack_from("<BBHI", header)
    flags = header[8]
    frequency, channel_flags = struct.unpack_from("<HH", header, 10)
    signal = struct.unpack_from("<b", header, 14)[0]

    assert (version, pad, length) == (0, 0, 15)
    assert present == capture.RT_FLAGS | capture.RT_CHANNEL | capture.RT_DBM_ANTSIGNAL
    assert flags == capture.RT_FLAG_BADFCS
    assert frequency == 6215
    assert channel_flags == capture.CH_FLAG_5GHZ | capture.CH_FLAG_OFDM
    assert signal == -42


def test_radiotap_marks_unknown_signal():
    assert struct.unpack_from("<b", capture.radiotap(2412, "2.4GHz", None, False), 14)[0] == -128


def test_pcap_global_header_is_radiotap_little_endian():
    header = capture.pcap_header(4096)

    assert len(header) == 24
    assert struct.unpack("<IHHiIII", header) == (
        0xA1B2C3D4,
        2,
        4,
        0,
        0,
        4096,
        capture.LINKTYPE_IEEE802_11_RADIOTAP,
    )
