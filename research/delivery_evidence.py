#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Compare BlockAck receiver evidence with each dongle's recent QoS-data visibility.

Passive only, both radios on one channel. Keep MAC addresses, packet fingerprints,
and per-sequence histories only in memory. Serialize aggregate opportunity counts.
A bit in repeated BA windows is not a unique packet. An absent recent observation
does not prove a link loss. Shared BA events are gated by shared-beacon clock fit.
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
from research.control_frames import parse_control
from research.dual_radio_probe import delta32, fit_clock
from research.mt7925_mib_characterize import parse_target


def qos_key(frame):
    """Clear MAC header only: (transmitter, receiver, TID, sequence)."""
    if len(frame) < 26:
        return None
    (fc,) = struct.unpack_from("<H", frame)
    if (fc & 0xFC) != 0x88 or frame[4] & 1 or fc & (1 << 10):
        return None
    (sc,) = struct.unpack_from("<H", frame, 22)
    if sc & 15:
        return None
    offset = 30 if fc & 0x300 == 0x300 else 24
    if len(frame) < offset + 2:
        return None
    (qos,) = struct.unpack_from("<H", frame, offset)
    if (qos >> 5) & 3 not in (0, 3):
        return None
    return frame[10:16], frame[4:10], qos & 15, sc >> 4


class DeliveryWindow:
    """Recent sequence visibility, preserving BA direction/TID and modulo-4096 wrap."""

    def __init__(self, lookback_us):
        self.lookback_us = lookback_us
        self.data = {}
        self.pending = collections.deque()
        self.started = None

    def observe(self, frame, tick):
        if self.started is None:
            self.started = tick
        # FIFO expiry assumes RX descriptor time is nondecreasing in this stream.
        while self.pending and tick - self.pending[0][0] > self.lookback_us:
            old, key = self.pending.popleft()
            if self.data.get(key) == old:
                self.data.pop(key, None)
        key = qos_key(frame)
        if key:
            self.data[key] = tick
            self.pending.append((tick, key))
            return None
        ba = parse_control(frame)
        if not ba or "ack_sequences" not in ba:
            return None
        if tick - self.started < self.lookback_us:
            return {"status": "warming_up"}
        sender, receiver, tid = ba["ra"], ba["ta"], ba["tid"]
        acked = set(ba["ack_sequences"])
        # Only sequences within this BA's window; zeros include unsent positions.
        seen = set()
        for displacement in range(ba["bitmap_bits"]):
            seq = (ba["start_sequence"] + displacement) % 4096
            at = self.data.get((sender, receiver, tid, seq))
            if at is not None and 0 <= tick - at <= self.lookback_us:
                seen.add(seq)
        return {"status": "window", "acked": acked, "seen": seen}


def capture(dev, seconds, lookback_us, barrier):
    decode = m.decoder_for(dev)
    window = DeliveryWindow(lookback_us)
    counts, modes = collections.Counter(), collections.Counter()
    subtypes = collections.Counter()
    ba_events, beacons = collections.defaultdict(list), collections.defaultdict(list)
    origin, previous = None, None
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
        if not d or len(d.get("frame", b"")) < 2:
            continue
        if d.get("fcs_err"):
            counts["fcs_failed_frames_excluded"] += 1
            continue
        subtypes[f"0x{d['frame'][0] & 0xFC:02x}"] += 1
        if "timestamp" not in d:
            counts["frames_without_timestamp_excluded"] += 1
            continue
        frame, timestamp = d["frame"], d["timestamp"]
        if origin is None:
            origin = timestamp
        tick = delta32(timestamp, origin)
        if previous is not None and tick < previous:
            counts["backward_timestamp_frames_skipped"] += 1
            continue
        previous = tick
        counts["frames"] += 1
        modes[d.get("phy", {}).get("mode_name", "unknown")] += 1
        (fc,) = struct.unpack_from("<H", frame)
        if fc & 0xFC in (0x80, 0x50):
            beacons[hashlib.sha256(frame).digest()].append((timestamp, at))
        if qos_key(frame):
            counts["qos_data_frames"] += 1
            counts["qos_retry_flag_frames"] += bool(fc & 0x800)
        event = window.observe(frame, tick)
        if event is None:
            continue
        if event["status"] == "warming_up":
            counts["ba_during_warmup"] += 1
            continue
        acked, seen = event["acked"], event["seen"]
        counts["blockack_windows"] += 1
        counts["ack_bits_with_recent_data_seen"] += len(acked & seen)
        counts["ack_bits_without_recent_data_seen"] += len(acked - seen)
        counts["recent_data_seen_but_bit_zero"] += len(seen - acked)
        ba_events[hashlib.sha256(frame).digest()].append((timestamp, acked, seen))
    return (
        {
            "chip": dev.CHIP,
            "elapsed_s": round(time.monotonic() - start, 3),
            "counts": dict(counts),
            "phy_frames": dict(modes),
            "frame_subtypes_before_timestamp_filter": dict(subtypes),
        },
        beacons,
        ba_events,
    )


def compare(captures):
    first, second = captures[0][1], captures[1][1]
    keys = [k for k in first.keys() & second.keys() if len(first[k]) == len(second[k]) == 1]
    pairs = sorted(
        [(first[k][0][0], second[k][0][0], first[k][0][1]) for k in keys], key=lambda p: p[2]
    )
    quality = fit_clock(pairs)
    result = {"clock": quality}
    if quality["status"] != "fit" or quality["all_fit"]["p95_us_if_1mhz"] > 20:
        return result | {"comparison": "no_usable_clock_fit"}
    x = [delta32(p[0], pairs[0][0]) for p in pairs]
    y = [delta32(p[1], pairs[0][1]) for p in pairs]
    mx, my = statistics.mean(x), statistics.mean(y)
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / sum(
        (a - mx) ** 2 for a in x
    )
    intercept = my - slope * mx
    a, b = captures[0][2], captures[1][2]
    counts = collections.Counter()
    counts["common_ba_fingerprints"] = len(a.keys() & b.keys())
    for key in a.keys() & b.keys():
        if len(a[key]) != 1 or len(b[key]) != 1:
            counts["repeated_ba_fingerprints_excluded"] += 1
            continue
        ta, acked, seen_a = a[key][0]
        tb, _, seen_b = b[key][0]
        residual = delta32(tb, pairs[0][1]) - slope * delta32(ta, pairs[0][0]) - intercept
        if abs(residual) > 100:
            counts["ba_outside_100us_gate"] += 1
            continue
        counts["shared_ba_events"] += 1
        counts["ack_bits_data_seen_by_both"] += len(acked & seen_a & seen_b)
        counts["ack_bits_data_seen_only_mt7921"] += len((acked & seen_a) - seen_b)
        counts["ack_bits_data_seen_only_mt7925"] += len((acked & seen_b) - seen_a)
        counts["ack_bits_data_seen_by_neither_recently"] += len(acked - seen_a - seen_b)
    return result | {
        "comparison": "sequence_window_opportunities_not_unique_packets",
        "counts": dict(counts),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=parse_target)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--lookback-ms", type=float, default=100)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 60 or not 10 <= args.lookback_ms <= 500:
        parser.error("seconds must be 5..60 and lookback 10..500 ms")
    if args.target[3] > 80:
        parser.error("paired same-width test is limited to MT7961's 80 MHz")
    result = {
        "tool": "delivery_evidence",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "target": args.target,
        "lookback_ms": args.lookback_ms,
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
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [
                pool.submit(capture, dev, args.seconds, args.lookback_ms * 1000, barrier)
                for dev in radios
            ]
            barrier.wait(timeout=15)
            captures = [j.result(timeout=args.seconds + 10) for j in jobs]
        result["radios"] = [c[0] for c in captures]
        result["paired"] = compare(captures)
        result["register_alive_after"] = [d.alive() for d in radios]
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 1 if any(r["counts"].get("usb_errors") for r in result["radios"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
