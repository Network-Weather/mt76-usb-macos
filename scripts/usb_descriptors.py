#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Show what the driver would do with each attached supported adapter, without firmware.

For every attached device whose USB id is in mt7921u.SUPPORTED_DEVICES, print its
configuration, interfaces, and endpoints, then the interface and endpoint roles
select_wifi_interface() resolves (or why it refuses). With --chip-id, also claim the
Wi-Fi interface and read MT_HW_CHIPID / MT_HW_REV over vendor control transfers; that
needs no firmware and is how a new adapter is identified on day one.

Output is redacted by design: no serial numbers or string descriptors are read or
printed. Safe to paste into an issue.

    ./.venv/bin/python scripts/usb_descriptors.py
    ./.venv/bin/python scripts/usb_descriptors.py --chip-id
    ./.venv/bin/python scripts/usb_descriptors.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import suppress

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402
import usb.util  # noqa: E402

import mt7921u as m  # noqa: E402

XFER_NAMES = {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}


def describe(dev, read_chip_id: bool) -> dict:
    key = (dev.idVendor, dev.idProduct)
    out: dict = {
        "usb_id": f"{key[0]:04x}:{key[1]:04x}",
        "chip": m.SUPPORTED_DEVICES.get(key),
        "bcd_usb": f"{dev.bcdUSB:#06x}",
        "usb_speed_code": getattr(dev, "speed", None),
        "configurations": dev.bNumConfigurations,
        "interfaces": [],
    }
    interfaces = m.interfaces_from_pyusb(dev)
    for intf in interfaces:
        out["interfaces"].append(
            {
                "number": intf.number,
                "class": "/".join(f"{v:02x}" for v in intf.class_triple),
                "endpoints": [
                    {
                        "address": f"{ep.address:#04x}",
                        "type": XFER_NAMES.get(ep.attributes & 0x3, "?"),
                    }
                    for ep in intf.endpoints
                ],
            }
        )
    try:
        number, in_eps, out_eps = m.select_wifi_interface(interfaces)
    except m.UnsupportedDevice as exc:
        out["selection"] = {"error": str(exc)}
        return out
    out["selection"] = {
        "wifi_interface": number,
        "in_eps": [f"{e:#04x}" for e in in_eps],
        "out_eps": [f"{e:#04x}" for e in out_eps],
        "roles": {
            "EP_IN_PKT_RX": f"{in_eps[0]:#04x}",
            "EP_IN_CMD_RESP": f"{in_eps[1]:#04x}",
            "EP_OUT_INBAND_CMD": f"{out_eps[0]:#04x}",
            "EP_OUT_AC_BE": f"{out_eps[1]:#04x}",
        },
    }
    if read_chip_id:
        out["registers"] = read_registers(dev, number)
    return out


def read_registers(dev, interface: int) -> dict:
    """Claim the Wi-Fi interface and read the identity registers (no firmware needed)."""
    reg = m.Mt7921u()
    try:
        usb.util.claim_interface(dev, interface)
    except usb.core.USBError as exc:
        return {"error": f"cannot claim interface {interface}: {exc}"}
    reg.dev = dev
    try:
        chipid = reg.rr(m.MT_HW_CHIPID)
        hwrev = reg.rr(m.MT_HW_REV)
        misc = reg.rr(m.MT_CONN_ON_MISC)
        return {
            "MT_HW_CHIPID": f"{chipid:#010x}",
            "chip_id": f"{chipid & 0xFFFF:#06x}",
            "MT_HW_REV": f"{hwrev:#010x}",
            "MT_CONN_ON_MISC": f"{misc:#010x}",
            "fw_n9_ready": bool(misc & m.MT_TOP_MISC2_FW_N9_RDY == m.MT_TOP_MISC2_FW_N9_RDY),
        }
    except usb.core.USBError as exc:
        return {"error": f"register read failed: {exc}"}
    finally:
        with suppress(usb.core.USBError):
            usb.util.release_interface(dev, interface)
        usb.util.dispose_resources(dev)


def print_text(report: dict) -> None:
    print(f"{report['usb_id']}  chip={report['chip']}  bcdUSB={report['bcd_usb']}")
    for intf in report["interfaces"]:
        eps = " ".join(f"{e['address']}/{e['type'][:4]}" for e in intf["endpoints"])
        print(f"  intf {intf['number']} class {intf['class']}: {eps}")
    sel = report["selection"]
    if "error" in sel:
        print(f"  selection: REFUSED: {sel['error']}")
    else:
        roles = ", ".join(f"{k}={v}" for k, v in sel["roles"].items())
        print(f"  selection: interface {sel['wifi_interface']}; {roles}")
    if "registers" in report:
        regs = report["registers"]
        if "error" in regs:
            print(f"  registers: {regs['error']}")
        else:
            print(
                f"  registers: chip_id={regs['chip_id']} MT_HW_REV={regs['MT_HW_REV']} "
                f"MT_CONN_ON_MISC={regs['MT_CONN_ON_MISC']} n9_ready={regs['fw_n9_ready']}"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--chip-id", action="store_true", help="claim and read identity registers")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--usb-id", help="only this vvvv:pppp (default: every supported id)")
    args = ap.parse_args()

    devices = m.find_supported_devices(args.usb_id)
    reports = [describe(dev, args.chip_id) for dev in devices]
    if args.json:
        print(json.dumps({"tool": "usb_descriptors", "devices": reports}, indent=2))
    elif not reports:
        print("no supported device attached (see mt7921u.SUPPORTED_DEVICES)")
    else:
        for report in reports:
            print_text(report)
    return 0 if reports else 3


if __name__ == "__main__":
    sys.exit(main())
