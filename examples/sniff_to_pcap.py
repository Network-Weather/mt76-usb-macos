#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Capture one channel to a radiotap pcap that Wireshark can read.

Passive receive only. Once frames land in a pcap, every existing 802.11 tool
works on them and our decode can be checked against an independent one.

Usage: sniff_to_pcap.py <channel> <duration_seconds> [out.pcap] [band]
       band is 2.4GHz | 5GHz | 6GHz (default 2.4GHz)

Firmware is loaded from $MT76_FW_DIR (or the older $MT7921_FW_DIR), defaulting to
<repo>/firmware; the pinned SHA-256s are checked.
"""

import argparse
import os
import struct
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = m.firmware_dir()  # $MT76_FW_DIR, then $MT7921_FW_DIR, then <repo>/firmware
CHAN_BAND = m.CHAN_BAND

LINKTYPE_IEEE802_11_RADIOTAP = 127

# radiotap "present" bits we emit, in ascending bit order (required).
RT_FLAGS = 1 << 1
RT_RATE = 1 << 2
RT_CHANNEL = 1 << 3
RT_DBM_ANTSIGNAL = 1 << 5
RT_MCS = 1 << 19
RT_VHT = 1 << 21
RT_HE = 1 << 23
# radiotap.org/fields/TLV: bit 28 says the rest of the header is a type-length-value list,
# 4-byte aligned; U-SIG and EHT exist only as TLV types (33 and 34).
RT_TLV = 1 << 28
RT_TLV_U_SIG = 33
RT_TLV_EHT = 34
# radiotap.org/fields/U-SIG: common word
USIG_BW_KNOWN = 0x00000002
USIG_BW_SHIFT = 15  # 0=20, 1=40, 2=80, 3=160, 4=320-1, 5=320-2
USIG_BW_CODE = {20: 0, 40: 1, 80: 2, 160: 3, 320: 4}
# radiotap.org/fields/EHT: known word and data words
EHT_KNOWN_GI = 0x00000004
EHT_KNOWN_RU_MRU_SIZE = 0x00400000
EHT_DATA0_GI_SHIFT = 7  # 0=0.8us, 1=1.6us, 2=3.2us
EHT_RU_MRU_SIZE_CODE = {20: 3, 40: 4, 80: 5, 160: 6, 320: 7}  # 242, 484, 996, 2x996, 4x996 tones
EHT_USER_MCS_KNOWN = 0x00000002
EHT_USER_CODING_KNOWN = 0x00000004
EHT_USER_NSS_KNOWN = 0x00000010
EHT_USER_CAPTURED = 0x00000080
EHT_USER_CODING_LDPC = 0x00080000
EHT_USER_MCS_SHIFT = 20
EHT_USER_NSS_SHIFT = 24  # NSS - 1
EHT_MODES = (rxd.MT_PHY_TYPE_EHT_SU, rxd.MT_PHY_TYPE_EHT_TRIG, rxd.MT_PHY_TYPE_EHT_MU)

RT_FLAG_BADFCS = 0x40

CH_FLAG_CCK = 0x0020
CH_FLAG_OFDM = 0x0040
CH_FLAG_2GHZ = 0x0080
CH_FLAG_5GHZ = 0x0100


def freq_for(band: str, chan: int) -> int:
    if band == "2.4GHz":
        return 2484 if chan == 14 else 2407 + chan * 5
    if band == "5GHz":
        return 5000 + chan * 5
    if band == "6GHz":
        return 5950 + chan * 5
    raise ValueError(f"unknown band {band!r}")


def radiotap(freq: int, band: str, rssi, bad_fcs: bool, phy: dict | None = None) -> bytes:
    """An 8-byte header plus flags, channel, signal, and optional PHY metadata."""
    present = RT_FLAGS | RT_CHANNEL | RT_DBM_ANTSIGNAL
    has_rate = False
    has_mcs = False
    has_vht = False
    has_he = False
    has_eht = False

    if phy:
        mode = phy.get("mode")
        rate_mbps = phy.get("rate_mbps")
        if mode in (rxd.MT_PHY_TYPE_CCK, rxd.MT_PHY_TYPE_OFDM) and rate_mbps:
            has_rate = True
            present |= RT_RATE
        elif mode in (rxd.MT_PHY_TYPE_HT, rxd.MT_PHY_TYPE_HT_GF):
            has_mcs = True
            present |= RT_MCS
        elif mode == rxd.MT_PHY_TYPE_VHT:
            has_vht = True
            present |= RT_VHT
        elif mode in (
            rxd.MT_PHY_TYPE_HE_SU,
            rxd.MT_PHY_TYPE_HE_EXT_SU,
            rxd.MT_PHY_TYPE_HE_TB,
            rxd.MT_PHY_TYPE_HE_MU,
        ):
            has_he = True
            present |= RT_HE
        elif mode in EHT_MODES:
            has_eht = True
            present |= RT_TLV

    body = bytearray()
    # Bit 1: Flags (1 byte, align 1)
    body.append(RT_FLAG_BADFCS if bad_fcs else 0)

    # Bit 2: Rate (1 byte, align 1, in 500 kbps units)
    if has_rate:
        body.append(round(phy["rate_mbps"] * 2.0))

    # Bit 3: Channel (4 bytes, align 2)
    if len(body) % 2 != 0:
        body.append(0)
    ch_flags = CH_FLAG_2GHZ | CH_FLAG_CCK if band == "2.4GHz" else CH_FLAG_5GHZ | CH_FLAG_OFDM
    body.extend(struct.pack("<HH", freq, ch_flags))

    # Bit 5: dBm Antenna Signal (1 byte, align 1)
    body.append((rssi if rssi is not None else -128) & 0xFF)

    # Bit 19: MCS (3 bytes, align 1)
    if has_mcs:
        known = 0x07  # BW, MCS, GI known
        mcs_flags = 0
        if phy.get("bw_mhz") == 40:
            mcs_flags |= 1
        if phy.get("gi"):
            mcs_flags |= 4
        body.extend(struct.pack("<BBB", known, mcs_flags, phy.get("mcs", 0)))

    # Bit 21: VHT (12 bytes, align 2)
    if has_vht:
        if len(body) % 2 != 0:
            body.append(0)
        bw_val = (
            4
            if phy.get("bw_mhz") == 80
            else (1 if phy.get("bw_mhz") == 40 else (0 if phy.get("bw_mhz") == 20 else 11))
        )
        gi_val = 1 if phy.get("gi") else 0
        vht_known = 0x0001 | 0x0004 | 0x0040  # STBC, GI, BW known
        flags = (1 if phy.get("stbc") else 0) | (gi_val << 2)
        nss = max(1, phy.get("nss", 1))
        user0 = ((phy.get("mcs", 0) & 0x0F) << 4) | (nss & 0x0F)
        coding = 1 if phy.get("ldpc") else 0  # bit 0 is user 0's coding, 1 = LDPC
        # known(u16) flags(u8) bandwidth(u8) mcs_nss[4](u8) coding(u8) group_id(u8)
        # partial_aid(u16), per the VHT field of the radiotap specification. All 12
        # bytes must be present: it_len covers every field the present bitmap claims,
        # and a short one makes Wireshark reject the packet as malformed.
        body.extend(
            struct.pack("<HBBBBBBBBH", vht_known, flags, bw_val, user0, 0, 0, 0, coding, 0, 0)
        )

    # Bit 23: HE (12 bytes, align 2)
    if has_he:
        if len(body) % 2 != 0:
            body.append(0)
        mode = phy.get("mode")
        fmt = (
            1
            if mode == rxd.MT_PHY_TYPE_HE_EXT_SU
            else (
                2 if mode == rxd.MT_PHY_TYPE_HE_MU else (3 if mode == rxd.MT_PHY_TYPE_HE_TB else 0)
            )
        )
        d1 = fmt | 0x0020 | 0x0040 | 0x0080 | 0x0200 | 0x4000
        d2 = 0x0002  # GI_KNOWN
        if mode in (rxd.MT_PHY_TYPE_HE_MU, rxd.MT_PHY_TYPE_HE_TB):
            d2 |= 0x4000 | ((phy.get("ru_offset", 0) & 0x3F) << 8)
        d3 = (
            ((phy.get("mcs", 0) & 0x0F) << 8)
            | ((1 << 12) if phy.get("dcm") else 0)
            | ((1 << 13) if phy.get("ldpc") else 0)
            | ((1 << 15) if phy.get("stbc") else 0)
        )
        d4 = 0
        ru_tones = phy.get("ru_tones", 0)
        bw_mhz = phy.get("bw_mhz", 20)
        if mode in (rxd.MT_PHY_TYPE_HE_MU, rxd.MT_PHY_TYPE_HE_TB):
            bw_ru_map = {26: 4, 52: 5, 106: 6, 242: 7, 484: 8, 996: 9, 1992: 10}
            he_bw_ru = bw_ru_map.get(
                ru_tones,
                3 if bw_mhz == 160 else (2 if bw_mhz == 80 else (1 if bw_mhz == 40 else 0)),
            )
        elif mode == rxd.MT_PHY_TYPE_HE_EXT_SU:
            he_bw_ru = 6 if ru_tones == 106 else (1 if bw_mhz == 40 else 0)
        else:
            he_bw_ru = 3 if bw_mhz == 160 else (2 if bw_mhz == 80 else (1 if bw_mhz == 40 else 0))
        d5 = (he_bw_ru & 0x0F) | ((phy.get("gi", 0) & 0x03) << 4)
        nsts = phy.get("nsts", phy.get("nss", 1))
        d6 = nsts & 0x0F
        body.extend(struct.pack("<HHHHHH", d1, d2, d3, d4, d5, d6))

    # TLV section (bit 28): U-SIG then EHT, each 4-byte aligned. Wireshark reads a fixed 40
    # bytes of EHT data plus one 4-byte user_info, so both are emitted in full.
    if has_eht:
        while len(body) % 4:
            body.append(0)
        body.extend(eht_tlvs(phy))

    hdr = struct.pack("<BBHI", 0, 0, 8 + len(body), present)
    return bytes(hdr + body)


def eht_tlvs(phy: dict) -> bytes:
    """U-SIG (bandwidth) and EHT (GI, RU size, one user's MCS/NSS/coding) TLVs for an EHT
    frame, from the P-RXV fields the decoder reports. Pads to the 4-byte TLV alignment first;
    the caller places this at the end of the radiotap body (header offset 8 is aligned)."""
    out = bytearray()
    bw = phy.get("bw_mhz") or 20
    common = 0
    if bw in USIG_BW_CODE:
        common = USIG_BW_KNOWN | (USIG_BW_CODE[bw] << USIG_BW_SHIFT)
    usig = struct.pack("<III", common, 0, 0)  # value and mask: no U-SIG bits are known
    out += struct.pack("<HH", RT_TLV_U_SIG, len(usig)) + usig

    known = EHT_KNOWN_GI
    data = [0] * 9
    data[0] = (phy.get("gi", 0) & 0x3) << EHT_DATA0_GI_SHIFT
    # Only an EHT-SU PPDU occupies its whole bandwidth with one RU. In EHT-MU and EHT-TRIG
    # (OFDMA) the user's RU can be smaller than the PPDU, and the P-RXV does not tell us
    # which, so the RU/MRU size stays unknown there; Wireshark still computes the rate from
    # the U-SIG bandwidth.
    if phy.get("mode") == rxd.MT_PHY_TYPE_EHT_SU and bw in EHT_RU_MRU_SIZE_CODE:
        known |= EHT_KNOWN_RU_MRU_SIZE
        data[1] = EHT_RU_MRU_SIZE_CODE[bw]
    nss = max(1, phy.get("nss", 1))
    user = (
        EHT_USER_MCS_KNOWN
        | EHT_USER_CODING_KNOWN
        | EHT_USER_NSS_KNOWN
        | EHT_USER_CAPTURED
        | ((phy.get("mcs", 0) & 0xF) << EHT_USER_MCS_SHIFT)
        | (((nss - 1) & 0xF) << EHT_USER_NSS_SHIFT)
        | (EHT_USER_CODING_LDPC if phy.get("ldpc") else 0)
    )
    eht = struct.pack("<I9II", known, *data, user)
    out += struct.pack("<HH", RT_TLV_EHT, len(eht)) + eht
    # TLV items are 4-aligned: 4 + 12 and 4 + 44 already are.
    return bytes(out)


def pcap_header(snaplen: int = 65535) -> bytes:
    return struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, snaplen, LINKTYPE_IEEE802_11_RADIOTAP)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=int)
    parser.add_argument("duration", type=float, help="capture duration in seconds")
    parser.add_argument("output", nargs="?", default="capture.pcap")
    parser.add_argument("band", nargs="?", choices=sorted(CHAN_BAND), default="2.4GHz")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    parser.add_argument(
        "--width",
        type=int,
        choices=sorted(m.WIDTH_TO_SNIFFER_BW),
        default=20,
        help="sniffer bandwidth in MHz (default 20); wider needs --center",
    )
    parser.add_argument(
        "--center",
        type=int,
        help="center channel for --width above 20 (defaults to the control channel)",
    )
    args = parser.parse_args()
    if args.width > 20 and args.center is None:
        parser.error("--center is required when --width is above 20 MHz")
    if not 1 <= args.channel <= 255:
        parser.error("channel must be between 1 and 255")
    if not 0 < args.duration <= 86400:
        parser.error("duration must be greater than 0 and at most 86400 seconds")
    chan = args.channel
    secs = args.duration
    out = args.output
    band = args.band

    dev = m.open_device()
    patch, ram = m.load_firmware(dev.CHIP, FW_DIR)

    mode = "wb" if args.overwrite else "xb"
    with dev, open(out, mode) as fh:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        dev.tune(band, chan, args.center, args.width)
        time.sleep(0.2)
        fh.write(pcap_header())
        print(f"channel {chan} ({band}, {args.width} MHz), {secs:g}s -> {out}")

        freq = freq_for(band, chan)
        n = written = 0
        deadline = time.monotonic() + secs
        while time.monotonic() < deadline:
            try:
                raw = bytes(dev.rx_read(timeout=500))
            except usb.core.USBError:
                continue
            n += 1
            d = m.decoder_for(dev)(raw)
            if d is None:
                continue
            frame = d.get("frame")
            if not frame or len(frame) < 10:
                continue
            # The descriptor's channel is authoritative; a hop may be in flight.
            f = freq
            if d.get("band") and d.get("channel"):
                f = freq_for(d["band"], d["channel"])
            rt = radiotap(
                f, d.get("band", band), d.get("rssi"), bool(d.get("fcs_err")), d.get("phy")
            )
            pkt = rt + frame
            now = time.time()
            fh.write(struct.pack("<IIII", int(now), int((now % 1) * 1e6), len(pkt), len(pkt)))
            fh.write(pkt)
            written += 1
        print(f"{n} transfers, {written} frames written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
