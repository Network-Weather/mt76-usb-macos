#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Does shared-beacon clock calibration survive a radio's channel excursion?

Passive only. Both radios observe the same target, one tunes away for two seconds
and returns, then both observe again without reboot. Train on the pre-excursion
pairs and predict post-excursion pairs. Frame hashes/identifiers stay in memory.
"""

import argparse
import concurrent.futures
import contextlib
import datetime
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m
from research.dual_radio_probe import capture, fit_clock
from research.mt7925_mib_characterize import parse_target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=parse_target)
    parser.add_argument("excursion", type=parse_target)
    parser.add_argument("--radio", choices=("mt7921", "mt7925"), default="mt7921")
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 30:
        parser.error("seconds per phase must be 5..30")
    result = {
        "tool": "clock_retune_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "target": args.target,
        "excursion": args.excursion,
        "retuned_radio": args.radio,
        "phases": [],
        "firmware_sha256": {},
    }
    all_pairs = []
    split = 0
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
        for phase in ("before", "after"):
            if phase == "after":
                moving = next(dev for dev in radios if args.radio == dev.CHIP)
                moving.tune(*args.excursion)
                # Drain while away. Nothing is retained; no decoder assumes a stale channel.
                barrier = threading.Barrier(1)
                capture(moving, 2, barrier)
                moving.tune(*args.target)
                time.sleep(0.2)
            barrier = threading.Barrier(3)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(capture, dev, args.seconds, barrier) for dev in radios]
                barrier.wait(timeout=15)
                captures = [job.result(timeout=args.seconds + 10) for job in jobs]
            a, b = captures[0][1], captures[1][1]
            keys = [k for k in a.keys() & b.keys() if len(a[k]) == len(b[k]) == 1]
            pairs = [(a[k][0][0], b[k][0][0], a[k][0][1]) for k in keys]
            all_pairs.extend(pairs)
            if phase == "before":
                split = len(pairs)
            record = {"phase": phase, "clock": fit_clock(pairs), "radios": [c[0] for c in captures]}
            result["phases"].append(record)
            print(json.dumps({"phase": phase, "pairs": len(pairs)}), file=sys.stderr, flush=True)
        result["across_retune"] = fit_clock(all_pairs, split_index=split)
        result["register_alive_after"] = [dev.alive() for dev in radios]
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return (
        1
        if any(r["packets"].get("usb_errors") for p in result["phases"] for r in p["radios"])
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
