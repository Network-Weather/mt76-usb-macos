#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""SIGTERM a passive session, then qualify fresh bring-up on the same dongle.

Supervises only our own child processes. No transmit, raw packets or identifiers.
This is process cancellation, not hot-unplug or a deterministic in-flight USB abort.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.c_radio_pair import records, stop, wait_ready

ROOT = Path(__file__).resolve().parents[1]


def accepted(summary, returncode, expected):
    session = summary.get("session", summary)
    counts = session.get("counts", session)
    return bool(
        returncode == expected
        and summary.get("exit_code") == expected
        and summary.get("register_alive_after") is True
        and session.get("state") in (2, "closed")
        and not counts.get("usb_errors", 0)
        and not counts.get("malformed", 0)
        and not summary.get("legacy_mcu_discarded_frames", 0)
        and not session.get("frame_depth", 0)
        and counts.get("frames_received", 0)
        == counts.get("frames_delivered", 0) + counts.get("frames_dropped", 0)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", choices=("python", "c"), required=True)
    parser.add_argument("--usb-id", choices=("0e8d:7961", "0846:9072"), required=True)
    parser.add_argument("--fw", required=True)
    args = parser.parse_args()
    executable = (
        [sys.executable, str(ROOT / "scripts/session_probe.py")]
        if args.implementation == "python"
        else [str(ROOT / "c/mt76_session_probe")]
    )
    common = [*executable, "--usb-id", args.usb_id, "--fw", args.fw, "--hop-seconds", "1"]
    report = {
        "tool": "session_lifecycle",
        "implementation": args.implementation,
        "usb_id": args.usb_id,
        "phases": [],
    }
    with tempfile.TemporaryDirectory(prefix="session-lifecycle-") as directory:
        for phase, seconds, expected in [("interrupt", "60", 130), ("fresh_bringup", "3", 0)]:
            path = Path(directory) / f"{phase}.jsonl"
            failure = None
            with path.open("w") as output:
                process = subprocess.Popen([*common, "--seconds", seconds], stdout=output)  # noqa: S603 -- fixed local probe, no shell
                try:
                    wait_ready(process, path)
                    if phase == "interrupt":
                        time.sleep(2.2)
                        process.terminate()
                    process.wait(timeout=15)
                except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
                    failure = type(exc).__name__
                finally:
                    stop(process)
            observed = records(path)
            summary = next((r for r in reversed(observed) if r.get("event") == "summary"), {})
            report["phases"].append(
                {
                    "phase": phase,
                    "returncode": process.returncode,
                    "error": failure,
                    "records": observed,
                    "pass": failure is None and accepted(summary, process.returncode, expected),
                }
            )
    report["pass"] = all(p["pass"] for p in report["phases"])
    print(json.dumps(report, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
