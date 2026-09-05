#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Qualify the native C transmitter against the other native C receiver.

Both radios run C; Python only supervises processes and records redacted NDJSON.
No frames or network identifiers are stored. Requires explicit TX acknowledgement.
"""

import argparse
import datetime
import json
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS = ("0e8d:7961", "0846:9072")


def stop(process):
    if process.poll() is None:
        process.terminate()  # SIGTERM lets the C CLI restore/reload firmware.
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def records(path):
    lines = path.read_text().splitlines()
    return [json.loads(line) for line in lines if line.startswith("{") and line.endswith("}")]


def wait_ready(process, path):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if any(r.get("event") == "ready" for r in records(path)):
            return
        if process.poll() is not None:
            raise RuntimeError("receiver exited before ready")
        time.sleep(0.05)
    raise RuntimeError("receiver ready timeout")


def run_pair(args, power):
    receiver = IDS[1 - IDS.index(args.transmitter)]
    common = [
        str(ROOT / "c/mt76_radio_probe"),
        "--fw",
        str(args.fw.resolve()),
        "--band",
        "5GHz",
        "--channel",
        str(args.channel),
        "--rate",
        args.rate,
    ]
    with tempfile.TemporaryDirectory(prefix="c-radio-pair-") as temp:
        rx_path, tx_path = Path(temp) / "rx.jsonl", Path(temp) / "tx.jsonl"
        with rx_path.open("w") as rx_file, tx_path.open("w") as tx_file:
            rx_cmd = [*common, "--usb-id", receiver, "--seconds", "12"]
            tx_cmd = [
                *common,
                "--usb-id",
                args.transmitter,
                "--seconds",
                "6",
                "--transmit",
                str(args.count),
                "--power-code",
                str(power),
                "--acknowledge-experimental-transmit",
            ]
            rx = subprocess.Popen(rx_cmd, stdout=rx_file)  # noqa: S603 -- fixed executable, no shell
            tx = None
            try:
                wait_ready(rx, rx_path)
                tx = subprocess.Popen(tx_cmd, stdout=tx_file)  # noqa: S603 -- fixed executable, no shell
                tx.wait(timeout=35)
                rx.wait(timeout=25)
            finally:
                if tx is not None:
                    stop(tx)
                stop(rx)
        rr, tr = records(rx_path), records(tx_path)
        rd = next((r for r in rr if r.get("event") == "dwell"), {})
        td = next((r for r in tr if r.get("event") == "dwell"), {})
        rc = next((r for r in rr if r.get("event") == "cleanup"), {})
        tc = next((r for r in tr if r.get("event") == "cleanup"), {})
        passed = (
            rx.returncode == 0
            and tx is not None
            and tx.returncode == 0
            and td.get("submitted") == args.count
            and rd.get("synthetic_unique") == args.count
            and rd.get("synthetic_rate_matches") == rd.get("synthetic_exact")
            and rc.get("alive_before_cleanup")
            and tc.get("alive_before_cleanup")
            and tc.get("firmware_reloaded")
        )
        return {"power_code": power, "pass": bool(passed), "receiver": rr, "transmitter": tr}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transmitter", choices=IDS, required=True)
    parser.add_argument("--fw", type=Path, required=True)
    parser.add_argument("--channel", type=int, choices=(36, 149), default=36)
    parser.add_argument("--rate", choices=("ofdm6", "ofdm54"), default="ofdm6")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--powers", default="0,-8,0,-16,0")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit experimental transmit acknowledgement required")
    if not 1 <= args.count <= 60:
        parser.error("count must be 1..60")
    try:
        powers = [int(p) for p in args.powers.split(",")]
    except ValueError:
        parser.error("powers must be comma-separated integer codes")
    allowed = (0, -8, -16, -32) if args.transmitter == IDS[1] else (0, -8, -16)
    if not powers or len(powers) > 9 or any(p not in allowed for p in powers):
        parser.error("unsupported power code or more than nine phases")
    if args.transmitter == IDS[0] and args.rate != "ofdm6":
        parser.error("MT7921 OFDM54 is outside measured scope")
    report = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tool": "c_radio_pair",
        "transmitter": args.transmitter,
        "channel": args.channel,
        "rate": args.rate,
        "count": args.count,
        "runs": [],
    }
    for power in powers:
        run = run_pair(args, power)
        report["runs"].append(run)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "power_code": power,
                    "pass": run["pass"],
                    "receiver": next(r for r in run["receiver"] if r["event"] == "dwell"),
                }
            ),
            flush=True,
        )
        if not run["pass"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
