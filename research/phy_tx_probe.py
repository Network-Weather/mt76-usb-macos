#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (C) 2023 MediaTek Inc.
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Try bounded HT/VHT/HE fixed-rate TX, with independent receiver evidence.

At most60 synthetic no-ACK probes, normally50ms spacing, bounded channels.
The bandwidth suite alone tests40MHz, primary6/center8, with20MHz controls.
Lowband/coding/timing suites use channels1/6/11 and exclude VHT; others use36/149.
Known OFDM controls bracket the candidate rates. No association or ambient frame
output. Full firmware reload in finally removes all experimental transmitter state.
Requires explicit TX acknowledgment. This is research, not a production API.
"""

import argparse
import collections
import concurrent.futures
import contextlib
import datetime
import hashlib
import json
import os
import statistics
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
import rxd as legacy_rx
from research import mt7925_tx_probe as c3
from research.dual_radio_probe import fixed_rate_txwi, tx_status_records
from research.rx_vector_probe import DMA_DCR0, G5_ENABLE

# mt76 c5a3bd91: mt76.h enum mt76_phy_type; connac2/3_mac.h
# MT_TX_RATE_MODE bits 9:6, IDX bits 5:0, NSS bits starting at 10.
# One stream, MCS 0/7, bandwidth 20; no short GI, STBC or power changes.
RATES = (
    ("ofdm_before", 0x4B),
    ("ht0", 2 << 6),
    ("ht7", (2 << 6) | 7),
    ("vht0", 4 << 6),
    ("he0", 8 << 6),
    ("ofdm_after", 0x4B),
)
# mt7915/mac.c mt7915_mac_write_txwi_tm at the same pin: HT NSS = 1 + MCS/8;
# encode NSS-1 for HT/VHT/HE. These are candidate TX settings, not RX evidence.
STREAM_RATES = (
    ("ofdm_before", 0x4B),
    ("ht0_control", 2 << 6),
    ("ht8_2ss", (1 << 10) | (2 << 6) | 8),
    ("vht0_2ss", (1 << 10) | (4 << 6)),
    ("he0_2ss", (1 << 10) | (8 << 6)),
    ("ofdm_after", 0x4B),
)
LOWBAND_RATES = (
    ("ofdm_before", 0x4B),
    ("ht0", 2 << 6),
    ("ht8_2ss", (1 << 10) | (2 << 6) | 8),
    ("he0", 8 << 6),
    ("he0_2ss", (1 << 10) | (8 << 6)),
    ("ofdm_after", 0x4B),
)
# mt76.h CCK_RATE and mac80211.c mt76_rates: indices0..3 are1/2/5.5/11 Mbps;
# bit2 selects short preamble. Only2/11 Mbps short controls are included.
CCK_RATES = (
    ("ofdm_before", 0x4B),
    ("cck1_long", 0),
    ("cck2_long", 1),
    ("cck5_5_long", 2),
    ("cck11_long", 3),
    ("ofdm_after", 0x4B),
)
PREAMBLE_RATES = (
    ("ofdm_before", 0x4B),
    ("cck2_long", 1),
    ("cck2_short", 5),
    ("cck11_long", 3),
    ("cck11_short", 7),
    ("ofdm_after", 0x4B),
)
# Connac3 STBC is bit14 (not Connac2 bit13). For one spatial stream,
# upstream mt7915 test descriptors encode two space-time streams, NSS field1.
# This is an independently received format experiment, not a gain claim.
STBC_RATES = (
    ("ht8_before", 0x488),
    ("ht0_before", 0x80),
    ("ht0_stbc", 0x4480),
    ("ht0_after", 0x80),
    ("ht8_after", 0x488),
)
# Connac3 HE-SU mode8, DCM bit4, STBC bit14. No LDPC/GI/power changes.
HE_CODING_RATES = (
    ("he0_2ss_before", 0x600),
    ("he0_1ss", 0x200),
    ("he0_dcm_1ss", 0x210),
    ("he0_stbc_1ss", 0x4600),
    ("he0_2ss_after", 0x600),
)
CONNAC3_CODING_CODES = {0x4480, 0x210, 0x4600}
TIMING_BURST_RATES = (("cck1_paced_before", 0), ("cck1_burst", 0), ("cck1_paced_after", 0))
# Pinned MT7925 ROM83c0ac maps config GI to ITDR1 bits13:12 and LDPC to25.
# Keep LTF, spatial selection and all unknown low bits at existing baseline.
# Independent RX, not the field names alone, determines the actual PHY format.
HT_TABLE_RATES = tuple(
    (name, 0x488) for name in ("ht8_before", "ht8_gi1", "ht8_middle", "ht8_ldpc", "ht8_after")
)
HT_TABLE_OPTIONS = ((0, 0), (1, 0), (0, 0), (0, 1), (0, 0))
HE_TABLE_RATES = tuple(
    (name, 0x600)
    for name in ("he2_before", "he2_gi1_ltf1", "he2_gi2_ltf2", "he2_ltf1", "he2_ldpc", "he2_after")
)
HE_TABLE_OPTIONS = ((0, 0), (1, 0), (2, 0), (0, 0), (0, 1), (0, 0))
HE_TABLE_LTF = (0, 1, 2, 1, 0, 0)
HE_CODING_LTF = (1, 1, 1, 1, 1)
HE_G5_RATES = (("he2_g5_off_before", 0x600), ("he2_g5_on", 0x600), ("he2_g5_off_after", 0x600))
# mt76.h mode9 is HE extended-range SU; DCM is rate bit4. One stream,
# full20MHz tone allocation, MCS0, no STBC and no power/beamforming changes.
HE_ER_RATES = (
    ("he2_before", 0x600),
    ("he1_control", 0x200),
    ("he_er1", 0x240),
    ("he_er1_dcm", 0x250),
    ("he2_after", 0x600),
)
HE_ER_LTF = (1, 1, 1, 1, 1)
WIDTH_RATES = (
    ("ht20_before", 0x488),
    ("ht40", 0x488),
    ("ht20_after", 0x488),
    ("he20_before", 0x600),
    ("he40", 0x600),
    ("he20_after", 0x600),
)
WIDTH_TX_MHZ = (20, 40, 20, 20, 40, 20)
WIDTH_LTF = (0, 0, 0, 1, 1, 1)
# Full40MHz HE-SU requires LDPC (BCC is limited to <=242-tone RUs).
# Apply LDPC to both HE20 controls too, isolating width within that triplet.
WIDTH_OPTIONS = ((0, 0), (0, 0), (0, 0), (0, 1), (0, 1), (0, 1))
TABLE_SPATIAL_RATES = tuple(
    (name, 0x80)
    for name in (
        "ht0_wtbl_before",
        "ht0_table_wf0",
        "ht0_wtbl_middle",
        "ht0_table_wf1",
        "ht0_table_duplicate",
        "ht0_wtbl_after",
    )
)
TABLE_SPATIAL_SPE = (None, 0, None, 1, 24, None)
STATUS_FORMAT_RATES = (
    ("ht8_format0_before", 0x488),
    ("ht8_format1", 0x488),
    ("ht8_format0_after", 0x488),
)
STATUS_FORMATS = (0, 1, 0)
HE_TABLE_SPATIAL_RATES = tuple(
    (name.replace("ht0", "he0"), 0x200) for name, _ in TABLE_SPATIAL_RATES
)
CONNAC3_CODING_CODES.update((0x240, 0x250))
ALLOWED_RATE_CODES = {
    rate
    for _, rate in RATES
    + STREAM_RATES
    + CCK_RATES
    + PREAMBLE_RATES
    + STBC_RATES
    + HE_CODING_RATES
    + HE_ER_RATES
}
# Vendor gen4m 8fddb9d7 wlanAntPathFavorSelect: 0=WF0, 1=WF1,
# 0x18=duplicated one-stream path. Connac2 TXD DW7 bits 15:11.
# Keep DW6 selection bit 10 at the existing zero, as mt7915 test descriptors do.
SPATIAL_SPE = (0, 1, 0, 24, 0)
SPATIAL_RATES = tuple(
    (name, 0x4B) for name in ("spe0_before", "spe1", "spe0_middle", "spe24_duplicate", "spe0_after")
)


def suite_rates(suite, channel):
    if type(channel) is not int or channel not in (1, 6, 11, 36, 149):
        raise ValueError("only bounded non-DFS test channels")
    if (channel <= 11) != (
        suite
        in (
            "lowband",
            "cck",
            "preamble",
            "stbc",
            "he-coding",
            "timing-burst",
            "ht-table",
            "he-table",
            "he-coding-ltf",
            "he-g5-cycle",
            "he-er",
            "bandwidth",
            "table-spatial",
            "he-table-spatial",
            "tx-status-format",
        )
    ):
        raise ValueError("lowband/CCK suite required for 2.4GHz; other suites require 5GHz")
    suites = {
        "baseline": RATES,
        "streams": STREAM_RATES,
        "spatial": SPATIAL_RATES,
        "lowband": LOWBAND_RATES,
        "cck": CCK_RATES,
        "preamble": PREAMBLE_RATES,
        "stbc": STBC_RATES,
        "he-coding": HE_CODING_RATES,
        "timing-burst": TIMING_BURST_RATES,
        "ht-table": HT_TABLE_RATES,
        "he-table": HE_TABLE_RATES,
        "he-coding-ltf": HE_CODING_RATES,
        "he-g5-cycle": HE_G5_RATES,
        "he-er": HE_ER_RATES,
        "bandwidth": WIDTH_RATES,
        "table-spatial": TABLE_SPATIAL_RATES,
        "he-table-spatial": HE_TABLE_SPATIAL_RATES,
        "tx-status-format": STATUS_FORMAT_RATES,
    }
    if suite not in suites:
        raise ValueError("unknown bounded rate suite")
    if suite == "bandwidth" and channel != 6:
        raise ValueError("bandwidth experiment requires primary6/center8")
    return suites[suite]


def descriptor(
    dev, frame, seq, code, fixed_bw=False, spe_idx=None, *, width_mhz=20, status_format=0
):
    if code not in ALLOWED_RATE_CODES:
        raise ValueError("rate outside bounded experiment")
    if (
        type(status_format) is not int
        or status_format not in (0, 1)
        or (status_format and (dev.CHIP != m.CHIP_MT7925 or code != 0x488 or width_mhz != 20))
    ):
        raise ValueError("alternate status format requires MT7925 HT8/20MHz")
    if type(width_mhz) is not int or width_mhz not in (20, 40):
        raise ValueError("bounded20/40MHz transmit only")
    if width_mhz == 40 and (dev.CHIP != m.CHIP_MT7925 or code not in (0x488, 0x600)):
        raise ValueError("40MHz experiment requires MT7925 HT8/HE2SS")
    if code in CONNAC3_CODING_CODES and dev.CHIP != m.CHIP_MT7925:
        raise ValueError("coding experiment rate encoding is MT7925-only")
    if spe_idx is not None and (
        dev.CHIP != m.CHIP_MT7921 or code != 0x4B or spe_idx not in (0, 1, 24)
    ):
        raise ValueError("spatial experiment is Connac2 OFDM6 with SPE 0/1/24 only")
    if dev.CHIP == m.CHIP_MT7925:
        data = bytearray(c3.build_txwi(frame, seq, disable_mat=True))
        if status_format:
            word = struct.unpack_from("<I", data, 20)[0]
            struct.pack_into("<I", data, 20, word | (1 << 8))
        if fixed_bw or width_mhz == 40:
            # connac3_mac.h: FIXED_BW bit25, BW bits24:22 codes0=20/1=40MHz.
            word = struct.unpack_from("<I", data, 24)[0]
            struct.pack_into(
                "<I", data, 24, (word & ~(7 << 22)) | (1 << 25) | (int(width_mhz == 40) << 22)
            )
        return bytes(data)
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("unsupported chip")
    data = bytearray(fixed_rate_txwi(dev, frame, seq, "ofdm6", True))
    struct.pack_into("<I", data, 24, m.MT_TXD6_FIXED_BW | (code << 16))
    if spe_idx is not None:
        word = struct.unpack_from("<I", data, 28)[0]
        struct.pack_into("<I", data, 28, (word & ~(31 << 11)) | (spe_idx << 11))
    return bytes(data)


def program_rate(dev, code, *, gi=0, ldpc=0, ltf=0, spe_idx=None):
    if code not in ALLOWED_RATE_CODES:
        raise ValueError("rate outside bounded experiment")
    if spe_idx is not None and (
        dev.CHIP != m.CHIP_MT7925
        or code not in (0x80, 0x200)
        or type(spe_idx) is not int
        or spe_idx not in (0, 1, 24)
        or gi
        or ldpc
        or ltf != int(code == 0x200)
    ):
        raise ValueError("table spatial experiment is MT7925 HT0/HE0 SPE0/1/24 only")
    if code in CONNAC3_CODING_CODES and dev.CHIP != m.CHIP_MT7925:
        raise ValueError("coding experiment rate encoding is MT7925-only")
    allowed = {
        0x488: ((0, 0, 0), (1, 0, 0), (0, 0, 1)),
        0x600: ((0, 0, 0), (1, 1, 0), (2, 2, 0), (0, 1, 0), (0, 0, 1), (0, 1, 1)),
        0x200: ((0, 0, 0), (0, 1, 0)),
        0x210: ((0, 0, 0), (0, 1, 0)),
        0x4600: ((0, 0, 0), (0, 1, 0)),
        0x240: ((0, 1, 0),),
        0x250: ((0, 1, 0),),
    }
    if any(type(v) is not int for v in (gi, ltf, ldpc)) or (gi, ltf, ldpc) not in allowed.get(
        code, ((0, 0, 0),)
    ):
        raise ValueError("bounded table GI/LDPC/LTF controls only")
    if (gi or ldpc or ltf) and dev.CHIP != m.CHIP_MT7925:
        raise ValueError("table GI/LDPC/LTF experiment is MT7925-only")
    if dev.CHIP != m.CHIP_MT7925:
        return
    # mt7925/mac.c mt7925_mac_set_fixed_rate_table at c5a3bd91.
    dev.wr(c3.ITDR0, code)
    # mt7996 fixed_rate_table: selection1 takes BMC WTBL; selection0 uses
    # the table's explicit SPE index. MT7925 ROM83c0ac maps these to bit6/11:7.
    spatial = 1 << 6 if spe_idx is None else spe_idx << 7
    dev.wr(c3.ITDR1, spatial | (gi << 12) | (ltf << 16) | (ldpc << 25))
    dev.wr(c3.ITCR, (1 << 31) | (1 << 16) | c3.RATE_TABLE_INDEX)
    for _ in range(100):
        if not dev.rr(c3.ITCR) & (1 << 31):
            return
        time.sleep(0.001)
    raise RuntimeError("rate table busy")


def he_ltf_raw(raw, *, vendor=False):
    """Two source-defined LTF locations, called only for independently matched HE.

    mt7921/mac.c selects group5 after six skipped words; connac2 HE radiotap
    then reads rxv[2], meaning Group5 word8. Pinned gen4m nic_connac2x_rx.h
    HAL_MAC_CONNAC2X_RX_VT_GET_LTF instead reads Group5 word0. Keep both as
    explicit alternatives; controlled reception validates the vendor origin.
    Missing/truncated group5 is unknown, never zero.
    """
    if len(raw) < 24:
        return None
    size, flags = struct.unpack_from("<II", raw)
    size &= 65535
    required = legacy_rx.MT_RXD1_NORMAL_GROUP_3 | legacy_rx.MT_RXD1_NORMAL_GROUP_5
    if not 24 <= size <= len(raw) or flags & required != required:
        return None
    offset = 24
    for flag, length in (
        (legacy_rx.MT_RXD1_NORMAL_GROUP_4, 16),
        (legacy_rx.MT_RXD1_NORMAL_GROUP_1, 16),
        (legacy_rx.MT_RXD1_NORMAL_GROUP_2, 8),
    ):
        if flags & flag:
            offset += length
    offset += 8
    if offset + 72 > size:
        return None
    return (struct.unpack_from("<I", raw, offset + (0 if vendor else 32))[0] >> 17) & 3


def receiver_g5_word(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("Group5 experiment receiver must be MT7961")
    value = dev.rr(DMA_DCR0)
    if type(value) is not int or not 0 <= value < 0xFFFFFFFF:
        raise ValueError("invalid receiver DMA descriptor control")
    return value


def timing_padding(length):
    """Only an optional128-byte private vendor IE, for packet-time controls."""
    if type(length) is not int or length not in (0, 128):
        raise ValueError("timing padding must be0 or128 bytes")
    return b"\xdd\x7e\x02NW\x02" + bytes(122) if length else b""


def phase_gap(suite, phase):
    if suite == "timing-burst":
        if type(phase) is not int or not 0 <= phase < 3:
            raise ValueError("bounded three-phase timing control required")
        return (0.05, 0, 0.05)[phase]
    return 0.05


def capture(dev, expected, per_phase, ready, stop, rates=RATES, marker=None, tx_timing=False):
    decode = m.decoder_for(dev)
    seen = [set() for _ in rates]
    phys = [collections.Counter() for _ in rates]
    signals = [[] for _ in rates]
    status = collections.Counter()
    counts = collections.Counter()
    started = time.monotonic()
    ready.set()
    while not stop.is_set():
        try:
            raw = bytes(dev.rx_read(timeout=100))
        except usb.core.USBTimeoutError:
            continue
        if marker is not None and marker in raw:
            counts["own_nonce_usb_records"] += 1
        d = decode(raw)
        if not d:
            continue
        counts["decoded_usb_records"] += 1
        if d["pkt_type"] == 0:
            rows = (
                c3.tx_status(raw, include_timing=tx_timing)
                if dev.CHIP == m.CHIP_MT7925
                else tx_status_records(raw)
            )
            for row in rows:
                if tx_timing and dev.CHIP == m.CHIP_MT7925:
                    row["status_received_host_seconds"] = time.monotonic() - started
                status[json.dumps(row, sort_keys=True)] += 1
        frame = d.get("frame", b"")
        if len(frame) < 24:
            continue
        counts["frames_seen"] += 1
        seq = struct.unpack_from("<H", frame, 22)[0] >> 4
        if expected.get(seq) != frame:
            if marker is not None and marker in frame:
                counts["own_nonce_frame_mismatch"] += 1
            continue
        if d.get("fcs_err"):
            counts["controlled_fcs_errors"] += 1
            continue
        phase = seq // per_phase
        seen[phase].add(seq)
        if d.get("rssi") is not None:
            signals[phase].append(d["rssi"])
        phy = d.get("phy", {})
        fields = {
            k: phy.get(k)
            for k in (
                "mode_name",
                "mcs",
                "nss",
                "nsts",
                "stbc",
                "bw_mhz",
                "gi",
                "ldpc",
                "dcm",
                "rate_mbps",
            )
        }
        if dev.CHIP == m.CHIP_MT7921 and phy.get("mode_name") in ("HE-SU", "HE-ER-SU"):
            fields["he_ltf_mt76_pointer_raw"] = he_ltf_raw(raw)
            fields["he_ltf_vendor_word0_raw"] = he_ltf_raw(raw, vendor=True)
            fields["he_ltf_group5_present"] = bool(
                struct.unpack_from("<I", raw, 4)[0] & legacy_rx.MT_RXD1_NORMAL_GROUP_5
            )
        phys[phase][json.dumps(fields, sort_keys=True)] += 1
    return {
        "chip": dev.CHIP,
        "counts": dict(counts),
        "phases": [
            {
                "name": name,
                "rate_code": code,
                "unique_exact_frames": len(seen[i]),
                "median_rssi_raw": statistics.median(signals[i]) if signals[i] else None,
                "phy": [{"fields": json.loads(k), "count": v} for k, v in phys[i].items()],
            }
            for i, (name, code) in enumerate(rates)
        ],
        "tx_status": [{"fields": json.loads(k), "count": v} for k, v in status.items()],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--transmitter", choices=("mt7961", "mt7925"), required=True)
    p.add_argument("--channel", type=int, choices=(1, 6, 11, 36, 149), default=36)
    p.add_argument("--per-phase", type=int, choices=range(1, 11), default=5)
    p.add_argument("--acknowledge-experimental-transmit", action="store_true")
    p.add_argument("--fixed-bw", action="store_true", help="connac3 explicit 20 MHz TXD flag")
    p.add_argument(
        "--receiver-g5",
        action="store_true",
        help="temporarily enable MT7961 Group5 for HE table/coding checks; restore and reload receiver",
    )
    p.add_argument(
        "--tx-timing",
        action="store_true",
        help="raw Connac3 TXS timing fields; no unit or ranging claim",
    )
    p.add_argument(
        "--timing-padding",
        type=int,
        choices=(0, 128),
        default=0,
        help="append128-byte private IE for TX timing length control",
    )
    p.add_argument(
        "--suite",
        choices=(
            "baseline",
            "streams",
            "spatial",
            "lowband",
            "cck",
            "preamble",
            "stbc",
            "he-coding",
            "timing-burst",
            "ht-table",
            "he-table",
            "he-coding-ltf",
            "he-g5-cycle",
            "he-er",
            "bandwidth",
            "table-spatial",
            "he-table-spatial",
            "tx-status-format",
        ),
        default="baseline",
    )
    args = p.parse_args()
    if args.receiver_g5 and (
        args.transmitter != "mt7925"
        or args.suite
        not in ("he-table", "he-coding-ltf", "he-g5-cycle", "he-er", "he-table-spatial")
    ):
        p.error("receiver Group5 is restricted to MT7925 HE table/coding experiments")
    if args.suite == "he-g5-cycle" and not args.receiver_g5:
        p.error("he-g5-cycle requires explicit --receiver-g5")
    if not args.acknowledge_experimental_transmit:
        p.error("explicit transmit acknowledgment required")
    if args.fixed_bw and args.transmitter != "mt7925":
        p.error("fixed-bw variant applies only to mt7925")
    if args.tx_timing and args.transmitter != "mt7925":
        p.error("TX timing currently supports only the Connac3 transmitter")
    if args.timing_padding and not args.tx_timing:
        p.error("timing padding requires explicit --tx-timing")
    if args.suite == "timing-burst" and not args.tx_timing:
        p.error("timing-burst requires explicit --tx-timing")
    if args.suite == "tx-status-format" and not args.tx_timing:
        p.error("tx-status-format requires explicit --tx-timing for format-aware telemetry")
    if args.suite == "spatial" and args.transmitter != "mt7961":
        p.error("spatial suite currently supports only the Connac2 transmitter")
    if (
        args.suite
        in (
            "stbc",
            "he-coding",
            "ht-table",
            "he-table",
            "he-coding-ltf",
            "he-er",
            "bandwidth",
            "table-spatial",
            "he-table-spatial",
            "tx-status-format",
        )
        and args.transmitter != "mt7925"
    ):
        p.error("coding suites currently support only the Connac3 transmitter")
    try:
        rates = suite_rates(args.suite, args.channel)
    except ValueError as exc:
        p.error(str(exc))
    out = {
        "tool": "phy_tx_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transmitter": args.transmitter,
        "channel": args.channel,
        "configured_center": 8 if args.suite == "bandwidth" else args.channel,
        "configured_width_mhz": 40 if args.suite == "bandwidth" else 20,
        "phase_tx_width_mhz": WIDTH_TX_MHZ if args.suite == "bandwidth" else [20] * len(rates),
        "per_phase": args.per_phase,
        "gap_s": None if args.suite == "timing-burst" else 0.05,
        "phase_gap_seconds": [phase_gap(args.suite, i) for i in range(len(rates))],
        "fixed_bw": args.fixed_bw or args.suite == "bandwidth",
        "suite": args.suite,
        "tx_timing": args.tx_timing,
        "requested_status_formats": STATUS_FORMATS if args.suite == "tx-status-format" else None,
        "timing_padding_bytes": args.timing_padding,
        "spatial_codes": SPATIAL_SPE if args.suite == "spatial" else None,
        "table_spatial_codes": TABLE_SPATIAL_SPE
        if args.suite in ("table-spatial", "he-table-spatial")
        else None,
        "table_gi_ldpc": {
            "ht-table": HT_TABLE_OPTIONS,
            "he-table": HE_TABLE_OPTIONS,
            "bandwidth": WIDTH_OPTIONS,
        }.get(args.suite),
        "submitted": 0,
        "receiver_g5": args.receiver_g5,
        "table_ltf": {
            "he-table-spatial": (1,) * 6,
            "bandwidth": WIDTH_LTF,
            "he-table": HE_TABLE_LTF,
            "he-coding-ltf": HE_CODING_LTF,
            "he-er": HE_ER_LTF,
        }.get(args.suite),
        "firmware_sha256": {},
    }
    if args.tx_timing:
        out["host_submissions"] = []
    tx_index = int(args.transmitter == "mt7925")
    # A fresh private-use vendor IE prevents a previous run's buffered probe
    # from matching this run. Never output the nonce, ambient frames, or headers.
    marker = b"\xdd\x0c\x02NW\x01" + os.urandom(8)
    expected = {
        seq: c3.controlled_frame(seq) + marker + timing_padding(args.timing_padding)
        for seq in range(len(rates) * args.per_phase)
    }
    out["frame_bytes_without_fcs"] = len(expected[0])
    out["unique_run_payload"] = True
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]

        def boot(i, cleanup=False):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            wide = args.suite == "bandwidth" and not cleanup
            dev.tune(
                "2.4GHz" if args.channel <= 11 else "5GHz",
                args.channel,
                8 if wide else args.channel,
                40 if wide else 20,
            )

        for i, dev in enumerate(radios):
            boot(i)
            out["firmware_sha256"][dev.CHIP] = [hashlib.sha256(b).hexdigest() for b in images[i]]
        tx = radios[tx_index]
        original_receiver_g5 = None
        try:
            if args.receiver_g5:
                original_receiver_g5 = receiver_g5_word(radios[0])
                if args.suite == "he-g5-cycle" and original_receiver_g5 & G5_ENABLE:
                    raise ValueError("Group5 cycle requires an initially disabled report bit")
                initial = (
                    original_receiver_g5
                    if args.suite == "he-g5-cycle"
                    else original_receiver_g5 | G5_ENABLE
                )
                radios[0].wr(DMA_DCR0, initial)
                enabled = receiver_g5_word(radios[0])
                out["receiver_g5_register"] = {
                    "before": hex(original_receiver_g5),
                    "enabled": hex(enabled),
                }
                if enabled != initial:
                    raise RuntimeError("receiver Group5 write not verified")
                out["receiver_g5_phase_values"] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                stop = threading.Event()
                ready = [threading.Event(), threading.Event()]
                jobs = [
                    pool.submit(
                        capture,
                        dev,
                        expected,
                        args.per_phase,
                        ready[i],
                        stop,
                        rates,
                        marker,
                        args.tx_timing,
                    )
                    for i, dev in enumerate(radios)
                ]
                try:
                    if not all(event.wait(5) for event in ready):
                        raise RuntimeError("capture not ready")
                    time.sleep(0.3)
                    submission_origin = time.monotonic()
                    for phase, (_, code) in enumerate(rates):
                        if args.suite == "he-g5-cycle":
                            target = (
                                original_receiver_g5 | G5_ENABLE
                                if phase == 1
                                else original_receiver_g5
                            )
                            radios[0].wr(DMA_DCR0, target)
                            observed = receiver_g5_word(radios[0])
                            out["receiver_g5_phase_values"].append(hex(observed))
                            if observed != target:
                                raise RuntimeError("Group5 cycle write not verified")
                        options = {
                            "ht-table": HT_TABLE_OPTIONS,
                            "he-table": HE_TABLE_OPTIONS,
                            "bandwidth": WIDTH_OPTIONS,
                        }.get(args.suite)
                        gi, ldpc = options[phase] if options else (0, 0)
                        ltfs = {
                            "he-table-spatial": (1,) * 6,
                            "bandwidth": WIDTH_LTF,
                            "he-table": HE_TABLE_LTF,
                            "he-coding-ltf": HE_CODING_LTF,
                            "he-er": HE_ER_LTF,
                        }.get(args.suite)
                        ltf = ltfs[phase] if ltfs else 0
                        table_spe = (
                            TABLE_SPATIAL_SPE[phase]
                            if args.suite in ("table-spatial", "he-table-spatial")
                            else None
                        )
                        program_rate(tx, code, gi=gi, ldpc=ldpc, ltf=ltf, spe_idx=table_spe)
                        for seq in range(phase * args.per_phase, (phase + 1) * args.per_phase):
                            if any(job.done() for job in jobs):
                                raise RuntimeError("capture stopped before transmit completed")
                            frame = expected[seq]
                            spe = SPATIAL_SPE[phase] if args.suite == "spatial" else None
                            tx_width = WIDTH_TX_MHZ[phase] if args.suite == "bandwidth" else 20
                            body = (
                                descriptor(
                                    tx,
                                    frame,
                                    seq,
                                    code,
                                    args.fixed_bw or args.suite == "bandwidth",
                                    spe,
                                    width_mhz=tx_width,
                                    status_format=STATUS_FORMATS[phase]
                                    if args.suite == "tx-status-format"
                                    else 0,
                                )
                                + frame
                            )
                            wire = struct.pack("<I", len(body)) + body
                            wire += bytes((-len(wire)) % 4 + 4)
                            before_submit = time.monotonic()
                            tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                            out["submitted"] += 1
                            if args.tx_timing:
                                out["host_submissions"].append(
                                    {
                                        "sequence": seq,
                                        "start_seconds": before_submit - submission_origin,
                                        "call_seconds": time.monotonic() - before_submit,
                                    }
                                )
                            gap = phase_gap(args.suite, phase)
                            if gap:
                                time.sleep(gap)
                        time.sleep(0.15)
                    time.sleep(0.5)
                finally:
                    stop.set()
                out["radios"] = [job.result(timeout=3) for job in jobs]
            out["alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if original_receiver_g5 is not None:
                try:
                    radios[0].wr(DMA_DCR0, original_receiver_g5)
                    out["receiver_g5_restored"] = (
                        receiver_g5_word(radios[0]) == original_receiver_g5
                    )
                except Exception as exc:
                    out["receiver_g5_restore_error_type"] = type(exc).__name__
            try:
                boot(tx_index, cleanup=True)
                out["cleanup_reload_alive"] = tx.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
            if args.receiver_g5 or args.suite == "bandwidth":
                try:
                    boot(0, cleanup=True)
                    out["cleanup_receiver_reload_alive"] = radios[0].alive()
                except Exception as exc:
                    out["cleanup_receiver_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2, sort_keys=True))
    return int(
        "error_type" in out
        or not out.get("cleanup_reload_alive")
        or not all(out.get("alive_after", [False]))
        or (
            args.receiver_g5
            and (
                not out.get("receiver_g5_restored") or not out.get("cleanup_receiver_reload_alive")
            )
        )
        or (args.suite == "bandwidth" and not out.get("cleanup_receiver_reload_alive"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
