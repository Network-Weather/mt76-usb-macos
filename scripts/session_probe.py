#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Passive continuous-session qualification. Emits redacted NDJSON, never frames.

Two 20-MHz targets per selected band, optional periodic retunes and CCA queries.
No transmit path, SSIDs, MACs, raw replies, or packet output. Run one process per radio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m
from mt76_measurements import Counter as NamedCounter
from mt76_measurements import ThermalAction, counter_descriptors, read_counters, read_thermal
from mt76_session import AcquisitionSession, SessionError


def cca(dev):
    sample = read_counters(dev, (NamedCounter.PRIMARY_CCA,))
    return {
        "value": sample.readings[0].raw,
        "opened_ns": sample.opened_us * 1000,
        "closed_ns": sample.closed_us * 1000,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb-id", required=True, choices=("0e8d:7961", "0846:9072"))
    parser.add_argument("--fw", default=os.fspath(m.firmware_dir()))
    parser.add_argument("--band", choices=("2.4GHz", "5GHz"), default="5GHz")
    parser.add_argument(
        "--thermal",
        action="store_true",
        help="query temperature and supported raw ADC alongside MIB",
    )
    parser.add_argument(
        "--named-counters", action="store_true", help="sample/export the raw named profile"
    )
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--hop-seconds", type=int, default=5, help="0 locks the first channel")
    parser.add_argument("--mib-seconds", type=int, default=1, help="0 disables queries")
    parser.add_argument("--frame-capacity", type=int, default=256)
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 14400 or not 0 <= args.hop_seconds <= 3600:
        parser.error("duration 1..14400 and hop interval 0..3600 required")
    if not 0 <= args.mib_seconds <= 3600 or not 1 <= args.frame_capacity <= 65536:
        parser.error("MIB interval 0..3600 and frame capacity 1..65536 required")
    if args.thermal and not args.mib_seconds:
        parser.error("--thermal requires a positive --mib-seconds interval")
    stopping = False

    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    result = {
        "event": "summary",
        "tool": "python_session_probe",
        "usb_id": args.usb_id,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "requested_seconds": args.seconds,
        "hop_seconds": args.hop_seconds,
        "mib_seconds": args.mib_seconds,
        "requested_band": args.band,
    }
    counts = Counter()
    session = None
    started = None
    exit_code = 1
    with m.open_device(args.usb_id) as dev:
        patch, ram = m.load_firmware(dev.CHIP, args.fw)
        result["firmware_sha256"] = {
            "patch": hashlib.sha256(patch).hexdigest(),
            "ram": hashlib.sha256(ram).hexdigest(),
        }
        dev.bringup(patch, ram, log=lambda *_: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        targets = (1, 11) if args.band == "2.4GHz" else (36, 149)
        dev.tune(args.band, targets[0])
        legacy_drops_before = dev.mcu_wait_dropped_frames
        decode = m.decoder_for(dev)
        current = targets[0]

        def consume(packet):
            counts["packets_consumed"] += 1
            decoded = decode(packet.raw)
            if not decoded or not decoded.get("frame"):
                counts["undecoded"] += 1
                return
            counts["decoded_frames"] += 1
            counts["timestamp_frames"] += int("timestamp" in decoded)
            counts["transition_frames"] += int(packet.transitioning)
            counts["off_requested_channel"] += int(
                decoded.get("band") != args.band or decoded.get("channel") != current
            )
            counts["max_delivery_latency_us"] = max(
                counts["max_delivery_latency_us"],
                (time.monotonic_ns() - packet.received_ns) // 1000,
            )

        try:
            session = AcquisitionSession(dev, frame_capacity=args.frame_capacity).start()
            started = time.monotonic()
            end = started + args.seconds
            next_hop = started + args.hop_seconds if args.hop_seconds else float("inf")
            next_mib = started + args.mib_seconds if args.mib_seconds else float("inf")
            heartbeat = started + 30
            print(json.dumps({"event": "ready", "usb_id": args.usb_id}), flush=True)
            while not stopping and time.monotonic() < end:
                packet = session.read(timeout=0.05)
                if packet:
                    consume(packet)
                while session.read(timeout=0, events=True) is not None:
                    counts["events_consumed"] += 1
                if session.snapshot()["state"] != "running":
                    raise SessionError("worker stopped during capture")
                now = time.monotonic()
                if now >= next_mib:
                    if args.named_counters:
                        sample = session.call(
                            lambda d: read_counters(
                                d, (c.counter for c in counter_descriptors(d.CHIP))
                            )
                        )
                        snapshot = session.snapshot()
                        print(
                            json.dumps(
                                {
                                    "event": "counters",
                                    "usb_id": args.usb_id,
                                    "epoch_ns": snapshot["epoch_ns"],
                                    "channel_generation": snapshot["channel_generation"],
                                    "requested_control": current,
                                    "requested_band": args.band,
                                    "opened_us": sample.opened_us,
                                    "closed_us": sample.closed_us,
                                    "values": {r.descriptor.name: r.raw for r in sample.readings},
                                }
                            ),
                            flush=True,
                        )
                        latency = sample.closed_us - sample.opened_us
                    else:
                        sample = session.call(cca)
                        latency = (sample["closed_ns"] - sample["opened_ns"]) // 1000
                    counts["mib_queries"] += 1
                    counts["max_mib_latency_us"] = max(
                        counts["max_mib_latency_us"],
                        latency,
                    )
                    if args.thermal:
                        actions = (ThermalAction.TEMPERATURE,)
                        if dev.CHIP == m.CHIP_MT7925:
                            actions = (
                                ThermalAction.TEMPERATURE,
                                ThermalAction.RAW_ADC,
                                ThermalAction.TEMPERATURE,
                            )
                        for action in actions:
                            reading = session.call(lambda d, a=action: read_thermal(d, a))
                            counts["thermal_queries"] += 1
                            print(
                                json.dumps(
                                    {
                                        "event": "thermal",
                                        "usb_id": args.usb_id,
                                        "epoch_ns": session.snapshot()["epoch_ns"],
                                        "action": int(action),
                                        "raw": reading.raw,
                                        "reported_temperature_c": reading.reported_temperature_c,
                                        "opened_us": reading.opened_us,
                                        "closed_us": reading.closed_us,
                                    }
                                ),
                                flush=True,
                            )
                    next_mib = time.monotonic() + args.mib_seconds
                if now >= next_hop:
                    current = targets[1] if current == targets[0] else targets[0]
                    tune_started = time.monotonic_ns()
                    session.tune(args.band, current)
                    counts["max_retune_latency_us"] = max(
                        counts["max_retune_latency_us"],
                        (time.monotonic_ns() - tune_started) // 1000,
                    )
                    counts["retunes"] += 1
                    next_hop = time.monotonic() + args.hop_seconds
                if now >= heartbeat:
                    print(
                        json.dumps(
                            {
                                "event": "heartbeat",
                                "elapsed_seconds": round(now - started, 2),
                                "counts": dict(counts),
                                "session": session.snapshot(),
                            }
                        ),
                        flush=True,
                    )
                    heartbeat = now + 30
            exit_code = 130 if stopping else 0
        except Exception as exc:
            result["error_type"] = type(exc).__name__  # never serialize exception payload
        finally:
            if session:
                session.stop(timeout=4)
                while (packet := session.read(timeout=0)) is not None:
                    consume(packet)
                while session.read(timeout=0, events=True) is not None:
                    counts["events_consumed"] += 1
                result["session"] = session.snapshot()
            result["elapsed_seconds"] = round(time.monotonic() - started, 3) if started else None
            result["register_alive_after"] = dev.alive()
            result["counts"] = dict(counts)
            result["legacy_mcu_discarded_frames"] = (
                dev.mcu_wait_dropped_frames - legacy_drops_before
            )
            if not result["register_alive_after"]:
                exit_code = 1
            result["exit_code"] = exit_code
            print(json.dumps(result, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
