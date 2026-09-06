#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded CSI/session coexistence gate, not a public stream API.

MT7925 channel36/20MHz receive only. STOP/select/START, receiver/filter controls
after START, host-side rejection of queued preconfiguration/unselected reports,
periodic named counters and temperature, STOP/drain, restart and final reload.
Never serialize transmitter identifiers, coefficients, raw replies or frame data.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m
from mt76_csi import CsiAction, build_csi_request, parse_beacon_csi, parse_csi_ack
from mt76_measurements import Counter, read_counters, read_thermal
from mt76_session import AcquisitionSession


def send(dev, action, **kwargs):
    payload = build_csi_request(dev.CHIP, action, **kwargs)
    if dev.uni_option(0x4A) != 7:
        raise ValueError("CSI controls require SET_ACK option7")
    raw = dev.mcu_uni(0x4A, payload, timeout=1000)
    if parse_csi_ack(dev.CHIP, raw, dev.msg_seq):
        raise RuntimeError("CSI command rejected")


class Window:
    """Transient private selection state; export counts only."""

    def __init__(self, selected=None, receivers=2, cutoff_ns=0, stopped=False):
        self.selected, self.receivers, self.cutoff_ns = selected, receivers, cutoff_ns
        self.stopped = stopped
        self.counts = collections.Counter()
        self.beacons = collections.Counter()
        self.sources = collections.Counter()
        self.iq_seen = set()
        self.rx_indices = collections.Counter()

    def frame(self, decoded):
        if not decoded or not decoded.get("frame"):
            return
        self.counts["normal_frames"] += 1
        if decoded.get("fcs_err"):
            self.counts["fcs_errors"] += 1
            return
        frame = decoded["frame"]
        if len(frame) >= 36 and frame[0] == 0x80:
            self.beacons[bytes(frame[10:16])] += 1
            self.counts["beacons"] += 1

    def event(self, packet):
        self.counts["events_consumed"] += 1
        raw = packet.raw
        if len(raw) < 44 or raw[36] != 0x4A:
            self.counts["other_events"] += 1
            return
        try:
            report = parse_beacon_csi("mt7925", raw)
        except ValueError:
            self.counts["invalid_or_outside_profile"] += 1
            return
        self.counts["csi_reports"] += 1
        if self.stopped:
            self.counts["reports_after_stop"] += 1
            return
        if packet.received_ns < self.cutoff_ns:
            self.counts["preconfiguration_discarded"] += 1
            return
        if self.selected is not None and report.transmitter != self.selected:
            self.counts["unselected_discarded"] += 1
            return
        if report.rx_index >= self.receivers:
            self.counts["receiver_discarded"] += 1
            return
        self.counts["accepted_reports"] += 1
        self.sources[report.transmitter] += 1
        self.rx_indices[report.rx_index] += 1
        self.iq_seen.add((report.i, report.q))

    def export(self):
        return {
            "counts": dict(self.counts),
            "accepted_sources": len(self.sources),
            "beacon_sources": len(self.beacons),
            "iq_distinct": len(self.iq_seen),
            "rx_indices": dict(self.rx_indices),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fw", default=os.fspath(m.firmware_dir()))
    parser.add_argument("--event-capacity", type=int, choices=(1, 8, 64), default=64)
    parser.add_argument("--stall-ms", type=int, choices=(0, 250), default=0)
    parser.add_argument(
        "--receiver-order", choices=("after-filter", "before-filter"), default="after-filter"
    )
    args = parser.parse_args(argv)
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    result = {
        "tool": "csi_session_probe",
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "event_capacity": args.event_capacity,
        "receiver_order": args.receiver_order,
        "stall_ms": args.stall_ms,
        "windows": [],
    }
    session = None
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, args.fw)
        result["firmware_sha256"] = [hashlib.sha256(image).hexdigest() for image in images]
        try:
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)
            session = AcquisitionSession(dev, event_capacity=args.event_capacity).start()
            decode = m.decoder_for(dev)

            def command(action, **kwargs):
                if stopping and action not in (CsiAction.STOP, CsiAction.REMOVE_TRANSMITTER):
                    raise InterruptedError("CSI experiment stopping")
                session.call(lambda d: send(d, action, **kwargs))

            def collect(name, window, seconds=2):
                started = time.monotonic()
                next_query = started
                while not stopping and time.monotonic() - started < seconds:
                    if session.snapshot()["state"] != "running":
                        raise RuntimeError("acquisition session failed")
                    if time.monotonic() >= next_query:
                        session.call(
                            lambda d: (
                                read_counters(d, (Counter.PRIMARY_CCA, Counter.RX_MPDU)),
                                read_thermal(d),
                            )
                        )
                        window.counts["counter_thermal_pairs"] += 1
                        next_query = time.monotonic() + 0.25
                    packet = session.read(timeout=0.005)
                    if packet is not None:
                        window.frame(decode(packet.raw))
                    for _ in range(64):
                        packet = session.read(events=True, timeout=0)
                        if packet is None:
                            break
                        window.event(packet)
                    if sum(window.counts[k] for k in ("normal_frames", "events_consumed")) > 4096:
                        window.counts["transfer_ceiling_reached"] += 1
                        break
                record = {
                    "name": name,
                    "elapsed_s": round(time.monotonic() - started, 3),
                    **window.export(),
                    "session": session.snapshot(),
                }
                result["windows"].append(record)
                print(
                    json.dumps({"event": "window", "name": name, "counts": record["counts"]}),
                    flush=True,
                )
                return window

            command(CsiAction.STOP)
            collect("stopped_baseline", Window(stopped=True), 1)
            command(CsiAction.BEACON_SELECTOR)
            command(CsiAction.START)
            command(CsiAction.RECEIVER_COUNT, receivers=2)
            baseline = collect("unfiltered", Window(cutoff_ns=time.monotonic_ns()))
            eligible = baseline.sources.keys() & baseline.beacons.keys()
            if not eligible:
                result["filter_gate"] = "no common CSI/beacon source"
            elif not stopping:
                selected = max(eligible, key=baseline.sources.__getitem__)
                for cycle in range(2):
                    command(CsiAction.STOP)
                    command(CsiAction.BEACON_SELECTOR)
                    command(CsiAction.START)
                    if args.receiver_order == "before-filter":
                        command(CsiAction.RECEIVER_COUNT, receivers=1)
                    command(CsiAction.ADD_TRANSMITTER, transmitter=selected)
                    if args.receiver_order == "after-filter":
                        command(CsiAction.RECEIVER_COUNT, receivers=1)
                    cutoff = time.monotonic_ns()
                    if args.stall_ms:
                        time.sleep(
                            args.stall_ms / 1000
                        )  # Deliberate bounded consumer-overflow test.
                    collect(f"filtered_restart_{cycle}", Window(selected, 1, cutoff))
                    command(CsiAction.REMOVE_TRANSMITTER, transmitter=selected)
                    command(CsiAction.STOP)
                    collect(f"stopped_{cycle}", Window(stopped=True), 0.5)
                    if stopping:
                        break
            command(CsiAction.STOP)
            result["stopped_ack"] = True
        except InterruptedError:
            result["cancelled"] = True
        except Exception as exc:
            result["error_type"] = type(exc).__name__
        finally:
            if session is not None:
                session.stop(timeout=4)  # Never reload while the worker still owns USB.
                result["session"] = session.snapshot()
            try:
                send(dev, CsiAction.STOP)
                result["cleanup_stop_ack"] = True
            except Exception as exc:
                result["cleanup_stop_error_type"] = type(exc).__name__
            dev.bringup(*images, log=lambda *_: None)
            result["cleanup_reload_alive"] = dev.alive()
    result["exit_code"] = (
        1
        if "error_type" in result
        or "cleanup_stop_error_type" in result
        or not result["cleanup_reload_alive"]
        else 130
        if stopping
        else 2
        if "filter_gate" in result
        else 0
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
