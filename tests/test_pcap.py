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


def test_radiotap_eht_frames_carry_usig_and_eht_tlvs():
    import rxd

    phy = {
        "mode": rxd.MT_PHY_TYPE_EHT_MU,
        "mcs": 13,
        "nss": 2,
        "bw_mhz": 160,
        "gi": 1,
        "ldpc": True,
    }
    header = capture.radiotap(6215, "6GHz", -50, False, phy)
    _version, _pad, length, present = struct.unpack_from("<BBHI", header)
    assert (
        present == capture.RT_FLAGS | capture.RT_CHANNEL | capture.RT_DBM_ANTSIGNAL | capture.RT_TLV
    )
    assert present >> 29 == 0  # nothing above the TLV bit (the list consumes the rest)
    # Flags(1) Rate? no; align; Channel(4) at 10; dBm at 14; pad to 16; then the TLV list.
    assert header[15] == 0
    tlv = 16
    assert tlv % 4 == 0
    t_type, t_len = struct.unpack_from("<HH", header, tlv)
    assert (t_type, t_len) == (capture.RT_TLV_U_SIG, 12)
    common, value, mask = struct.unpack_from("<III", header, tlv + 4)
    assert common == capture.USIG_BW_KNOWN | (3 << capture.USIG_BW_SHIFT)  # 160 MHz
    assert (value, mask) == (0, 0)
    tlv += 16
    t_type, t_len = struct.unpack_from("<HH", header, tlv)
    assert (t_type, t_len) == (capture.RT_TLV_EHT, 44)
    words = struct.unpack_from("<11I", header, tlv + 4)
    known, data, user = words[0], words[1:10], words[10]
    # EHT-MU: the user's RU may be smaller than the PPDU, so RU/MRU size is not claimed.
    assert known == capture.EHT_KNOWN_GI
    assert (data[0] >> 7) & 0x3 == 1  # GI 1.6 us
    assert data[1] == 0  # RU/MRU size left unknown for MU
    assert user & 0xFF == 0x02 | 0x04 | 0x10 | 0x80
    assert (user >> 20) & 0xF == 13
    assert (user >> 24) & 0xF == 1  # NSS 2 encodes as 1
    assert user & capture.EHT_USER_CODING_LDPC
    assert length == tlv + 48 == len(header)


def test_radiotap_eht_20mhz_single_stream():
    import rxd

    phy = {"mode": rxd.MT_PHY_TYPE_EHT_SU, "mcs": 0, "nss": 1, "bw_mhz": 20, "gi": 0, "ldpc": False}
    header = capture.radiotap(6215, "6GHz", -50, False, phy)
    common = struct.unpack_from("<I", header, 20)[0]
    assert common == capture.USIG_BW_KNOWN  # BW code 0
    words = struct.unpack_from("<11I", header, 36)
    assert words[0] == capture.EHT_KNOWN_GI | capture.EHT_KNOWN_RU_MRU_SIZE  # SU: full-width RU
    assert words[2] & 0x1F == 3  # data[1]: 242-tone RU
    assert (words[10] >> 20) & 0xF == 0
    assert (words[10] >> 24) & 0xF == 0
    assert not words[10] & capture.EHT_USER_CODING_LDPC


def test_eht_pcap_dissects_in_tshark(tmp_path):
    """tshark, when installed, must read the TLVs back as an 802.11be frame with the rate."""
    import shutil
    import subprocess

    import rxd

    tshark = shutil.which("tshark")
    if not tshark:
        pytest.skip("tshark not installed")
    phy = {"mode": rxd.MT_PHY_TYPE_EHT_MU, "mcs": 11, "nss": 2, "bw_mhz": 80, "gi": 1, "ldpc": True}
    frame = bytes.fromhex("88410000") + bytes(18) + bytes(8)  # QoS data header shape
    header = capture.radiotap(5210, "5GHz", -50, False, phy)
    pcap = tmp_path / "eht.pcap"
    record = struct.pack("<IIII", 1, 0, len(header) + len(frame), len(header) + len(frame))
    pcap.write_bytes(capture.pcap_header() + record + header + frame)
    out = subprocess.run(  # noqa: S603 - fixed argv, local tshark, no shell
        [
            tshark,
            "-r",
            str(pcap),
            "-T",
            "fields",
            "-e",
            "wlan_radio.phy",
            "-e",
            "wlan_radio.11be.mcs",
            "-e",
            "wlan_radio.11be.nsts",
            "-e",
            "wlan_radio.data_rate",
            "-e",
            "radiotap.u_sig.common.bw",
            "-e",
            "_ws.malformed",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    fields = out.stdout.strip().split("\t")
    assert fields[0] == "12", out.stdout  # PHDR_802_11_PHY_11BE
    assert fields[1] == "11"
    assert fields[2] == "2"
    assert fields[3].startswith("1134.")  # MCS 11, 2 streams, 80 MHz (from U-SIG BW), 1.6 us GI
    assert int(fields[4], 0) == 2  # U-SIG BW code for 80 MHz
    assert len(fields) < 6 or fields[5] == ""


# Byte widths and alignments of each radiotap field this writer emits, from the radiotap
# specification (https://www.radiotap.org/fields). it_len must account for every field the
# present bitmap claims; a short header makes Wireshark reject the packet as malformed,
# and no assertion on the field contents alone can catch that.
RADIOTAP_FIELD_SIZES = {
    "RT_FLAGS": (1, 1),
    "RT_RATE": (1, 1),
    "RT_CHANNEL": (4, 2),
    "RT_DBM_ANTSIGNAL": (1, 1),
    "RT_MCS": (3, 1),
    "RT_VHT": (12, 2),
    "RT_HE": (12, 2),
}


def expected_radiotap_length(present: int) -> int:
    """The length a radiotap header with these present bits must have."""
    offset = 8  # version, pad, it_len, it_present
    for name, (size, align) in RADIOTAP_FIELD_SIZES.items():
        if not present & getattr(capture, name):
            continue
        offset += -offset % align
        offset += size
    return offset


@pytest.mark.parametrize(
    ("label", "phy"),
    [
        ("no phy", None),
        ("cck", {"mode": 0, "rate_mbps": 1.0}),
        ("ofdm", {"mode": 1, "rate_mbps": 54.0}),
        ("ht", {"mode": 2, "mcs": 3, "bw_mhz": 20, "gi": 1}),
        ("vht 20", {"mode": 4, "mcs": 9, "nss": 2, "bw_mhz": 20, "gi": 0}),
        ("vht 80", {"mode": 4, "mcs": 9, "nss": 2, "bw_mhz": 80, "gi": 1, "stbc": False}),
        ("vht 160", {"mode": 4, "mcs": 7, "nss": 1, "bw_mhz": 160, "gi": 0}),
        ("he su", {"mode": 8, "mcs": 5, "nss": 2, "nsts": 2, "bw_mhz": 80, "gi": 0}),
        ("he mu", {"mode": 11, "mcs": 5, "nss": 1, "nsts": 1, "bw_mhz": 20, "ru_tones": 52}),
    ],
)
def test_radiotap_length_accounts_for_every_field_the_present_bitmap_claims(label, phy):
    header = capture.radiotap(5180, "5GHz", -45, False, phy=phy)
    it_len = struct.unpack_from("<H", header, 2)[0]
    present = struct.unpack_from("<I", header, 4)[0]

    assert it_len == len(header), label
    assert it_len == expected_radiotap_length(present), label


def test_the_vht_field_is_twelve_bytes_and_carries_coding():
    # known(2) flags(1) bandwidth(1) mcs_nss[4] coding(1) group_id(1) partial_aid(2).
    phy = {"mode": 4, "mcs": 9, "nss": 2, "bw_mhz": 80, "gi": 1, "ldpc": True}
    header = capture.radiotap(5180, "5GHz", -45, False, phy=phy)

    # Flags(1) at 8, pad(1), Channel(4) at 10, signal(1) at 14, pad(1), VHT at 16.
    vht = header[16:]
    assert len(vht) == 12
    assert vht[8] & 0x01  # user 0 coding, LDPC
    assert struct.unpack_from("<H", vht, 10)[0] == 0  # partial_aid present and zero
