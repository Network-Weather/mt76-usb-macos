#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Boot the firmware on the attached adapter and report what the chip says, redacted.

The smallest hardware check above enumeration: open the device by its USB id, run
bringup() (WFSYS reset if needed, power on, DMA init, patch and RAM download, N9_RDY,
NIC capability, efuse push), and print one JSON record with the chip id, hardware
revision, firmware hashes, the capability element tags the firmware reported, and the
PHY capability fields. The MAC address element is reported by presence only.

    ./.venv/bin/python scripts/firmware_boot.py [--usb-id VVVV:PPPP] [--verbose]

Exit 0 on N9_RDY plus a successful efuse push, 1 on failure, 3 when no supported
device is attached.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import mt7921u as m  # noqa: E402

FW_DIR = m.firmware_dir()

# rx_pkt_type (mt76_connac.h): the same DW0 bits 31:27 on connac2 and connac3, so this
# count needs no descriptor decoder and works before one exists for a chip.
PKT_TYPE_NAMES = {
    0: "TXS",
    1: "TXRXV",
    2: "NORMAL",
    3: "RX_DUP_RFB",
    4: "RX_TMR",
    5: "RETRIEVE",
    6: "TXRX_NOTIFY",
    7: "RX_EVENT",
    8: "NORMAL_MCU",
}


def parse_channel(text: str) -> tuple[str, int, int, int]:
    parts = text.split(":")
    if len(parts) < 2 or parts[0] not in m.CHAN_BAND or not all(p.isdigit() for p in parts[1:]):
        raise ValueError(f"channel must look like 5GHz:36[:42[:80]], got {text!r}")
    control = int(parts[1])
    center = int(parts[2]) if len(parts) > 2 else control
    width = int(parts[3]) if len(parts) > 3 else 20
    return parts[0], control, center, width


def receive_counts(dev, channel: str, seconds: float) -> dict:
    """Monitor mode, sniffer on, tune, then count bulk transfers by RXD packet type."""
    import usb.core

    band, control, center, width = parse_channel(channel)
    dev.set_monitor_mode()
    dev.set_sniffer(True)
    dev.tune(band, control, center, width)
    time.sleep(0.05)
    counts: dict[str, int] = {}
    sizes: list[int] = []
    timeouts = errors = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            raw = bytes(dev.rx_read(timeout=250))
        except usb.core.USBTimeoutError:
            timeouts += 1
            continue
        except usb.core.USBError:
            errors += 1
            continue
        if len(raw) < 4:
            counts["short"] = counts.get("short", 0) + 1
            continue
        pkt_type = (int.from_bytes(raw[:4], "little") >> 27) & 0x1F
        name = PKT_TYPE_NAMES.get(pkt_type, f"type_{pkt_type}")
        counts[name] = counts.get(name, 0) + 1
        sizes.append(len(raw))
    sizes.sort()
    return {
        "channel": {"band": band, "control": control, "center": center, "width_mhz": width},
        "seconds": seconds,
        "transfers": sum(counts.values()),
        "by_pkt_type": counts,
        "usb_timeouts": timeouts,
        "usb_errors": errors,
        "transfer_bytes": {
            "min": sizes[0] if sizes else None,
            "median": sizes[len(sizes) // 2] if sizes else None,
            "max": sizes[-1] if sizes else None,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--usb-id", help="adapter to use when several are attached")
    ap.add_argument("--verbose", action="store_true", help="print each MCU command")
    ap.add_argument(
        "--rx",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="after boot, enter monitor mode, tune, and count receive transfers this long",
    )
    ap.add_argument(
        "--channel",
        default="2.4GHz:6",
        metavar="BAND:CONTROL[:CENTER[:WIDTH]]",
        help="channel for --rx (default 2.4GHz:6; e.g. 6GHz:53:47:160)",
    )
    args = ap.parse_args()
    if args.rx and not 0 < args.rx <= 60:
        ap.error("--rx must be between 0 and 60 seconds")

    result: dict = {"tool": "firmware_boot", "mt76_usb_macos": m.__version__, "status": "fail"}
    log_lines: list[str] = []
    started = time.monotonic()
    try:
        dev = m.open_device(args.usb_id, verbose=args.verbose)
        chip = dev.CHIP
        patch, ram = m.load_firmware(chip, FW_DIR)
        result["chip"] = chip
        result["firmware"] = {
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "ram_sha256": hashlib.sha256(ram).hexdigest(),
        }
        with dev:
            result["device"] = {
                "usb_id": dev.layout.usb_id,
                "wifi_interface": dev.layout.interface,
                "chip_id": f"{dev.chip_id():#06x}",
                "hw_rev": f"{dev.hw_rev():#010x}",
            }
            dev.bringup(patch, ram, log=log_lines.append)
            misc = dev.rr(m.MT_CONN_ON_MISC)
            result["mt_conn_on_misc"] = f"{misc:#010x}"
            result["n9_ready"] = (misc & m.MT_TOP_MISC2_FW_N9_RDY) == m.MT_TOP_MISC2_FW_N9_RDY
            caps = getattr(dev, "nic_caps", None)
            if caps:
                result["capability_tags"] = dev.cap_names()
                if dev.phy_cap:
                    result["phy_cap"] = {k: v for k, v in dev.phy_cap.items() if k != "hw_path"} | {
                        "hw_path": f"{dev.phy_cap['hw_path']:#04x}"
                    }
            if args.rx:
                result["rx"] = receive_counts(dev, args.channel, args.rx)
        result["status"] = "pass" if result["n9_ready"] else "fail"
    except m.UnsupportedDevice as exc:
        result["status"] = "unsupported"
        result["error"] = str(exc)
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    result["log"] = log_lines
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, indent=2, sort_keys=True))
    return {"pass": 0, "fail": 1, "unsupported": 3}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
