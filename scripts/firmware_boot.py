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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--usb-id", help="adapter to use when several are attached")
    ap.add_argument("--verbose", action="store_true", help="print each MCU command")
    args = ap.parse_args()

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
