#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Exercise single-MT7961 portions of multi-radio research without inventing peer evidence.

Use through boot_alias_probe.py script. Default: temperature, efuse length only,
LPON/TSF snapshots, power/noise queries, and reversible normal-mode PHY counters.
Explicit TX option submits three synthetic wildcard probes on channel 6 only;
TX status is firmware evidence, never proof of independent over-air reception.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import usb.core

import mt7921u as m
from research import lpon_clock, noise_average_probe, tsf_snapshot, txpower_info_probe
from research.dual_radio_probe import tx_status_records
from research.normal_phy_counter_probe import CONTROL, MASK, control_value
from research.phy_stats_probe import hardware_snapshot


def dwell(dev, seconds):
    counts = collections.Counter()
    statuses = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            raw = bytes(dev.rx_read(timeout=100))
        except usb.core.USBTimeoutError:
            counts["timeouts"] += 1
            continue
        counts["transfers"] += 1
        if len(raw) >= 4 and (int.from_bytes(raw[:4], "little") >> 27) & 31 == 0:
            statuses.extend(tx_status_records(raw))
        decoded = m.decoder_for(dev)(raw)
        if decoded and decoded.get("frame"):
            counts["frames"] += 1
    return {"counts": dict(counts), "tx_status": statuses}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    out = {"tool": "windows_single_radio", "independent_receiver": False, "queries": []}
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP)

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        original = None
        try:
            boot()
            out["temperature_c"] = dev.get_temperature()
            valid, data = dev.read_efuse(0)
            out["efuse"] = {"valid": valid, "bytes": len(data) if data else 0}
            out["clocks"] = []
            for _ in range(3):
                out["clocks"].append(
                    {"lpon": lpon_clock.read_counter(dev), "tsf": tsf_snapshot.snapshot(dev)}
                )
                time.sleep(0.1)
            for band, channel in (("2.4GHz", 6), ("5GHz", 36), ("6GHz", 53)):
                dev.tune(band, channel, channel, 20)
                row = {"band": band, "channel": channel}
                out["queries"].append(row)
                for name, query in (
                    ("noise", noise_average_probe.query),
                    ("power", txpower_info_probe.query),
                ):
                    try:
                        row[name] = query(dev)
                    except (RuntimeError, ValueError, usb.core.USBError) as exc:
                        row[name] = {"error": str(exc)}
            dev.tune("2.4GHz", 6, 6, 20)
            original = dev.rr(CONTROL)
            out["counter_phases"] = []
            for phase in ("baseline", "enabled", "restored"):
                if phase == "enabled":
                    dev.wr(CONTROL, control_value(dev.rr(CONTROL), False))
                    dev.wr(CONTROL, control_value(dev.rr(CONTROL), True))
                elif phase == "restored":
                    dev.rmw(CONTROL, MASK, original & MASK)
                row = {
                    "phase": phase,
                    "bits": dev.rr(CONTROL) & MASK,
                    "before": hardware_snapshot(dev),
                }
                row["receive"] = dwell(dev, 1)
                row["after"] = hardware_snapshot(dev)
                out["counter_phases"].append(row)
            if args.acknowledge_experimental_transmit:
                source = b"\x02NW" + os.urandom(3)
                out["submitted"] = 0
                for seq in range(3):
                    dev.inject(
                        m.build_probe_request(source, seq=seq), dev.ep_out_ac_be, seq=seq, pid=3
                    )
                    out["submitted"] += 1
                    time.sleep(0.1)
                out["after_tx"] = dwell(dev, 2)
        except Exception as exc:
            out["error"] = str(exc)
        finally:
            if original is not None:
                try:
                    dev.rmw(CONTROL, MASK, original & MASK)
                    out["counter_bits_restored"] = dev.rr(CONTROL) & MASK == original & MASK
                except Exception as exc:
                    out["restore_error"] = str(exc)
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
                out["cleanup_rx"] = dwell(dev, 1)
            except Exception as exc:
                out["cleanup_error"] = str(exc)
    print(json.dumps(out, indent=2))
    return int("error" in out or "restore_error" in out or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
