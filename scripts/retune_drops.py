#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Measure how many received frames a retune throws away. Passive receive only.

Once RX events are routed to EP4, MCU replies and 802.11 frames share one bulk
endpoint, and `mcu_wait` discards every frame it reads while hunting for its reply.
A retune is two MCU commands (channel switch, then sniffer config), so each retune
drops whatever was queued behind those two replies. This script measures that.

Method: listen on each candidate channel briefly, pick the two busiest, then alternate
between them. On each channel it reads frames for `--dwell` seconds (so the device is
being drained, as a real capture would), then retunes and records how many frames the
two commands discarded. Output is one JSON document of counts only: no frames, SSIDs,
BSSIDs, client addresses, or payloads.

Usage: retune_drops.py [--retunes 10] [--dwell 2] [--candidates 2.4GHz:1,2.4GHz:6,...]
Firmware is loaded from $MT76_FW_DIR (or the older $MT7921_FW_DIR), defaulting to
<repo>/firmware; the pinned SHA-256s are checked.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = m.firmware_dir()  # $MT76_FW_DIR, then $MT7921_FW_DIR, then <repo>/firmware
CHAN_BAND = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}
DEFAULT_CANDIDATES = "2.4GHz:1,2.4GHz:6,2.4GHz:11,5GHz:36,5GHz:44,5GHz:149,5GHz:157"
# How long the census listens on each candidate. Long enough for several beacon
# intervals (102.4 ms nominal) from every AP on the channel.
CENSUS_SECONDS = 1.0
# Per-read USB timeout while draining. Short so a quiet channel does not stall the loop.
READ_TIMEOUT_MS = 250


def parse_candidates(text: str) -> list[tuple[str, int]]:
    out = []
    for item in text.split(","):
        band, _, chan = item.strip().partition(":")
        if band not in CHAN_BAND or not chan.isdigit():
            raise argparse.ArgumentTypeError(f"bad candidate {item!r}; want BAND:CHANNEL")
        out.append((band, int(chan)))
    return out


def retune(dev: m.Mt7921uDevice, band: str, chan: int) -> dict:
    """Retune and return what the two MCU commands discarded, with wall time."""
    dropped0, stale0 = dev.mcu_wait_dropped_frames, dev.mcu_wait_stale_events
    other0 = dev.mcu_wait_other_packets
    t0 = time.monotonic()
    dev.set_chan_info(control_ch=chan, center_ch=chan, bw=m.CMD_CBW_20MHZ, band=CHAN_BAND[band])
    t1 = time.monotonic()
    dev.config_sniffer(control_ch=chan, center_ch=chan, band_name=band, bw=m.SNIFFER_BW_20)
    t2 = time.monotonic()
    return {
        "to": f"{band}:{chan}",
        "dropped_frames": dev.mcu_wait_dropped_frames - dropped0,
        "stale_events": dev.mcu_wait_stale_events - stale0,
        "other_packets": dev.mcu_wait_other_packets - other0,
        "chan_switch_ms": round((t1 - t0) * 1000, 1),
        "sniffer_cfg_ms": round((t2 - t1) * 1000, 1),
    }


def drain(dev: m.Mt7921uDevice, seconds: float) -> dict:
    """Read frames for `seconds`, the way a capture loop would, and count them."""
    frames = timeouts = usb_errors = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
        except usb.core.USBTimeoutError:
            timeouts += 1  # a quiet channel, not a fault
            continue
        except usb.core.USBError as exc:
            usb_errors += 1  # a real transport failure; the sample is incomplete
            print(f"usb error during drain: {exc}", file=sys.stderr)
            continue
        decoded = rxd.decode(raw)
        if decoded and decoded.get("frame"):
            frames += 1
    return {"frames": frames, "timeouts": timeouts, "usb_errors": usb_errors, "seconds": seconds}


def summary(values: list[int]) -> dict:
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "max": ordered[-1],
        "total": sum(ordered),
        "values": values,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--retunes", type=int, default=10, help="number of retunes to measure")
    parser.add_argument(
        "--dwell", type=float, default=2.0, help="seconds to drain before each retune"
    )
    parser.add_argument(
        "--candidates",
        type=parse_candidates,
        default=parse_candidates(DEFAULT_CANDIDATES),
        help="BAND:CHANNEL list to census; the two busiest are used",
    )
    args = parser.parse_args()
    if not 1 <= args.retunes <= 1000:
        parser.error("--retunes must be between 1 and 1000")
    if not 0.1 <= args.dwell <= 60:
        parser.error("--dwell must be between 0.1 and 60 seconds")
    if len(args.candidates) < 2:
        parser.error("need at least two candidates")

    patch, ram = m.load_firmware(m.CHIP_MT7921, FW_DIR)

    result = {
        "tool": "retune_drops",
        "mt76_usb_macos": m.__version__,
        "python": platform.python_version(),
        "macos": platform.mac_ver()[0],
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "retunes_requested": args.retunes,
        "dwell_seconds": args.dwell,
    }

    with m.Mt7921uDevice() as dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)

        census = []
        for band, chan in args.candidates:
            retune(dev, band, chan)
            counts = drain(dev, CENSUS_SECONDS)
            census.append({"channel": f"{band}:{chan}", **counts})
        census.sort(key=lambda c: c["frames"], reverse=True)
        result["census"] = census
        busiest = [c["channel"] for c in census[:2]]
        result["pair"] = busiest
        pair = [(b, int(c)) for b, c in (x.split(":") for x in busiest)]

        # Land on the first channel of the pair so the first measured retune leaves a
        # busy channel, then alternate.
        retune(dev, *pair[0])
        runs = []
        for i in range(args.retunes):
            leaving = drain(dev, args.dwell)
            target = pair[(i + 1) % 2]
            hop = retune(dev, *target)
            runs.append(
                {
                    "from_frames_in_dwell": leaving["frames"],
                    "usb_errors_in_dwell": leaving["usb_errors"],
                    **hop,
                }
            )
        result["retunes"] = runs

    result["dropped_frames"] = summary([r["dropped_frames"] for r in runs])
    result["stale_events"] = summary([r["stale_events"] for r in runs])
    result["other_packets"] = summary([r["other_packets"] for r in runs])
    result["frames_per_dwell"] = summary([r["from_frames_in_dwell"] for r in runs])
    result["usb_errors"] = sum(c["usb_errors"] for c in census) + sum(
        r["usb_errors_in_dwell"] for r in runs
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
