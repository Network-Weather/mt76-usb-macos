#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Characterize extended receive vectors without saving frames or identifiers.

Passive by default. --g5-cycle changes only MT792x DMA descriptor-report bit 23,
then restores it; this is an experimental receive configuration, not a PHY enable.
No frames are transmitted. Unknown vector bytes are summarized, not labeled as RF units.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import math
import os
import statistics
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
import rxd
from mt76_measurements import Group5Guard
from research.mt7925_mib_characterize import parse_target

# mt792x_regs.h:MT_DMA_DCR0(0), MT_DMA_DCR0_RXD_G5_EN at c5a3bd91.
DMA_DCR0 = 0x820E7000
G5_ENABLE = 1 << 23


def vectors(raw: bytes, chip: str) -> dict:
    """Bounded group extraction, indexes relative to Group 3 as in mt76.

    mt7921/mac.c:mt7921_mac_fill_rx and mt7925/mac.c:mt7925_mac_fill_rx,
    c5a3bd91. Only call for normal frames after chip-specific packet classification.
    No bytes from Group 1 (packet numbers), Group 4, or the frame are returned.
    """
    c3 = chip == m.CHIP_MT7925
    fixed = 32 if c3 else 24
    if len(raw) < fixed:
        return {"error": "short_fixed"}
    (length,) = struct.unpack_from("<H", raw)
    end = min(len(raw), length)
    if end < fixed:
        return {"error": "short_dma"}
    flags = (struct.unpack_from("<I", raw, 4)[0] >> (16 if c3 else 11)) & 31
    out = {"mask": flags}
    if flags & 16 and not flags & 4:
        return out | {"error": "g5_without_g3"}
    offset = fixed
    for bit, size in ((8, 16), (1, 16), (2, 16 if c3 else 8)):
        if flags & bit:
            offset += size
    if offset > end:
        return out | {"error": "short_groups"}
    if flags & 4:
        words = 4 if c3 else 2
        if offset + words * 4 > end:
            return out | {"error": "short_g3"}
        out["g3"] = struct.unpack_from(f"<{words}I", raw, offset)
        offset += words * 4
        if flags & 16:
            words = 24 if c3 else 18
            if offset + words * 4 > end:
                return out | {"error": "short_g5"}
            out["g5"] = struct.unpack_from(f"<{words}I", raw, offset)
    return out


def he_fields(v: dict, mode: int) -> dict | None:
    """Source-defined HE fields, with explicit chip-layout lengths.

    Connac2: gen4m 8fddb9d7 nic_connac2x_rx.h, Group5-relative origins.
    Connac3: mt76_connac3_mac.c at c5a3bd91, Group3-relative origins.
    Neither layout is a calibrated topology inference; validate against frames.
    """
    if len(v.get("g3", ())) == 2 and len(v.get("g5", ())) == 18:
        if mode not in (8, 9, 10, 11):
            return None
        g5 = v["g5"]
        return {
            "bss_color": g5[12] & 63,
            "uplink": g5[0] >> 31,
            "spatial_reuse": (g5[9] >> 8) & 15,
            "txop": (g5[12] >> 6) & 127,
        }
    if (
        mode not in (8, 9, 10, 11, 13, 14, 15)
        or len(v.get("g3", ())) != 4
        or len(v.get("g5", ())) != 24
    ):
        return None
    rxv = v["g3"] + v["g5"]
    return {
        "bss_color": (rxv[9] >> 10) & 63,
        "uplink": (rxv[5] >> 2) & 1,
        "spatial_reuse": (rxv[13] >> 8) & 15,
        "txop": (rxv[9] >> 17) & (127 if mode in (13, 14, 15) else 7),
    }


def correlation(xs, ys):
    if len(xs) < 20:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    xx = sum((x - mx) ** 2 for x in xs)
    yy = sum((y - my) ** 2 for y in ys)
    if not xx or not yy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / math.sqrt(xx * yy)


def summarize(rows):
    """Rows contain PHY metadata only; byte correlations are exploratory, not calibration."""
    by_mode = collections.defaultdict(list)
    for mode, signal, group in rows:
        by_mode[mode].append((signal, group))
    result = {}
    for mode, samples in sorted(by_mode.items()):
        word_stats, candidates = [], []
        for index in range(len(samples[0][1])):
            values = [g[index] for _, g in samples]
            word_stats.append({"word": index, "distinct": len(set(values)), "nonzero": any(values)})
            valid = [(s, g[index]) for s, g in samples if s is not None]
            for lane in range(4):
                xs = [(w >> (8 * lane)) & 255 for _, w in valid]
                ys = [s for s, _ in valid]
                rho = correlation(xs, ys)
                if rho is not None and abs(rho) >= 0.8:
                    candidates.append({"word": index, "byte": lane, "r": round(rho, 4)})
        result[mode] = {
            "frames": len(samples),
            "words": word_stats,
            "rssi_byte_correlations_exploratory": candidates,
        }
        if len(samples[0][1]) == 24:
            # Hypothesis only: mt7915's *standalone* vector indexes, tried against
            # connac3 Group 5. The record type/chip differ; do not export as SNR.
            snr = [((g[20] >> 13) & 63) - 16 for _, g in samples]
            result[mode]["g5_word20_snr_hypothesis"] = {
                "min": min(snr),
                "median": statistics.median(snr),
                "max": max(snr),
                "distinct": len(set(snr)),
            }
    return result


def dwell(dev, target, seconds):
    decode = m.decoder_for(dev)
    counts, masks, controls = collections.Counter(), collections.Counter(), collections.Counter()
    rows, he = [], []
    raw_signals = collections.defaultdict(list)
    # Mapping stays in memory and is never serialized.
    advertised = {}
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        try:
            raw = bytes(dev.rx_read(timeout=150))
        except usb.core.USBTimeoutError:
            counts["timeouts"] += 1
            continue
        except usb.core.USBError:
            counts["usb_errors"] += 1
            break
        decoded = decode(raw)
        if not decoded:
            counts["short"] += 1
            continue
        counts[decoded["pkt_type_name"]] += 1
        if decoded["pkt_type"] not in (rxd.PKT_TYPE_NORMAL, rxd.PKT_TYPE_NORMAL_MCU):
            continue
        v = vectors(raw, dev.CHIP)
        if "error" in v:
            counts[v["error"]] += 1
            continue
        masks[f"{v['mask']:02x}"] += 1
        counts["fcs_errors"] += bool(decoded.get("fcs_err"))
        phy = decoded.get("phy", {})
        for name, value in decoded.get("raw_signal", {}).items():
            raw_signals[name].append(value)
        if "g5" in v:
            rows.append((phy.get("mode_name", "unknown"), decoded.get("rssi"), v["g5"]))
            if dev.CHIP == m.CHIP_MT7925:
                equal = (v["g5"][6] & 65535) == (v["g3"][3] & 65535)
                counts["g5_rcpi01_equal_prxv" if equal else "g5_rcpi01_different_prxv"] += 1
        frame = rxd.parse_80211(decoded.get("frame", b""))
        if frame.get("ftype") == 1:
            controls[frame["kind"]] += 1
        if decoded.get("fcs_err"):
            continue
        # IEEE HE Operation extension 36: 3-byte params then BSS color byte.
        for eid, body in frame.get("ie_list", []):
            if eid == 255 and len(body) >= 7 and body[0] == 36 and not body[4] & 128:
                advertised[frame.get("addr2")] = body[4] & 63
        fields = he_fields(v, phy.get("mode"))
        if fields:
            bssid, direction = frame.get("addr2"), None
            if frame.get("ftype") == 2 and frame["to_ds"] != frame["from_ds"]:
                direction = int(frame["to_ds"])
                bssid = frame.get("addr1" if frame["to_ds"] else "addr2")
            he.append((bssid, fields, direction))
    color_checks = collections.Counter()
    direction_checks = collections.Counter()
    fields_summary = {
        key: collections.Counter() for key in ("bss_color", "uplink", "spatial_reuse", "txop")
    }
    for address, fields, direction in he:
        for key, value in fields.items():
            fields_summary[key][value] += 1
        if address in advertised:
            color_checks["match" if fields["bss_color"] == advertised[address] else "mismatch"] += 1
        if direction is not None:
            direction_checks["match" if fields["uplink"] == direction else "mismatch"] += 1
    return {
        "target": target,
        "elapsed_s": round(time.monotonic() - started, 3),
        "packets": dict(counts),
        "group_masks": dict(masks),
        "control_subtypes": dict(controls),
        "group5_by_phy": summarize(rows),
        "raw_signal": {
            name: {"count": len(values), "min": min(values), "max": max(values)}
            for name, values in raw_signals.items()
        },
        "he_eht_candidates": fields_summary,
        "he_eht_color_vs_beacon": dict(color_checks),
        "he_eht_uplink_vs_frame_control": dict(direction_checks),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="+", type=parse_target)
    parser.add_argument("--usb-id", required=True)
    parser.add_argument("--seconds", type=float, default=6)
    parser.add_argument(
        "--g5-cycle", action="store_true", help="MT7921 only: baseline, enable, restore"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("seconds must be 1..60")
    dev = m.open_device(args.usb_id)
    if args.g5_cycle and dev.CHIP != m.CHIP_MT7921:
        parser.error("register experiment is MT7921 only")
    patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
    result = {
        "tool": "rx_vector_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "chip": dev.CHIP,
        "usb_id": args.usb_id,
        "firmware_sha256": {
            "patch": hashlib.sha256(patch).hexdigest(),
            "ram": hashlib.sha256(ram).hexdigest(),
        },
        "runs": [],
    }
    with dev:
        dev.bringup(patch, ram, log=lambda *_: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        for target in args.targets:
            dev.tune(*target)
            time.sleep(0.2)
            guard = Group5Guard(dev) if args.g5_cycle else None
            phases = ("baseline", "enabled", "restored") if args.g5_cycle else ("baseline",)
            try:
                for phase in phases:
                    if guard is not None:
                        if phase == "enabled":
                            guard.begin()
                        elif phase == "restored":
                            guard.restore()
                    record = dwell(dev, target, args.seconds) | {"phase": phase}
                    if guard is not None:
                        record["dcr0_readback"] = hex(dev.rr(DMA_DCR0))
                    result["runs"].append(record)
                    print(
                        json.dumps(
                            {
                                "target": target,
                                "phase": phase,
                                "packets": record["packets"],
                                "groups": record["group_masks"],
                            }
                        ),
                        file=sys.stderr,
                        flush=True,
                    )
            finally:
                if guard is not None:
                    guard.restore()
                    result["restored_register"] = not guard.active
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")
    return 1 if any(r["packets"].get("usb_errors") for r in result["runs"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
