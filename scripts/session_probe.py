#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Passive continuous-session qualification. Emits redacted NDJSON, never frames.

Two measured 5 GHz/20 MHz targets, optional periodic retunes and CCA queries.
No transmit path, SSIDs, MACs, raw replies, or packet output. Run one process per radio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import struct
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m
from mt76_session import AcquisitionSession, SessionError
from research.mt7925_mib_characterize import build_request, parse_counter
from scripts.mcu_stats import parse_mt7921_value


def cca(dev):
    opened = time.monotonic_ns()
    if dev.CHIP == "mt7925":
        body = dev.reply_body(dev.mcu_uni(0x22, build_request(0, (19,)), query=True))
        value = parse_counter(body, 19)
    else:
        body = dev.reply_body(dev.mcu_cmd_word(m.MCU_EXT_CMD(0x5A), struct.pack("<IIQ", 0, 11, 0)))
        value = parse_mt7921_value(body)
    if value is None:
        raise SessionError("invalid CCA reply")
    return {"value": value, "opened_ns": opened, "closed_ns": time.monotonic_ns()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb-id", required=True, choices=("0e8d:7961", "0846:9072"))
    parser.add_argument("--fw", default=os.fspath(m.firmware_dir()))
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--hop-seconds", type=int, default=5, help="0 locks channel 36")
    parser.add_argument("--mib-seconds", type=int, default=1, help="0 disables queries")
    parser.add_argument("--frame-capacity", type=int, default=256)
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 14400 or not 0 <= args.hop_seconds <= 3600:
        parser.error("duration 1..14400 and hop interval 0..3600 required")
    if not 0 <= args.mib_seconds <= 3600 or not 1 <= args.frame_capacity <= 65536:
        parser.error("MIB interval 0..3600 and frame capacity 1..65536 required")
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
        dev.tune("5GHz", 36)
        decode = m.decoder_for(dev)
        current = 36

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
                decoded.get("band") != "5GHz" or decoded.get("channel") != current
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
                    sample = session.call(cca)
                    counts["mib_queries"] += 1
                    counts["max_mib_latency_us"] = max(
                        counts["max_mib_latency_us"],
                        (sample["closed_ns"] - sample["opened_ns"]) // 1000,
                    )
                    next_mib = time.monotonic() + args.mib_seconds
                if now >= next_hop:
                    current = 149 if current == 36 else 36
                    tune_started = time.monotonic_ns()
                    session.tune("5GHz", current)
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
            result["legacy_mcu_discarded_frames"] = dev.mcu_wait_dropped_frames
            if not result["register_alive_after"]:
                exit_code = 1
            result["exit_code"] = exit_code
            print(json.dumps(result, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
