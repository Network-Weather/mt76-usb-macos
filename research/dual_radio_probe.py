#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Measure shared packet clocks, control exchanges, and optional controlled TX.

Passive unless --transmit and --acknowledge-experimental-transmit are supplied.
Optional MT7961 transmission: 1 Mb/s CCK or 6 Mb/s OFDM, at most 120 directed
probe requests, 50 ms apart, on 2.4 GHz 1/6/11 or non-DFS 5 GHz 36/149.
No association, deauthentication, or ACK solicitation. No network identifiers,
packet hashes, or payloads are serialized. Both receive loops share a barrier.
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
import rxd
from research.control_frames import parse_control
from research.mt7925_mib_characterize import parse_target
from research.rx_vector_probe import summarize, vectors

SOURCE = bytes.fromhex("02005e105adb")
SSID = b"mt76-observability-cal"


def delta32(value, origin):
    return ((value - origin + (1 << 31)) % (1 << 32)) - (1 << 31)


def fit_clock(pairs, split_index=None):
    """Fit shared beacon timestamps, including independent second-half validation."""
    if len(pairs) < 20:
        return {"status": "insufficient_pairs", "pairs": len(pairs)}
    pairs = sorted(pairs, key=lambda p: p[2])
    xs = [delta32(p[0], pairs[0][0]) for p in pairs]
    ys = [delta32(p[1], pairs[0][1]) for p in pairs]

    def fit(x, y):
        mx, my = statistics.mean(x), statistics.mean(y)
        denominator = sum((v - mx) ** 2 for v in x)
        if not denominator:
            return None
        slope = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / denominator
        return slope, my - slope * mx

    def residuals(x, y, model):
        slope, intercept = model
        values = sorted(abs(b - slope * a - intercept) for a, b in zip(x, y, strict=True))
        return {
            "median_us_if_1mhz": round(statistics.median(values), 3),
            "p95_us_if_1mhz": round(values[int((len(values) - 1) * 0.95)], 3),
            "max_us_if_1mhz": round(max(values), 3),
        }

    full = fit(xs, ys)
    split = len(xs) // 2 if split_index is None else split_index
    if not 2 <= split <= len(xs) - 2:
        return {"status": "insufficient_split_pairs", "pairs": len(pairs)}
    train = fit(xs[:split], ys[:split])
    if full is None or train is None:
        return {"status": "degenerate", "pairs": len(pairs)}
    host_span = pairs[-1][2] - pairs[0][2]
    return {
        "status": "fit",
        "pairs": len(pairs),
        "relative_drift_ppm": round((full[0] - 1) * 1e6, 4),
        "host_span_s": round(host_span, 3),
        "radio1_ticks_per_host_second": round((xs[-1] - xs[0]) / host_span, 1)
        if host_span
        else None,
        "all_fit": residuals(xs, ys, full),
        "second_half_prediction": residuals(xs[split:], ys[split:], train),
    }


def fixed_rate_txwi(dev, frame, sequence, rate, status):
    """Change only the fixed rate in the existing connac2 management TX descriptor.

    mt76 c5a3bd91: mt76_connac2_mac.h MT_TX_RATE_MODE bits9:6 and
    mac80211.c mt76_rates OFDM_RATE(11,60); mode 1 + index 11 = 0x4b.
    """
    data = bytearray(dev._build_txwi(frame, sequence, 3 if status else 0))
    rate_bits = {"cck1": 0, "ofdm6": 0x4B}[rate]
    struct.pack_into("<I", data, 24, m.MT_TXD6_FIXED_BW | rate_bits << 16)
    return bytes(data)


def tx_status_records(raw):
    """MT7921 TXS: two-word prefix then eight-word records (mt7921_rx_check).

    Constants: mt76_connac2_mac.h MT_TXS*, c5a3bd91. Return only metadata.
    The power byte is not called calibrated dBm; no-ACK TX cannot measure an ACK's RSSI.
    """
    if len(raw) < 8:
        return []
    end = min(len(raw), int.from_bytes(raw[:2], "little"))
    result = []
    for offset in range(8, end - 31, 32):
        words = struct.unpack_from("<8I", raw, offset)
        result.append(
            {
                "format": (words[0] >> 23) & 3,
                "rate": words[0] & 0x3FFF,
                "ack_error_bits": (words[0] >> 16) & 7,
                "tx_power_raw": words[1] & 255,
                "pid": words[3] >> 24,
            }
        )
    return result


def capture(dev, seconds, barrier):
    counts, control_counts, ba_types = (
        collections.Counter(),
        collections.Counter(),
        collections.Counter(),
    )
    decode = m.decoder_for(dev)
    fingerprints = collections.defaultdict(list)
    control_pairs, rows, synthetic = set(), [], []
    acked, holes = 0, 0
    status_counts = collections.Counter()
    barrier.wait(timeout=15)
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        try:
            raw = bytes(dev.rx_read(timeout=150))
        except usb.core.USBTimeoutError:
            counts["timeouts"] += 1
            continue
        except usb.core.USBError:
            counts["usb_errors"] += 1
            break
        at = time.monotonic()
        d = decode(raw)
        if not d:
            continue
        counts[d["pkt_type_name"]] += 1
        if d["pkt_type"] == rxd.PKT_TYPE_TXS and dev.CHIP == m.CHIP_MT7921:
            for status in tx_status_records(raw):
                status_counts[json.dumps(status, sort_keys=True)] += 1
        if d.get("fcs_err") or not d.get("frame"):
            continue
        frame = d["frame"]
        f = rxd.parse_80211(frame)
        if f.get("ftype") == 0 and f.get("subtype") in (5, 8) and "timestamp" in d:
            digest = hashlib.sha256(frame).digest()
            fingerprints[digest].append((d["timestamp"], at))
        control = parse_control(frame)
        if control:
            control_counts[f.get("kind", "unknown")] += 1
            if "ta" in control:
                control_pairs.add((control["ta"], control["ra"]))
            if "ba_type" in control:
                ba_types[str(control["ba_type"])] += 1
            if "error" in control or "unsupported" in control:
                counts[control.get("error", control.get("unsupported"))] += 1
            if "acknowledged" in control:
                counts["decoded_blockacks"] += 1
                acked += control["acknowledged"]
                holes += control["zero_positions_through_last_ack"]
        if len(frame) >= 24 and frame[10:16] == SOURCE:
            seq = struct.unpack_from("<H", frame, 22)[0] >> 4
            phy = d.get("phy", {})
            synthetic.append((seq, phy.get("mode_name"), phy.get("rate_mbps"), d.get("rssi")))
            v = vectors(raw, dev.CHIP)
            if "g5" in v:
                rows.append((phy.get("mode_name", "unknown"), d.get("rssi"), v["g5"]))
    return {
        "chip": dev.CHIP,
        "duration_s": round(time.monotonic() - start, 3),
        "packets": dict(counts),
        "control_subtypes": dict(control_counts),
        "distinct_directed_control_pairs": len(control_pairs),
        "ba_types": dict(ba_types),
        "blockack_ack_bits_sum_not_unique_packets": acked,
        "blockack_zero_positions_through_last_ack_not_loss_rate": holes,
        "synthetic_frames": len(synthetic),
        "synthetic_unique_sequences": len({s[0] for s in synthetic}),
        "synthetic_phys": dict(collections.Counter(f"{s[1]}:{s[2]}" for s in synthetic)),
        "synthetic_rssi_median": statistics.median([s[3] for s in synthetic if s[3] is not None])
        if any(s[3] is not None for s in synthetic)
        else None,
        "synthetic_group5": summarize(rows),
        "tx_status_records": [
            {"fields": json.loads(key), "count": count} for key, count in status_counts.items()
        ],
    }, fingerprints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=parse_target)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--transmit", type=int, default=0)
    parser.add_argument("--rate", choices=("cck1", "ofdm6"), default="cck1")
    parser.add_argument("--tx-status", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 3 <= args.seconds <= 60 or not 0 <= args.transmit <= 120:
        parser.error("seconds must be 3..60 and transmit 0..120")
    band, channel, _, width = args.target
    if args.transmit:
        if not args.acknowledge_experimental_transmit:
            parser.error("transmit requires explicit acknowledgment")
        if (band, channel) not in {
            ("2.4GHz", 1),
            ("2.4GHz", 6),
            ("2.4GHz", 11),
            ("5GHz", 36),
            ("5GHz", 149),
        } or width != 20:
            parser.error("TX is limited to 20 MHz on 2.4 GHz 1/6/11 or 5 GHz 36/149")
        if band == "5GHz" and args.rate == "cck1":
            parser.error("CCK is not a 5 GHz PHY")
        if args.seconds < args.transmit * 0.05 + 2:
            parser.error("receive window must exceed burst by two seconds")
    result = {
        "tool": "dual_radio_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "target": args.target,
        "transmit_requested": args.transmit,
        "rate": args.rate,
        "radios": [],
        "firmware_sha256": {},
    }
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        for dev in radios:
            patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
            result["firmware_sha256"][dev.CHIP] = {
                "patch": hashlib.sha256(patch).hexdigest(),
                "ram": hashlib.sha256(ram).hexdigest(),
            }
            dev.bringup(patch, ram, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune(*args.target)
        barrier = threading.Barrier(3)
        sent = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(capture, dev, args.seconds, barrier) for dev in radios]
            barrier.wait(timeout=15)
            time.sleep(0.5)
            for seq in range(args.transmit):
                frame = m.build_probe_request(SOURCE, SSID, seq)
                # Advertise the tested OFDM rate when transmitting OFDM.
                if args.rate == "ofdm6":
                    frame = frame[:-6] + bytes((1, 1, 0x8C))
                body = fixed_rate_txwi(radios[0], frame, seq, args.rate, args.tx_status) + frame
                wire = struct.pack("<I", len(body)) + body
                wire += b"\x00" * ((-len(wire)) % 4 + 4)
                radios[0].bulk_out(radios[0].ep_out_ac_be, wire, 1000)
                sent += 1
                time.sleep(0.05)
            captures = [job.result(timeout=args.seconds + 10) for job in jobs]
        result["transmit_submitted"] = sent
        result["register_alive_after"] = [dev.alive() for dev in radios]
        for record, _ in captures:
            result["radios"].append(record)
        a, b = captures[0][1], captures[1][1]
        common = a.keys() & b.keys()
        unique = [key for key in common if len(a[key]) == len(b[key]) == 1]
        pairs = [(a[k][0][0], b[k][0][0], a[k][0][1]) for k in unique]
        result["beacon_matching"] = {
            "radio_unique_fingerprints": [len(a), len(b)],
            "common": len(common),
            "unambiguous_common": len(unique),
        }
        result["clock"] = fit_clock(pairs)
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")
    return 1 if any(r["packets"].get("usb_errors") for r in result["radios"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
