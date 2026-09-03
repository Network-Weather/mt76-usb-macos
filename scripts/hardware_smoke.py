#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Redacted passive MT7921U hardware smoke test.

This command never transmits and never emits frames, SSIDs, BSSIDs, client addresses,
payloads, or the USB serial number. It prints one JSON result to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = m.firmware_dir()  # $MT76_FW_DIR, then $MT7921_FW_DIR, then <repo>/firmware
CHIP = m.CHIP_MT7921  # the chip this smoke test drives; firmware pins come from the module

CH_24 = [1, 6, 11]
CH_5 = [
    36,
    40,
    44,
    48,
    52,
    56,
    60,
    64,
    100,
    104,
    108,
    112,
    116,
    120,
    124,
    128,
    132,
    136,
    140,
    144,
    149,
    153,
    157,
    161,
    165,
]
CH_6_PSC = [5, 21, 37, 53, 69, 85, 101, 117, 133, 149, 165, 181, 197, 213, 229]

PLANS = {
    "quick": [("2.4GHz", 1), ("5GHz", 36), ("6GHz", 53)],
    "2.4": [("2.4GHz", channel) for channel in CH_24],
    "5": [("5GHz", channel) for channel in CH_5],
    "6": [("6GHz", channel) for channel in CH_6_PSC],
}
PLANS["all"] = PLANS["2.4"] + PLANS["5"] + PLANS["6"]
CHAN_BAND = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        choices=sorted(PLANS),
        default="all",
        help="channel set; 'all' covers 2.4 GHz, 5 GHz, and 6 GHz PSCs",
    )
    parser.add_argument(
        "--dwell",
        type=float,
        default=0.75,
        metavar="SECONDS",
        help="time to listen on each channel (0.05 through 10; default: 0.75)",
    )
    parser.add_argument(
        "--usb-id",
        metavar="VVVV:PPPP",
        help="adapter to use when several are attached (default: $MT76_USB_ID or the only one)",
    )
    args = parser.parse_args()
    if not 0.05 <= args.dwell <= 10:
        parser.error("--dwell must be between 0.05 and 10 seconds")
    return args


def empty_band() -> dict:
    return {
        "channels_attempted": 0,
        "channels_with_transfers": 0,
        "channels_with_frames": 0,
        "usb_transfers": 0,
        "usb_timeouts": 0,
        "usb_errors": 0,
        "decoded_frames": 0,
        "undecoded_transfers": 0,
        "frame_types": {"management": 0, "control": 0, "data": 0, "other": 0},
    }


def frame_family(frame: bytes) -> str:
    if len(frame) < 2:
        return "other"
    frame_type = (int.from_bytes(frame[:2], "little") >> 2) & 0x3
    return {0: "management", 1: "control", 2: "data"}.get(frame_type, "other")


def main() -> int:
    args = arguments()
    started = time.monotonic()
    patch_path, ram_path = m.firmware_paths(CHIP, FW_DIR)
    requested_bands = sorted({band for band, _ in PLANS[args.plan]})
    result = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "fail",
        "software": {
            "mt76_usb_macos": m.__version__,
            "python": platform.python_version(),
            "pyusb": package_version("pyusb"),
        },
        "host": {"macos": platform.mac_ver()[0], "machine": platform.machine()},
        "plan": {
            "name": args.plan,
            "dwell_seconds": args.dwell,
            "channels": len(PLANS[args.plan]),
            "requested_bands": requested_bands,
        },
        "firmware": {},
        "device": None,
        "bands": {band: empty_band() for band in requested_bands},
        "totals": {},
    }

    device_opened = False
    try:
        if not patch_path.is_file() or not ram_path.is_file():
            raise FileNotFoundError("required firmware is missing; run bash setup.sh")
        result["firmware"] = {
            "patch_sha256": sha256_file(patch_path),
            "ram_sha256": sha256_file(ram_path),
        }
        patch, ram = m.load_firmware(CHIP, FW_DIR)  # raises on a pin mismatch

        with m.Mt7921uDevice(usb_id=args.usb_id) as dev:
            device_opened = True
            result["device"] = {
                "chip": dev.layout.chip,
                "usb_id": dev.layout.usb_id,
                "wifi_interface": dev.layout.interface,
                "usb_speed_code": getattr(dev.dev, "speed", None),
            }
            dev.bringup(patch, ram, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)

            for band, channel in PLANS[args.plan]:
                counters = result["bands"][band]
                counters["channels_attempted"] += 1
                dev.set_chan_info(
                    control_ch=channel,
                    center_ch=channel,
                    bw=m.CMD_CBW_20MHZ,
                    band=CHAN_BAND[band],
                )
                dev.config_sniffer(
                    control_ch=channel,
                    center_ch=channel,
                    band_name=band,
                    bw=m.SNIFFER_BW_20,
                )
                time.sleep(0.05)
                channel_transfers = 0
                channel_frames = 0
                deadline = time.monotonic() + args.dwell
                while time.monotonic() < deadline:
                    try:
                        raw = bytes(dev.rx_read(timeout=250))
                    except usb.core.USBTimeoutError:
                        counters["usb_timeouts"] += 1
                        continue
                    except usb.core.USBError:
                        counters["usb_errors"] += 1
                        continue
                    channel_transfers += 1
                    counters["usb_transfers"] += 1
                    decoded = rxd.decode(raw)
                    frame = decoded.get("frame") if decoded is not None else None
                    if not frame:
                        counters["undecoded_transfers"] += 1
                        continue
                    channel_frames += 1
                    counters["decoded_frames"] += 1
                    counters["frame_types"][frame_family(frame)] += 1
                if channel_transfers:
                    counters["channels_with_transfers"] += 1
                if channel_frames:
                    counters["channels_with_frames"] += 1

        totals = Counter()
        for counters in result["bands"].values():
            for key in (
                "usb_transfers",
                "usb_timeouts",
                "usb_errors",
                "decoded_frames",
                "undecoded_transfers",
            ):
                totals[key] += counters[key]
        result["totals"] = dict(totals)
        result["status"] = (
            "pass"
            if all(result["bands"][band]["decoded_frames"] > 0 for band in requested_bands)
            else "inconclusive"
        )
    except Exception as exc:
        if not device_opened and isinstance(exc, m.UnsupportedDevice):
            result["status"] = "unsupported"
        message = str(exc).replace(str(REPO_ROOT), "<repo>").replace(str(FW_DIR), "<firmware>")
        result["error"] = {"type": type(exc).__name__, "message": message}

    result["duration_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, indent=2, sort_keys=True))
    return {"pass": 0, "fail": 1, "inconclusive": 2, "unsupported": 3}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
