# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""connac3 (MT7925) RX descriptor decoding against synthetic descriptors.

Layouts come from mt76_connac3_mac.h and mt7925_mac_fill_rx at c5a3bd91. Frames are
built here, never captured, so nothing identifies a real network.
"""

import struct

import pytest

import rxd
import rxd_connac3 as c3

BEACON = bytes.fromhex(
    "80000000"  # fc, duration
    "ffffffffffff"  # da
    "020000000001"  # sa
    "020000000001"  # bssid
    "1000"  # seq
    + "00" * 8  # timestamp
    + "6400"  # interval
    + "1104"  # capability
    + "0004"
    + "74657374"  # SSID "test"
    + "0301"
    + "06"  # DS parameter set, channel 6
)
FCS = b"\xde\xad\xbe\xef"


def rxd_words(
    *,
    groups=(),
    fcs_err=False,
    icv_err=False,
    pkt_type=rxd.PKT_TYPE_NORMAL,
    pkt_flag=0,
    chfreq=6,
    hdr_offset=0,
    amsdu=0,
    wlan_idx=5,
    band_idx=1,
    sec_mode=0,
    non_ampdu=True,
    frag=False,
    sw_frame=False,
    dma_len=None,
):
    w1 = wlan_idx & 0xFFF
    for g in groups:
        w1 |= {
            1: c3.MT_RXD1_NORMAL_GROUP_1,
            2: c3.MT_RXD1_NORMAL_GROUP_2,
            3: c3.MT_RXD1_NORMAL_GROUP_3,
            4: c3.MT_RXD1_NORMAL_GROUP_4,
            5: c3.MT_RXD1_NORMAL_GROUP_5,
        }[g]
    if icv_err:
        w1 |= c3.MT_RXD1_NORMAL_ICV_ERR
    w1 |= (band_idx & 0x3) << 27
    w2 = (hdr_offset & 0x7) << 13 | (sec_mode & 0x1F) << 16
    if non_ampdu:
        w2 |= c3.MT_RXD2_NORMAL_NON_AMPDU
    if frag:
        w2 |= c3.MT_RXD2_NORMAL_FRAG
    w3 = (chfreq & 0xFF) << 8
    if fcs_err:
        w3 |= c3.MT_RXD3_NORMAL_FCS_ERR
    w4 = amsdu & 0x3
    w0 = (pkt_type & 0x1F) << 27 | (pkt_flag & 0xF) << 16
    if sw_frame:
        w0 = c3.MT_RXD0_SW_PKT_TYPE_FRAME << 16  # type field 7 (RX_EVENT), flag 1, sw map
    return [w0, w1, w2, w3, w4, 0, 0, 0], dma_len


def build(frame=BEACON, groups=(), prxv=None, g4=None, timestamp=None, **kw):
    words, dma_len = rxd_words(groups=groups, **kw)
    body = bytearray()
    if 4 in groups:
        g = g4 or [0x0080, 0, 0x00100000, 0]  # fc=beacon, seq_ctrl 0x0010 in word 2 low? (see test)
        body += struct.pack("<4I", *g)
    if 1 in groups:
        body += b"\x11" * 16
    if 2 in groups:
        body += struct.pack("<I", timestamp or 0xDEADBEEF) + b"\x00" * 12
    if 3 in groups:
        body += struct.pack("<4I", *(prxv or [0, 0, 0, 0]))
        if 5 in groups:
            body += b"\x55" * 96
    padding = b"\x00\x00" * kw.get("hdr_offset", 0)
    frame_bytes = frame + FCS
    total = 32 + len(body) + len(padding) + len(frame_bytes)
    words[0] |= (dma_len if dma_len is not None else total) & 0xFFFF
    return struct.pack("<8I", *words) + bytes(body) + padding + frame_bytes + b"\x00" * 6


def prxv_words(
    *,
    rate_idx,
    nsts,
    mode,
    frame_mode,
    gi=0,
    stbc=0,
    dcm=False,
    ldpc=False,
    txbf=False,
    ru=0,
    rcpi=(0, 0, 0, 0),
):
    v0 = (rate_idx & 0x7F) | ((nsts & 0xF) << 7) | ((ru & 0x1FF) << 22)
    if ldpc:
        v0 |= c3.MT_PRXV_HT_AD_CODE
    if txbf:
        v0 |= c3.MT_PRXV_TXBF
    v2 = (frame_mode & 0x7) | ((gi & 0x3) << 3) | ((stbc & 0x3) << 9) | ((mode & 0xF) << 11)
    if dcm:
        v2 |= c3.MT_PRXV_DCM
    v3 = rcpi[0] | (rcpi[1] << 8) | (rcpi[2] << 16) | (rcpi[3] << 24)
    return [v0, 0, v2, v3]


def test_fixed_header_fields_and_frame_without_groups():
    d = c3.decode(build())
    assert d["pkt_type"] == rxd.PKT_TYPE_NORMAL
    assert d["hdr_gap"] == 32
    assert d["frame"] == BEACON + FCS  # record ends at dma_len, padding excluded
    assert (d["band"], d["channel"]) == ("2.4GHz", 6)
    assert d["wlan_idx"] == 5
    assert d["band_idx"] == 1
    assert d["fcs_err"] is False
    assert d["amsdu"] == 0
    assert d["non_ampdu"] is True
    p = rxd.parse_80211(d["frame"])
    assert p["kind"] == "Beacon"
    assert p["ssid"] == "test"


def test_fcs_error_is_rxd3_bit_24_and_icv_is_rxd1_bit_25():
    d = c3.decode(build(fcs_err=True))
    assert d["fcs_err"] is True
    assert d["icv_err"] is False
    d = c3.decode(build(icv_err=True))
    assert d["fcs_err"] is False
    assert d["icv_err"] is True
    # The connac2 decoder reads FCS from RXD1 bit 27, which on connac3 is the band index:
    # prove the layouts disagree so nobody swaps decoders by accident.
    assert rxd.decode(build(fcs_err=True, band_idx=0))["fcs_err"] is False
    assert rxd.decode(build(fcs_err=False, band_idx=1))["fcs_err"] is True


@pytest.mark.parametrize(
    ("groups", "gap"),
    [
        ((4,), 48),
        ((1,), 48),
        ((2,), 48),
        ((3,), 48),
        ((4, 1), 64),
        ((4, 1, 2), 80),
        ((4, 1, 2, 3), 96),
        ((4, 1, 2, 3, 5), 192),
        ((3, 5), 144),
        ((2, 3), 64),
    ],
)
def test_every_group_combination_lands_on_the_frame(groups, gap):
    d = c3.decode(build(groups=groups))
    assert d["hdr_gap"] == gap
    assert d["frame"] == BEACON + FCS
    assert rxd.parse_80211(d["frame"])["kind"] == "Beacon"


def test_group5_without_group3_is_flagged_not_skipped():
    d = c3.decode(build(groups=(5,)))
    assert d["g5_without_g3"] is True
    # The decoder mirrors the driver, which only steps over group 5 inside group 3, so the
    # gap stays at the fixed header; the flag tells a reader why the frame may be off.
    assert d["hdr_gap"] == 32


def test_header_offset_pads_in_two_byte_units():
    d = c3.decode(build(groups=(4,), hdr_offset=1))
    assert d["hdr_gap"] == 48 + 2
    assert d["frame"] == BEACON + FCS


def test_group4_exposes_frame_control_seq_and_qos():
    g4 = [0x0080 | (0xABCD << 16), 0, (0x1234 << 16) | 0x0567, 0]
    d = c3.decode(build(groups=(4,), g4=g4))
    assert d["fc_rxd"] == 0x0080
    assert d["seq_ctrl"] == 0x0567
    assert d["qos_ctl"] == 0x1234


def test_group2_timestamp():
    d = c3.decode(build(groups=(2,), timestamp=0x01020304))
    assert d["timestamp"] == 0x01020304


def test_prxv_rcpi_word3_gives_rssi_per_chain():
    # rcpi 110 -> -55 dBm, 90 -> -65 dBm, 0 -> -110 (invalid, filtered), 220 -> 0 (not < 0)
    prxv = prxv_words(
        rate_idx=0, nsts=1, mode=rxd.MT_PHY_TYPE_OFDM, frame_mode=0, rcpi=(110, 90, 0, 220)
    )
    d = c3.decode(build(groups=(3,), prxv=prxv))
    assert d["chain_signal"] == [-55, -65, -110, 0]
    assert d["rssi"] == -55


def test_he_su_160mhz_rate():
    # HE-SU, MCS 11, NSTS 2 (nss 2), 160 MHz, 0.8 us GI -> 2401.9 Mbps (802.11ax table)
    prxv = prxv_words(
        rate_idx=11, nsts=1, mode=rxd.MT_PHY_TYPE_HE_SU, frame_mode=3, gi=0, ldpc=True
    )
    d = c3.decode(build(groups=(3,), prxv=prxv))
    phy = d["phy"]
    assert phy["mode_name"] == "HE-SU"
    assert phy["bw_mhz"] == 160
    assert phy["nss"] == 2
    assert phy["mcs"] == 11
    assert phy["ldpc"] is True
    assert phy["rate_mbps"] == pytest.approx(2402.0, abs=0.1)


def test_eht_mcs13_160mhz_rate_and_320_frame_modes():
    # EHT-MU, MCS 13 (4096-QAM 5/6), 2 streams, 160 MHz, 0.8 us -> 2882.4 Mbps (802.11be)
    prxv = prxv_words(rate_idx=13, nsts=1, mode=rxd.MT_PHY_TYPE_EHT_MU, frame_mode=3)
    phy = c3.decode(build(groups=(3,), prxv=prxv))["phy"]
    assert phy["mode_name"] == "EHT-MU"
    assert phy["rate_mbps"] == pytest.approx(2882.4, abs=0.1)
    for fm in (4, 5):
        prxv = prxv_words(rate_idx=0, nsts=0, mode=rxd.MT_PHY_TYPE_EHT_SU, frame_mode=fm)
        phy = c3.decode(build(groups=(3,), prxv=prxv))["phy"]
        assert phy["bw_mhz"] == 320
        assert phy["rate_mbps"] is None  # no 320 MHz tone plan; not this chip's capability
    # MCS 12/13 are EHT-only: an HE frame claiming MCS 13 has no rate.
    assert rxd.phy_rate_mbps(rxd.MT_PHY_TYPE_HE_SU, 13, 1, 80, 0) is None


def test_vht_ht_and_legacy_rates_from_prxv_word2_fields():
    prxv = prxv_words(rate_idx=9, nsts=2, mode=rxd.MT_PHY_TYPE_VHT, frame_mode=2, gi=1, stbc=1)
    phy = c3.decode(build(groups=(3,), prxv=prxv))["phy"]
    assert (phy["mode_name"], phy["mcs"], phy["nss"], phy["bw_mhz"], phy["gi"]) == (
        "VHT",
        9,
        3,
        80,
        1,
    )
    assert phy["stbc"] is True
    assert phy["rate_mbps"] == pytest.approx(234 * 8 * (5 / 6) * 3 / 3.6, abs=0.1)
    prxv = prxv_words(rate_idx=15, nsts=1, mode=rxd.MT_PHY_TYPE_HT, frame_mode=1, gi=1)
    phy = c3.decode(build(groups=(3,), prxv=prxv))["phy"]
    assert phy["mode_name"] == "HT"
    assert phy["rate_mbps"] == pytest.approx(300.0, abs=0.1)  # MCS 15, 40 MHz, SGI
    prxv = prxv_words(rate_idx=11, nsts=0, mode=rxd.MT_PHY_TYPE_OFDM, frame_mode=0)
    assert c3.decode(build(groups=(3,), prxv=prxv))["phy"]["rate_mbps"] == 6.0


def test_he_er_su_106_tone_case_and_dcm():
    prxv = prxv_words(
        rate_idx=0x20 | 2, nsts=0, mode=rxd.MT_PHY_TYPE_HE_EXT_SU, frame_mode=1, dcm=True
    )
    phy = c3.decode(build(groups=(3,), prxv=prxv))["phy"]
    assert phy["ru_tones"] == 106
    assert phy["bw_mhz"] == 40  # descriptor width kept; the RU is in ru_tones
    assert phy["rate_mbps"] == pytest.approx(102 * 2 * (3 / 4) * 0.5 / 13.6, abs=0.1)
    assert phy["dcm"] is True
    assert phy["mcs"] == 2


def test_sw_pkt_type_frame_override_and_event_flag():
    d = c3.decode(build(sw_frame=True))
    assert d["pkt_type"] == rxd.PKT_TYPE_NORMAL
    assert d["frame"] == BEACON + FCS
    # RX_EVENT with flag 1 is exactly the 0x3801 software type, so mt7925_queue_rx_skb
    # turns it into NORMAL before the NORMAL_MCU branch can see it.
    d = c3.decode(build(pkt_type=rxd.PKT_TYPE_RX_EVENT, pkt_flag=1))
    assert d["pkt_type"] == rxd.PKT_TYPE_NORMAL
    assert "frame" in d
    d = c3.decode(build(pkt_type=rxd.PKT_TYPE_RX_EVENT, pkt_flag=0))
    assert d["pkt_type_name"] == "RX_EVENT"
    assert "frame" not in d
    d = c3.decode(build(pkt_type=rxd.PKT_TYPE_TXS))
    assert d["pkt_type_name"] == "TXS"
    assert "frame" not in d


def test_amsdu_maxlen_error_and_short_buffers():
    words, _ = rxd_words()
    words[2] |= c3.MT_RXD2_NORMAL_AMSDU_ERR
    d = c3.decode(struct.pack("<8I", *words) + b"\x00" * 8)
    assert d["error"] == "amsdu/maxlen"
    assert c3.decode(b"\x00" * 31) is None
    d = c3.decode(build(groups=(4,))[:40])  # group 4 announced but truncated
    assert "frame" not in d


def test_dma_len_bounds_the_frame_not_the_transfer():
    raw = build(dma_len=32 + 20)
    d = c3.decode(raw)
    assert d["frame"] == (BEACON + FCS)[:20]
    raw = build(dma_len=0xFFFF)
    d = c3.decode(raw)
    assert d["frame"] == BEACON + FCS + b"\x00" * 6  # clamped to the transfer


def test_decoder_selection_by_device_class():
    import mt7921u as m
    import mt7925u as m25

    assert m.decoder_for(m.Mt7921uDevice()) is rxd.decode
    assert m.decoder_for(m25.Mt7925uDevice()) is c3.decode
