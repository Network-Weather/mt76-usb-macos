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


def test_radiotap_with_rate_and_mcs():
    # CCK rate: 1.0 Mbps -> 2 in 500 kbps units
    phy_cck = {"mode": 0, "rate_mbps": 1.0}
    hdr_cck = capture.radiotap(2412, "2.4GHz", -60, False, phy=phy_cck)
    assert struct.unpack_from("<I", hdr_cck, 4)[0] & capture.RT_RATE
    assert hdr_cck[9] == 2  # Rate at offset 9

    # HT MCS 3, 20 MHz, SGI
    phy_ht = {"mode": 2, "mcs": 3, "bw_mhz": 20, "gi": 1}
    hdr_ht = capture.radiotap(5180, "5GHz", -50, False, phy=phy_ht)
    assert struct.unpack_from("<I", hdr_ht, 4)[0] & capture.RT_MCS
    # MCS fields: known, flags, index
    known, mcs_flags, mcs_idx = struct.unpack_from("<BBB", hdr_ht, 15)
    assert known == 0x07
    assert mcs_flags & 0x04  # SGI
    assert mcs_idx == 3


def test_radiotap_with_vht_and_he():
    # VHT 80 MHz, MCS 9, NSS 2, SGI
    phy_vht = {"mode": 4, "mcs": 9, "nss": 2, "bw_mhz": 80, "gi": 1, "stbc": False}
    hdr_vht = capture.radiotap(5180, "5GHz", -45, False, phy=phy_vht)
    assert struct.unpack_from("<I", hdr_vht, 4)[0] & capture.RT_VHT
    vht_known, _flags, bw, user0 = struct.unpack_from("<HBBB", hdr_vht, 16)
    assert vht_known == (0x0001 | 0x0004 | 0x0040)
    assert bw == 4  # 80 MHz
    assert (user0 >> 4) == 9  # MCS 9
    assert (user0 & 0x0F) == 2  # NSS 2

    # HE-MU on 52-tone RU (ru_tones=52, ru_offset=3, mcs=5)
    phy_he_mu = {
        "mode": 11,
        "mcs": 5,
        "nss": 1,
        "nsts": 1,
        "bw_mhz": 20,
        "gi": 0,
        "ru_tones": 52,
        "ru_offset": 3,
    }
    hdr_he_mu = capture.radiotap(5180, "5GHz", -40, False, phy=phy_he_mu)
    assert struct.unpack_from("<I", hdr_he_mu, 4)[0] & capture.RT_HE
    d1, d2, d3, _d4, d5, d6 = struct.unpack_from("<HHHHHH", hdr_he_mu, 16)
    assert (d1 & 0x0003) == 2  # Format: HE-MU
    assert (d2 & 0x4000) != 0  # RU offset known
    assert ((d2 >> 8) & 0x3F) == 3  # RU offset 3
    assert ((d3 >> 8) & 0x0F) == 5  # MCS 5
    assert (d5 & 0x0F) == 5  # 52-tone RU alloc
    assert (d6 & 0x0F) == 1  # NSTS 1

    # HE-ER-SU 40 MHz full-bandwidth (ru_tones=484, mcs=0)
    phy_he_er = {
        "mode": 9,
        "mcs": 0,
        "nss": 1,
        "nsts": 1,
        "bw_mhz": 40,
        "gi": 0,
        "ru_tones": 484,
    }
    hdr_he_er = capture.radiotap(5180, "5GHz", -40, False, phy=phy_he_er)
    assert struct.unpack_from("<I", hdr_he_er, 4)[0] & capture.RT_HE
    d1_er, _d2, _d3, _d4, d5_er, d6_er = struct.unpack_from("<HHHHHH", hdr_he_er, 16)
    assert (d1_er & 0x0003) == 1  # Format: HE-EXT-SU
    assert (d5_er & 0x0F) == 1  # 40 MHz BW alloc
    assert (d6_er & 0x0F) == 1  # NSTS 1
