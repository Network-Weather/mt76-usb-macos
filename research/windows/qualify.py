#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Run bounded, single-MT7961 receive/query experiments sequentially on Windows.

Requires setup.ps1 and WinUSB interface 3. No transmit commands are included.
Logs stay in ignored build/windows/qualification; review them before publication.
An exit code of zero means the script completed, not that every query succeeded.
Stop if a failure cannot be followed by a successful firmware recovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "research/windows/boot_alias_probe.py"

# A bounded representative plan for single-radio CLI capabilities. Multi-radio
# stimulus/correlation and MT7925-specific experiments need additional hardware.
PLAN = [
    ("smoke_all", "scripts/hardware_smoke.py", ["--plan", "all", "--dwell", "0.3"]),
    (
        "widths",
        "scripts/width_probe.py",
        [
            "2.4GHz:6:6:20",
            "2.4GHz:6:8:40",
            "5GHz:36:36:20",
            "5GHz:36:38:40",
            "5GHz:36:42:80",
            "6GHz:53:53:20",
            "6GHz:53:55:40",
            "6GHz:53:55:80",
            "--seconds",
            "3",
        ],
    ),
    (
        "retunes",
        "scripts/retune_drops.py",
        ["--retunes", "20", "--dwell", "0.25", "--candidates", "2.4GHz:6,5GHz:36,6GHz:53"],
    ),
    ("sustained_rx", "scripts/firmware_boot.py", ["--rx", "60", "--channel", "5GHz:36"]),
    ("mcu_stats", "scripts/mcu_stats.py", ["--published", "--seconds", "1"]),
    (
        "mib_survey",
        "scripts/mib_survey.py",
        ["2.4GHz:6", "5GHz:36", "6GHz:53", "--seconds", "1", "--registers"],
    ),
    ("mib_offsets", "research/mib_offset_sweep.py", ["--max", "64", "--seconds", "1", "--json"]),
    (
        "vectors_g5",
        "research/rx_vector_probe.py",
        ["2.4GHz:6", "5GHz:36", "6GHz:53", "--usb-id", "0e8d:7961", "--seconds", "2", "--g5-cycle"],
    ),
    ("evm_cn", "research/evm_cn_probe.py", ["--channel", "36"]),
    ("sniffer_trace", "research/mt7961_sniffer_trace.py", []),
    ("sr_registers", "research/sr_rmac_probe.py", ["--device", "mt7961", "--channel", "36"]),
    ("sr_query", "research/legacy_spatial_reuse_query_probe.py", ["--channel", "36"]),
    ("rtt", "research/rtt_capability_probe.py", ["--chip", "mt7961"]),
    ("rx_stats_ext", "research/rx_stat_query.py", ["--usb-id", "0e8d:7961"]),
    (
        "rxv_report",
        "research/rxv_report_probe.py",
        ["--chip", "mt7961", "--enable-reporting", "--both-endpoints"],
    ),
    ("rdd_stop", "research/rdd_stop_probe.py", ["--chip", "mt7961"]),
    (
        "legacy_ics_24",
        "research/legacy_ics_probe.py",
        [
            "--activate-legacy-rmac-ics",
            "--match-rxd-in-memory",
            "--enable-group5",
            "--channel",
            "6",
        ],
    ),
    (
        "legacy_ics_5",
        "research/legacy_ics_probe.py",
        ["--activate-legacy-rmac-ics", "--match-rxd-in-memory", "--channel", "36"],
    ),
    (
        "histogram",
        "research/legacy_noise_hist_probe.py",
        ["--enable-histogram", "--cca-crosscheck", "--channel", "36"],
    ),
    ("ipi_read", "research/ipi_probe.py", ["--seconds", "1"]),
    ("ipi_hist", "research/ipi_hist_cmd.py", ["--seconds", "1"]),
    ("mcu_commands", "research/mcu_command_probe.py", ["--json"]),
    ("station_normal", "research/station_testmode_probe.py", ["--chip", "mt7961"]),
    ("station_rf", "research/station_testmode_probe.py", ["--chip", "mt7961", "--test-mode"]),
    ("legacy_rx_stats", "research/legacy_rx_stats_probe.py", []),
    ("signal_fields", "research/signal_field_crosscheck_probe.py", []),
    ("cfo", "research/cfo_crosscheck_probe.py", []),
    ("phy_stats", "research/phy_stats_probe.py", ["--registers"]),
    ("ipi_compact", "research/ipi_compact_probe.py", ["--registers"]),
    ("ipi_compact_rf", "research/ipi_compact_probe.py", ["--rf-rx", "--registers"]),
    ("ipi_register", "research/ipi_register_probe.py", ["--direct-init"]),
    ("ipi_register_rf", "research/ipi_register_probe.py", ["--direct-init", "--rf-rx"]),
    (
        "rdd_state",
        "research/legacy_rdd_state_probe.py",
        ["--enable-passive-detector", "--registers"],
    ),
    (
        "csi",
        "research/csi_control_probe.py",
        ["--chip", "mt7961"],
    ),
    ("icap_status", "research/icap_status_probe.py", ["--mode", "2"]),
    (
        "icap_capture",
        "research/icap_capture_probe.py",
        ["--samples", "64", "--prepare-rx", "--retrieve", "--registers"],
    ),
    ("final_rx", "scripts/firmware_boot.py", ["--rx", "3", "--channel", "2.4GHz:6"]),
]


def run(name, script, arguments, directory):
    command = [sys.executable, str(WRAPPER), "script", script, *arguments]
    stdout = directory / f"{name}.stdout.txt"
    stderr = directory / f"{name}.stderr.txt"
    started = time.monotonic()
    with stdout.open("wb") as output, stderr.open("wb") as errors:
        try:
            result = subprocess.run(  # noqa: S603 -- fixed local interpreter and probe plan
                command, cwd=ROOT, stdout=output, stderr=errors, timeout=180, check=False
            )
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    return {
        "name": name,
        "script": script,
        "arguments": arguments,
        "exit_code": code,
        "seconds": round(time.monotonic() - started, 3),
        "stdout_sha256": hashlib.sha256(stdout.read_bytes()).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", choices=[row[0] for row in PLAN], default=PLAN[0][0])
    parser.add_argument("--stop", choices=[row[0] for row in PLAN], default=PLAN[-1][0])
    args = parser.parse_args()
    os.environ["PYTHONUTF8"] = "1"
    os.environ["MT76_USB_ID"] = "0e8d:7961"
    directory = ROOT / "build/windows/qualification" / time.strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "runs.json"
    rows = json.loads(report.read_text(encoding="utf-8")) if report.exists() else []
    names = [row[0] for row in PLAN]
    for name, script, arguments in PLAN[names.index(args.start) : names.index(args.stop) + 1]:
        print(f"START {name}", flush=True)
        result = run(name, script, arguments, directory)
        rows.append(result)
        report.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(f"DONE {name}: exit={result['exit_code']} seconds={result['seconds']}", flush=True)
        if result["exit_code"] != 0:
            recovery = run(f"{name}_recovery", "scripts/firmware_boot.py", ["--rx", "1"], directory)
            rows.append(recovery)
            report.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
            print(f"RECOVERY {name}: exit={recovery['exit_code']}", flush=True)
            if recovery["exit_code"] != 0:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
