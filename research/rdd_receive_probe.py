#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded MT7925 receiver-only radar START after successful STOP control.

Source-defined UNI19/tag0, ctrl1/index0/rxsel0/region1(FCC). Normal ch36/20.
This selects the firmware detector profile, not a TX country/power setting.
No emulation, START_TXQ, threshold writes, DFS-channel TX or pulse generation.
At most three one-second/512-transfer windows, then STOP and full normal reload.
Only event metadata, no raw radar payload or ambient identities, is exported.
"""

import argparse
import contextlib
import datetime
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m
from research.mt7925_rdd_fields import snapshot
from research.rdd_stop_probe import collect, stop


def start_request():
    return struct.pack("<4xHHBBBB4x", 0, 12, 1, 0, 0, 1)


def state(dev):
    """Traced host enable at GP+121776 and prerequisite byte at GP+62669."""
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925-only traced RDD state")
    host = dev.rr(0x022303B0)
    gate = dev.rr(0x02221CCC)
    if any(type(word) is not int or not 0 <= word < 0xFFFFFFFF for word in (host, gate)):
        raise ValueError("invalid RDD state read")
    return {"host_enabled_byte": host & 255, "prerequisite_byte_02221ccd": (gate >> 8) & 255}


def start(dev, stop_result):
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(0x19, False) != 7:
        raise ValueError("pinned MT7925 SET ACK7 only")
    if not any(row.get("command_result_status") == 0 for row in stop_result["events"]):
        raise ValueError("successful STOP control required before START")
    dev.mcu_uni(0x19, start_request(), query=False, wait=False, timeout=1000)
    return collect(dev)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-passive-detector", action="store_true")
    parser.add_argument(
        "--state", action="store_true", help="read traced enable/prerequisite bytes"
    )
    parser.add_argument(
        "--registers", action="store_true", help="read five ROM-mapped RDD registers"
    )
    args = parser.parse_args()
    if not args.enable_passive_detector:
        parser.error("explicit receiver-only detector opt-in required")
    out = {
        "tool": "rdd_receive_probe",
        "chip": "mt7925",
        "channel": 36,
        "detector_region_raw": 1,
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": [],
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        try:
            boot()
            if args.state:
                out["state_before"] = state(dev)
            if args.registers:
                out["hardware_before"] = snapshot(dev)
            initial = stop(dev)
            out["initial_stop"] = initial
            if args.state:
                out["state_after_initial_stop"] = state(dev)
            if args.registers:
                out["hardware_after_initial_stop"] = snapshot(dev)
            out["rows"].append(start(dev, initial))
            if args.state:
                out["state_after_start"] = state(dev)
            if args.registers:
                out["hardware_after_start"] = snapshot(dev)
            for _ in range(2):
                out["rows"].append(collect(dev))
                if args.registers:
                    out["rows"][-1]["hardware_after"] = snapshot(dev)
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                out["final_stop"] = stop(dev)
                if args.state:
                    out["state_after_final_stop"] = state(dev)
                if args.registers:
                    out["hardware_after_final_stop"] = snapshot(dev)
            except Exception as exc:
                out["stop_error_type"] = type(exc).__name__
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
                if args.state:
                    out["state_after_reload"] = state(dev)
                if args.registers:
                    out["hardware_after_reload"] = snapshot(dev)
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out or not out.get("alive_after") or not out.get("cleanup_reload_alive")
    )


if __name__ == "__main__":
    raise SystemExit(main())
