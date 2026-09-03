# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
# Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear).
# See NOTICE.md and RELATED_WORK.md for source lineage and peer implementations.
"""Decode connac3 (MT7925) RX descriptors into the same dict rxd.decode produces.

Transcribed from mt7925_mac_fill_rx and mt7925_mac_fill_rx_rate (mt7925/mac.c) and the
MT_RXD* / MT_PRXV_* fields in mt76_connac3_mac.h at c5a3bd91. Everything after the
descriptor (802.11 parsing, PHY rate arithmetic, airtime, aggregation) is shared with
rxd.py; only the descriptor layout differs from connac2:

- 8 fixed words (32 bytes) instead of 6; the group presence bits sit at RXD1 bits 16..20.
- FCS error is RXD3 bit 24, not RXD1 bit 27.
- Every optional group is 4 words (16 bytes); group 5 (C-RXV) is 24 words and is only
  stepped over when group 3 is also present, exactly as the driver does.
- The P-RXV rate fields are spread over its words 0 and 2, and the four RCPI bytes are its
  word 3.

The result dict uses the same keys as rxd.decode so parse_80211, the pcap writer, and
the scripts do not care which chip received the frame.
"""

from __future__ import annotations

import struct

import rxd

# mt76_connac3_mac.h
MT_RXD0_LENGTH = (0, 0xFFFF)
MT_RXD0_PKT_FLAG = (16, 0xF)
MT_RXD0_PKT_TYPE = (27, 0x1F)
MT_RXD0_SW_PKT_TYPE = (16, 0xFFFF)  # MT_RXD0_SW_PKT_TYPE_MASK GENMASK(31, 16)
MT_RXD0_SW_PKT_TYPE_MAP = 0x380F
MT_RXD0_SW_PKT_TYPE_FRAME = 0x3801

MT_RXD1_NORMAL_WLAN_IDX = (0, 0xFFF)
MT_RXD1_NORMAL_GROUP_1 = 1 << 16
MT_RXD1_NORMAL_GROUP_2 = 1 << 17
MT_RXD1_NORMAL_GROUP_3 = 1 << 18
MT_RXD1_NORMAL_GROUP_4 = 1 << 19
MT_RXD1_NORMAL_GROUP_5 = 1 << 20
MT_RXD1_NORMAL_ICV_ERR = 1 << 25
MT_RXD1_NORMAL_BAND_IDX = (27, 0x3)

MT_RXD2_NORMAL_HDR_TRANS = 1 << 7
MT_RXD2_NORMAL_HDR_OFFSET = (13, 0x7)
MT_RXD2_NORMAL_SEC_MODE = (16, 0x1F)
MT_RXD2_NORMAL_AMSDU_ERR = 1 << 23
MT_RXD2_NORMAL_MAX_LEN_ERROR = 1 << 24
MT_RXD2_NORMAL_FRAG = 1 << 27
MT_RXD2_NORMAL_NON_AMPDU = 1 << 30

MT_RXD3_NORMAL_CH_FREQ = (8, 0xFF)
MT_RXD3_NORMAL_FCS_ERR = 1 << 24

MT_RXD4_NORMAL_PAYLOAD_FORMAT = (0, 0x3)

# Group 4 (802.11 header fields), relative words
MT_RXD8_FRAME_CONTROL = (0, 0xFFFF)  # group word 0
MT_RXD10_SEQ_CTRL = (0, 0xFFFF)  # group word 2
MT_RXD10_QOS_CTL = (16, 0xFFFF)  # group word 2

# P-RXV (group 3) word 0
MT_PRXV_TX_RATE = (0, 0x7F)
MT_PRXV_TX_DCM = 1 << 4
MT_PRXV_TX_ER_SU_106T = 1 << 5
MT_PRXV_NSTS = (7, 0xF)
MT_PRXV_TXBF = 1 << 11
MT_PRXV_HT_AD_CODE = 1 << 12
MT_PRXV_HE_RU_ALLOC = (22, 0x1FF)
# P-RXV word 2
MT_PRXV_FRAME_MODE = (2 - 2, 0x7)  # GENMASK(2, 0)
MT_PRXV_HT_SHORT_GI = (3, 0x3)
MT_PRXV_DCM = 1 << 5
MT_PRXV_HT_STBC = (9, 0x3)
MT_PRXV_TX_MODE = (11, 0xF)
# P-RXV word 3: RCPI0..3, one byte per chain, low to high
MT_PRXV_RCPI = ((0, 0xFF), (8, 0xFF), (16, 0xFF), (24, 0xFF))

RXD_FIXED_LEN = 32  # 8 words before the optional groups
GROUP_LEN = 16  # groups 1..4 are 4 words each
GROUP5_LEN = 96  # C-RXV, 24 words

# mt7925_mac_fill_rx_rate: FRAME_MODE values. 4 and 5 both mean 320 MHz ("RXV can report
# 320 in two positions"); 320 MHz is not a capability of the MT7925 but the value is decoded.
FRAME_MODE_TO_MHZ = {0: 20, 1: 40, 2: 80, 3: 160, 4: 320, 5: 320}


def decode_prxv(v0: int, v2: int) -> dict:
    """The rate fields of one connac3 P-RXV, in the dict shape rxd.decode_rxv returns."""
    idx = rxd.fget(v0, MT_PRXV_TX_RATE)
    nsts = rxd.fget(v0, MT_PRXV_NSTS)
    stbc = rxd.fget(v2, MT_PRXV_HT_STBC)
    gi = rxd.fget(v2, MT_PRXV_HT_SHORT_GI)
    mode = rxd.fget(v2, MT_PRXV_TX_MODE)
    frame_mode = rxd.fget(v2, MT_PRXV_FRAME_MODE)
    dcm = bool(v2 & MT_PRXV_DCM)
    ldpc = bool(v0 & MT_PRXV_HT_AD_CODE)
    ru = rxd.fget(v0, MT_PRXV_HE_RU_ALLOC)

    # mt7925_mac_fill_rx_rate keeps nss = NSTS + 1 as is; STBC is reported as a flag.
    nss = nsts + 1
    mcs = idx
    if mode in (
        rxd.MT_PHY_TYPE_VHT,
        rxd.MT_PHY_TYPE_HE_SU,
        rxd.MT_PHY_TYPE_HE_EXT_SU,
        rxd.MT_PHY_TYPE_HE_TB,
        rxd.MT_PHY_TYPE_HE_MU,
        rxd.MT_PHY_TYPE_EHT_SU,
        rxd.MT_PHY_TYPE_EHT_TRIG,
        rxd.MT_PHY_TYPE_EHT_MU,
    ):
        mcs = idx & 0xF

    bw_mhz = FRAME_MODE_TO_MHZ.get(frame_mode)
    ru_tones = None
    offs = 0
    if mode == rxd.MT_PHY_TYPE_HE_EXT_SU and frame_mode == 1 and (idx & MT_PRXV_TX_ER_SU_106T):
        # The driver's one RU case in the P-RXV path: HE-ER-SU on the 106-tone RU. The
        # descriptor width stays 40 MHz (as rxd.decode_rxv reports it); ru_tones carries the RU.
        ru_tones = 106
    elif mode in (rxd.MT_PHY_TYPE_HE_MU, rxd.MT_PHY_TYPE_HE_TB):
        # The HE_RU_ALLOC index follows the connac2 numbering that rxd.decode_rxv maps;
        # the driver itself reads RU details from C-RXV, which is off by default.
        ru_tones, offs = _ru_from_alloc(ru, bw_mhz)

    rate = rxd.phy_rate_mbps(mode, mcs, nss, bw_mhz, gi, dcm, ru_tones)
    return {
        "mode": mode,
        "mode_name": rxd.PHY_MODE_NAMES.get(mode, f"mode{mode}"),
        "mcs": mcs,
        "nss": nss,
        "nsts": nsts + 1,
        "bw_mhz": bw_mhz,
        "gi": gi,
        "stbc": bool(stbc),
        "ldpc": ldpc,
        "dcm": dcm,
        "txbf": bool(v0 & MT_PRXV_TXBF),
        "ru_tones": ru_tones if ru_tones is not None else _full_width_tones(bw_mhz),
        "ru_offset": offs,
        "ru_alloc": ru,
        "rate_mbps": rate,
    }


def _full_width_tones(bw_mhz):
    return {20: 242, 40: 484, 80: 996, 160: 1992}.get(bw_mhz, 242)


def _ru_from_alloc(ru: int, bw_mhz) -> tuple[int, int]:
    """HE RU allocation index to (tones, offset), the same table rxd.decode_rxv uses."""
    if ru <= 36:
        return 26, ru
    if ru <= 52:
        return 52, ru - 37
    if ru <= 60:
        return 106, ru - 53
    if ru <= 64:
        return 242, ru - 61
    if ru <= 66:
        return 484, ru - 65
    if ru == 67:
        return 996, 0
    if ru == 68:
        return 1992, 0
    return _full_width_tones(bw_mhz), 0


def decode(buf: bytes) -> dict | None:
    """Decode one RX transfer from a connac3 chip. None if it is not a normal frame."""
    if len(buf) < RXD_FIXED_LEN:
        return None
    r = struct.unpack_from("<8I", buf, 0)
    rxd0, rxd1, rxd2, rxd3, rxd4 = r[0], r[1], r[2], r[3], r[4]

    ptype = rxd.fget(rxd0, MT_RXD0_PKT_TYPE)
    pflag = rxd.fget(rxd0, MT_RXD0_PKT_FLAG)
    if ptype != rxd.PKT_TYPE_NORMAL:
        # mt7925_queue_rx_skb: a software packet type of 0x3801 (masked 0x380F) is a frame.
        sw_type = rxd.fget(rxd0, MT_RXD0_SW_PKT_TYPE)
        if (sw_type & MT_RXD0_SW_PKT_TYPE_MAP) == MT_RXD0_SW_PKT_TYPE_FRAME:
            ptype = rxd.PKT_TYPE_NORMAL
    if ptype == rxd.PKT_TYPE_RX_EVENT and pflag == 0x1:
        ptype = rxd.PKT_TYPE_NORMAL_MCU

    out = {
        "pkt_type": ptype,
        "pkt_type_name": rxd.PKT_TYPE_NAMES.get(ptype, f"0x{ptype:02x}"),
        "dma_len": rxd.fget(rxd0, MT_RXD0_LENGTH),
        "len": len(buf),
        "fcs_err": bool(rxd3 & MT_RXD3_NORMAL_FCS_ERR),
        "icv_err": bool(rxd1 & MT_RXD1_NORMAL_ICV_ERR),
        "sec_mode": rxd.fget(rxd2, MT_RXD2_NORMAL_SEC_MODE),
        "wlan_idx": rxd.fget(rxd1, MT_RXD1_NORMAL_WLAN_IDX),
        "band_idx": rxd.fget(rxd1, MT_RXD1_NORMAL_BAND_IDX),
        "hdr_trans": bool(rxd2 & MT_RXD2_NORMAL_HDR_TRANS),
        "non_ampdu": bool(rxd2 & MT_RXD2_NORMAL_NON_AMPDU),
        "frag": bool(rxd2 & MT_RXD2_NORMAL_FRAG),
        "amsdu": rxd.fget(rxd4, MT_RXD4_NORMAL_PAYLOAD_FORMAT),
    }
    if ptype not in (rxd.PKT_TYPE_NORMAL, rxd.PKT_TYPE_NORMAL_MCU):
        return out
    if rxd2 & (MT_RXD2_NORMAL_AMSDU_ERR | MT_RXD2_NORMAL_MAX_LEN_ERROR):
        out["error"] = "amsdu/maxlen"
        return out

    band, chan = rxd.status_freq(rxd.fget(rxd3, MT_RXD3_NORMAL_CH_FREQ))
    out["band"], out["channel"] = band, chan
    remove_pad = rxd.fget(rxd2, MT_RXD2_NORMAL_HDR_OFFSET)

    # Groups in mt7925_mac_fill_rx order: 4, 1, 2, 3 (+5 inside 3).
    off = RXD_FIXED_LEN
    prxv = None
    if rxd1 & MT_RXD1_NORMAL_GROUP_4:
        if off + GROUP_LEN > len(buf):
            return out
        g = struct.unpack_from("<4I", buf, off)
        out["fc_rxd"] = rxd.fget(g[0], MT_RXD8_FRAME_CONTROL)
        out["seq_ctrl"] = rxd.fget(g[2], MT_RXD10_SEQ_CTRL)
        out["qos_ctl"] = rxd.fget(g[2], MT_RXD10_QOS_CTL)
        off += GROUP_LEN
    if rxd1 & MT_RXD1_NORMAL_GROUP_1:
        off += GROUP_LEN  # IV / PN; not needed for passive capture
    if rxd1 & MT_RXD1_NORMAL_GROUP_2:
        if off + 4 <= len(buf):
            out["timestamp"] = struct.unpack_from("<I", buf, off)[0]
        off += GROUP_LEN
    if rxd1 & MT_RXD1_NORMAL_GROUP_3:
        if off + GROUP_LEN <= len(buf):
            prxv = struct.unpack_from("<4I", buf, off)
        off += GROUP_LEN
        if rxd1 & MT_RXD1_NORMAL_GROUP_5:
            off += GROUP5_LEN
    elif rxd1 & MT_RXD1_NORMAL_GROUP_5:
        # The driver never steps over group 5 without group 3; record it rather than guess.
        out["g5_without_g3"] = True

    if prxv is not None:
        chains = [rxd.to_rssi(rxd.fget(prxv[3], f)) for f in MT_PRXV_RCPI]
        out["chain_signal"] = chains
        valid = [c for c in chains if c < 0]
        out["rssi"] = max(valid) if valid else None
        out["phy"] = decode_prxv(prxv[0], prxv[2])

    hdr_gap = off + 2 * remove_pad
    out["hdr_gap"] = hdr_gap
    # As on connac2, the record ends at the descriptor's length word, not the transfer end.
    end = min(out["dma_len"], len(buf)) if out["dma_len"] else len(buf)
    if hdr_gap < end:
        out["frame"] = buf[hdr_gap:end]
    return out
