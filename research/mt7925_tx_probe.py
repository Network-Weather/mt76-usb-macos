#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (C) 2023 MediaTek Inc.
# Copyright (C) 2016 Felix Fietkau <nbd@nbd.name>
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Bounded MT7925 no-ACK OFDM transmit, independently observed by MT7961.

Research only; does not enable the production inject() API. Programs volatile
fixed-rate table entry 18 (and 25 with --alternate-rate) using the upstream path. Reloads firmware
afterward to remove experimental table state. Requires explicit TX acknowledgment;
at most 60 directed probes, 50 ms apart, 5 GHz channel 36/149, 20 MHz. No ambient
frame bytes, addresses, or packet fingerprints are serialized.
"""

from __future__ import annotations

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
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.dual_radio_probe import SOURCE, SSID

# openwrt/mt76 c5a3bd91aa735b669618610d5f0ebfa5786845a6:
# mt7925/mac.c mt7925_mac_set_fixed_rate_table, mt7925/init.c basic rates,
# mt792x_regs.h MT_WTBL_IT*, mt792x.h MT792x_BASIC_RATES_TBL + OFDM6 index 4.
ITCR, ITDR0, ITDR1 = 0x820D43B0, 0x820D43B8, 0x820D43BC
RATE_TABLE_INDEX = 18
# mt76 mac80211.c mt76_rates: OFDM6 is entry 4, OFDM54 entry 11;
# basic-rate table base 14. Hardware codes are mode 1 + indices 11/12.
RATES = {"ofdm6": (18, 0x4B, 6.0), "ofdm54": (25, 0x4C, 54.0)}


def set_ofdm_rate(dev, rate="ofdm6"):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("rate table operation is MT7925 only")
    table, code, _ = RATES[rate]
    dev.wr(ITDR0, code)
    dev.wr(ITDR1, 1 << 6)  # MT_WTBL_SPE_IDX_SEL, as upstream.
    dev.wr(ITCR, (1 << 16) | (1 << 31) | table)
    for _ in range(100):
        control = dev.rr(ITCR)
        if not control & (1 << 31):
            return {"control_after": control, "staging_rate": dev.rr(ITDR0)}
        time.sleep(0.001)
    raise RuntimeError("fixed-rate table operation did not finish")


def build_txwi(frame, sequence, power_code=0, *, disable_mat=False, rate="ofdm6"):
    """MT7925 USB injected mgmt subset; mt7925/mac.c and mt76_connac3_mac.h.

    Important: connac3 word 6 rate is a TABLE INDEX, not connac2's inline PHY rate.
    All fields from c5a3bd91. No association, keys, MLD, ACK, or aggregation.
    """
    if len(frame) < 24 or frame[:2] != b"\x40\x00":
        raise ValueError("only Probe Request frames supported")
    if not 0 <= sequence < 4096 or power_code not in (0, -8, -16, -32):
        raise ValueError("sequence or candidate attenuation code out of range")
    words = [0] * 16
    words[0] = len(frame) + 64 | (1 << 23) | (0x10 << 25)  # SF, ALTX0
    words[1] = (1 << 31) | (12 << 16) | (2 << 14)  # fixed, hdrlen/2, 802.11
    words[2] = 4 | ((power_code & 63) << 26)  # subtype, POWER_OFFSET
    words[3] = (1 << 31) | (1 << 28) | (sequence << 16) | (15 << 11) | 1
    if frame[4] & 1:
        words[3] |= 1 << 4  # BCM moved from connac2 word 2 to word 3.
    words[5] = 3 | (1 << 10)  # PID_FIRST, TX_STATUS_HOST
    words[6] = (RATES[rate][0] << 16) | (1 << 4) | (1 << 2)  # one MSDU, DAS
    if disable_mat:
        words[6] |= 1 << 3  # MT_TXD6_DIS_MAT, upstream non-MLD vif path.
    return struct.pack("<16I", *words)


def tx_status(raw):
    # mt7925_mac_rx_check: MT_TXS_HDR_SIZE=4 DW, MT_TXS_SIZE=12 DW.
    if len(raw) < 16:
        return []
    end = min(len(raw), int.from_bytes(raw[:2], "little"))
    records = []
    for offset in range(16, end - 47, 48):
        words = struct.unpack_from("<12I", raw, offset)
        records.append(
            {
                "sequence": words[1] >> 20,
                "format": (words[0] >> 23) & 3,
                "rate_raw": words[0] & 0x3FFF,
                "power_raw": words[1] & 255,
                "ack_error_bits": (words[0] >> 16) & 7,
                "error_bits_16_22": (words[0] >> 16) & 127,
                "tx_count_format0": (words[5] >> 25) & 31,
                "pid": words[3] >> 24,
            }
        )
    return records


def planned_rate(sequence, alternate):
    return "ofdm54" if alternate and sequence % 2 else "ofdm6"


def controlled_frame(sequence, alternate=False):
    frame = m.build_probe_request(SOURCE, SSID, sequence)
    rates_ie = bytes((1, 2, 0x8C, 0x6C)) if alternate else bytes((1, 1, 0x8C))
    return frame[:-6] + rates_ie


def capture(dev, seconds, barrier, count, phase_codes, alternate=False):
    decode = m.decoder_for(dev)
    counts, phys, statuses = collections.Counter(), collections.Counter(), collections.Counter()
    sequences, signals = set(), []
    phase_rx = collections.defaultdict(set)
    phase_rssi, phase_power = collections.defaultdict(list), collections.defaultdict(list)
    rate_rx, rate_rssi, rate_power = (
        collections.defaultdict(lambda: collections.defaultdict(list)) for _ in range(3)
    )
    per_phase = count // len(phase_codes)
    barrier.wait(timeout=15)
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        try:
            raw = bytes(dev.rx_read(timeout=150))
        except usb.core.USBTimeoutError:
            continue
        except usb.core.USBError:
            counts["usb_errors"] += 1
            break
        d = decode(raw)
        if not d:
            continue
        counts[d["pkt_type_name"]] += 1
        if d["pkt_type"] == 0 and dev.CHIP == m.CHIP_MT7925:
            for status in tx_status(raw):
                seq = status.pop("sequence")
                if seq < count:
                    phase_power[seq // per_phase].append(status["power_raw"])
                    rate_power[seq // per_phase][str(status["rate_raw"])].append(
                        status["power_raw"]
                    )
                    statuses[json.dumps(status, sort_keys=True)] += 1
        frame = d.get("frame", b"")
        if len(frame) < 24 or d.get("fcs_err"):
            continue
        # Match our unique directed SSID too: connac3 address translation may
        # rewrite SOURCE. Never emit any replacement/ambient address.
        marker = bytes((0, len(SSID))) + SSID
        if frame[24 : 24 + len(marker)] != marker:
            continue
        seq = struct.unpack_from("<H", frame, 22)[0] >> 4
        if seq >= count:
            continue
        sequences.add(seq)
        phase_rx[seq // per_phase].add(seq)
        counts["controlled_source_preserved"] += frame[10:16] == SOURCE
        counts["controlled_source_rewritten"] += frame[10:16] != SOURCE
        expected = controlled_frame(seq, alternate)
        counts["controlled_bytes_exact"] += frame == expected
        phy = d.get("phy", {})
        rate_key = f"{phy.get('mode_name')}:{phy.get('rate_mbps')}"
        rate_rx[seq // per_phase][rate_key].append(seq)
        counts["controlled_rate_mismatch"] += (
            phy.get("mode_name") != "OFDM"
            or phy.get("rate_mbps") != RATES[planned_rate(seq, alternate)][2]
        )
        phys[f"{phy.get('mode_name')}:{phy.get('rate_mbps')}"] += 1
        if d.get("rssi") is not None:
            signals.append(d["rssi"])
            phase_rssi[seq // per_phase].append(d["rssi"])
            rate_rssi[seq // per_phase][rate_key].append(d["rssi"])
    return {
        "chip": dev.CHIP,
        "counts": dict(counts),
        "unique_sequences": len(sequences),
        "controlled_phys": dict(phys),
        "median_rssi": statistics.median(signals) if signals else None,
        "tx_status": [{"fields": json.loads(k), "count": v} for k, v in statuses.items()],
        "phases": [
            {
                "phase": i,
                "power_code": code,
                "unique_sequences": len(phase_rx[i]),
                "median_rssi": statistics.median(phase_rssi[i]) if phase_rssi[i] else None,
                "tx_power_raw_values": dict(collections.Counter(phase_power[i])),
                "by_received_rate": {
                    rate: {
                        "unique_sequences": len(set(seqs)),
                        "median_rssi": statistics.median(rate_rssi[i][rate])
                        if rate_rssi[i][rate]
                        else None,
                    }
                    for rate, seqs in rate_rx[i].items()
                },
                "tx_power_by_rate_raw": {
                    rate: dict(collections.Counter(values))
                    for rate, values in rate_power[i].items()
                },
            }
            for i, code in enumerate(phase_codes)
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, choices=(36, 149), default=36)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--power-code", type=int, choices=(0, -8, -16, -32), default=0)
    parser.add_argument("--power-cycle", action="store_true", help="60 frames: 0/-8/0/-16/0 codes")
    parser.add_argument(
        "--cycle-depth",
        type=int,
        choices=(16, 32),
        default=16,
        help="largest candidate attenuation code in a power cycle",
    )
    parser.add_argument(
        "--alternate-rate", action="store_true", help="alternate OFDM6 and OFDM54 per packet"
    )
    parser.add_argument("--disable-mat", action="store_true", help="set connac3 DIS_MAT bit")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit or not 1 <= args.count <= 60:
        parser.error("TX acknowledgment and count 1..60 required")
    if args.power_cycle and (args.count != 60 or args.power_code != 0):
        parser.error("power-cycle requires count 60 and default power-code")
    if not args.power_cycle and args.cycle_depth != 16:
        parser.error("cycle-depth requires power-cycle")
    phase_codes = (
        [0, -(args.cycle_depth // 2), 0, -args.cycle_depth, 0]
        if args.power_cycle
        else [args.power_code]
    )
    result = {
        "tool": "mt7925_tx_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": args.channel,
        "count": args.count,
        "power_code": args.power_code,
        "disable_mat": args.disable_mat,
        "phase_codes": phase_codes,
        "alternate_rate": args.alternate_rate,
        "gap_s": 0.05,
        "firmware_sha256": {},
        "submitted": 0,
    }
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = {}
        for dev in radios:
            patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
            images[dev.CHIP] = (patch, ram)
            result["firmware_sha256"][dev.CHIP] = {
                "patch": hashlib.sha256(patch).hexdigest(),
                "ram": hashlib.sha256(ram).hexdigest(),
            }
            dev.bringup(patch, ram, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", args.channel, args.channel, 20)
        try:
            result["rate_table"] = set_ofdm_rate(radios[1])
            if args.alternate_rate:
                result["ofdm54_rate_table"] = set_ofdm_rate(radios[1], "ofdm54")
            barrier = threading.Barrier(3)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [
                    pool.submit(
                        capture, dev, 8, barrier, args.count, phase_codes, args.alternate_rate
                    )
                    for dev in radios
                ]
                barrier.wait(timeout=15)
                time.sleep(0.5)
                for seq in range(args.count):
                    frame = controlled_frame(seq, args.alternate_rate)
                    code = phase_codes[seq // (args.count // len(phase_codes))]
                    body = (
                        build_txwi(
                            frame,
                            seq,
                            code,
                            disable_mat=args.disable_mat,
                            rate=planned_rate(seq, args.alternate_rate),
                        )
                        + frame
                    )
                    wire = struct.pack("<I", len(body)) + body
                    wire += b"\x00" * ((-len(wire)) % 4 + 4)
                    radios[1].bulk_out(radios[1].ep_out_ac_be, wire, 1000)
                    result["submitted"] += 1
                    time.sleep(0.05)
                result["radios"] = [job.result(timeout=20) for job in jobs]
            result["register_alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
        finally:
            try:
                # Existing bringup performs WFSYS reset of retained firmware state.
                dev = radios[1]
                dev.bringup(*images[dev.CHIP], log=lambda *_: None)
                dev.set_monitor_mode()
                dev.set_sniffer(True)
                dev.tune("5GHz", args.channel, args.channel, 20)
                result["cleanup_firmware_reload_alive"] = dev.alive()
            except Exception as exc:
                result["cleanup_error"] = type(exc).__name__ + ": " + str(exc)
    failed = (
        "error" in result
        or "cleanup_error" in result
        or not result.get("cleanup_firmware_reload_alive")
        or not all(result.get("register_alive_after", [False]))
        or any(r["counts"].get("usb_errors") for r in result.get("radios", []))
    )
    heard = result.get("radios", [{}])[0].get("unique_sequences", 0)
    result["outcome"] = (
        "error" if failed else ("independently_received" if heard else "no_independent_decode")
    )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 1 if failed else (0 if heard else 2)


if __name__ == "__main__":
    raise SystemExit(main())
