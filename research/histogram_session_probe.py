#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded passive histogram/session gate on either pinned dongle.

Resets shared histogram history, which cannot be restored. One radio owner,
three reset-separated windows, normal RX and named counter/thermal queries.
MT7925 uses the firmware one-shot event; MT7921 uses its traced host-timed bank.
No CSI, TX, arbitrary registers, calibration, identities or captured bytes.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import signal
import struct
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m
from mt76_histogram import parse_legacy_histogram
from mt76_histogram_acquisition import HistogramGuard
from mt76_measurements import Counter, read_counters, read_thermal
from mt76_session import AcquisitionSession
from research import legacy_noise_hist_probe as old
from research import mt7925_noise_event_probe as new
from research import mt7925_noise_hist_probe as views


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chip", required=True, choices=("mt7921", "mt7925"))
    parser.add_argument("--fw", required=True)
    parser.add_argument("--channel", type=int, choices=(1, 6, 11, 36), default=6)
    parser.add_argument("--reset-shared-histogram", action="store_true")
    parser.add_argument("--event-capacity", type=int, choices=(1, 64), default=64)
    args = parser.parse_args(argv)
    if not args.reset_shared_histogram:
        parser.error("explicit shared-history reset acknowledgment required")
    stopping = False

    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    modern = args.chip == "mt7925"
    masks = new.MASKS if modern else old.MASKS
    result = {
        "tool": "histogram_session_probe",
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "chip": args.chip,
        "channel": args.channel,
        "event_capacity": args.event_capacity,
        "coverage_fraction": None,
        "calibrated_power": False,
        "windows": [],
    }
    session = None
    guard = None
    changed = pending = False
    saved = {}
    with m.open_device("0846:9072" if modern else "0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, args.fw)
        result["firmware_sha256"] = [hashlib.sha256(image).hexdigest() for image in images]
        try:
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel <= 11 else "5GHz", args.channel, args.channel, 20)
            if modern:
                result["code_checks"] = views.verify(dev)
                if not all(row["matches"] for row in result["code_checks"]):
                    raise RuntimeError("pinned histogram code mismatch")
            for address, mask in masks.items():
                word = dev.rr(address)
                (new.masked if modern else old.masked_value)(address, word, 0)
                saved[address] = word & mask
            # Legacy option bits can be set; neither engine may already be active.
            if any(bits for address, bits in saved.items() if address != old.OPTIONS):
                raise RuntimeError("histogram already enabled or reset asserted")
            result["saved_masks"] = {hex(a): b for a, b in saved.items()}
            session = AcquisitionSession(dev, event_capacity=args.event_capacity).start()
            decoder = m.decoder_for(dev)

            def snapshot(d):
                return {
                    "controls": {hex(a): d.rr(a) & mask for a, mask in masks.items()},
                    "banks": views.banks(d, True)
                    if modern
                    else {
                        "legacy_index0": list(
                            parse_legacy_histogram(d.CHIP, struct.pack("<11I", *old.bins(d))).bins[
                                0
                            ]
                        )
                    },
                }

            def measurement(d):
                sample = read_counters(d, (Counter.PRIMARY_CCA, Counter.RX_MPDU))
                temperature = read_thermal(d)
                return {"counters": asdict(sample), "thermal": asdict(temperature)}

            def drain(seconds, expect=False, raw_reports=None):
                counts = collections.Counter()
                reports = []
                started = time.monotonic()
                next_query = started
                queries = []
                while not stopping and time.monotonic() - started < seconds:
                    if session.snapshot()["state"] != "running":
                        raise RuntimeError("histogram session failed")
                    if time.monotonic() >= next_query:
                        queries.append(session.call(measurement))
                        next_query = time.monotonic() + 0.2
                    packet = session.read(timeout=0.005)
                    if packet:
                        decoded = decoder(packet.raw)
                        if decoded and decoded.get("frame"):
                            counts["normal_frames"] += 1
                    for _ in range(64):
                        packet = session.read(events=True, timeout=0)
                        if packet is None:
                            break
                        counts["events_consumed"] += 1
                        if len(packet.raw) >= 44 and packet.raw[36] == 0x36:
                            report = new.summarize(packet.raw)
                            report["received_ns"] = packet.received_ns
                            reports.append(report)
                            if raw_reports is not None:
                                raw_reports.append(packet.raw)
                    if expect and reports:
                        break
                    if counts["normal_frames"] + counts["events_consumed"] >= 4096:
                        raise RuntimeError("transfer ceiling reached")
                return {
                    "elapsed_s": time.monotonic() - started,
                    "counts": dict(counts),
                    "queries": queries,
                    "reports": reports,
                }

            result["baseline_before"] = session.call(snapshot)
            result["baseline"] = drain(0.25)
            result["baseline_after"] = session.call(snapshot)
            for index, duration in enumerate((0.25, 0.5, 1.0)):
                if stopping:
                    break
                row = {"index": index, "requested_host_s": None if modern else duration}
                result["windows"].append(row)
                guard = HistogramGuard(dev)
                changed = pending = True
                session.call(lambda _d, guard=guard: guard.begin())
                row["command_open_ns"] = guard.command_open_us * 1000
                row["command_closed_ns"] = guard.command_closed_us * 1000
                print(json.dumps({"event": "histogram_started", "index": index}), flush=True)
                raw_reports = []
                row["collection"] = drain(
                    2 if modern else duration, expect=modern, raw_reports=raw_reports
                )
                if stopping:
                    break
                if modern:
                    reports = row["collection"]["reports"]
                    if len(reports) != 1:
                        raise RuntimeError("missing or duplicate histogram event")
                    row["event_latency_ns"] = reports[0]["received_ns"] - row["command_open_ns"]
                sample = session.call(
                    lambda _d, guard=guard, raw=raw_reports[0] if modern else None: guard.finish(
                        raw
                    )
                )
                row["sample"] = asdict(sample)
                row["stopped"] = session.call(snapshot)
                if any(
                    bits
                    for address, bits in row["stopped"]["controls"].items()
                    if address != hex(old.OPTIONS)
                ):
                    raise RuntimeError("histogram control not stopped")
                pending = False
                row["post_stop"] = drain(0.1)
                row["stopped_repeat"] = session.call(snapshot)
                if row["stopped"] != row["stopped_repeat"]:
                    raise RuntimeError("stopped histogram changed")
                if row["post_stop"]["reports"]:
                    raise RuntimeError("unexpected late histogram event")
                if modern:
                    for name, key in (
                        ("timer_getter", "timer_index0"),
                        ("timer_index1", "timer_index1"),
                    ):
                        if row["stopped"]["banks"][name] != reports[0][key]:
                            raise RuntimeError("histogram event/bank mismatch")
                session.call(lambda _d, guard=guard: guard.restore())
                row["guard_restored"] = not guard.active
                print(
                    json.dumps(
                        {
                            "event": "histogram_complete",
                            "index": index,
                            "totals": {k: sum(v) for k, v in row["stopped"]["banks"].items()},
                            "counts": row["collection"]["counts"],
                        }
                    ),
                    flush=True,
                )
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)
        finally:
            if guard is not None:
                result["guard"] = {
                    "active": guard.active,
                    "pending": guard.pending,
                    "ready": guard.ready,
                    "needs_reload": guard.needs_reload,
                }
            if session is not None:
                session.stop(timeout=4)
                result["session"] = session.snapshot()
            if changed and not pending:
                result["restored"] = {}
                for address, bits in saved.items():
                    try:
                        (new.restore if modern else old.set_bits)(dev, address, bits)
                        result["restored"][hex(address)] = True
                    except Exception as exc:
                        result["restored"][hex(address)] = type(exc).__name__
            elif changed:
                result["restore_policy"] = (
                    "pending acquisition: full reload, no timer-racing masked restore"
                )
            dev.bringup(*images, log=lambda *_: None)
            result["cleanup_reload_alive"] = dev.alive()
    result["exit_code"] = (
        1
        if "error_type" in result
        or not result["cleanup_reload_alive"]
        or any(v is not True for v in result.get("restored", {}).values())
        else 130
        if stopping
        else 0
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
