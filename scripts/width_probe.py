#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Which channel widths does this adapter decode, and what width does each AP run?

Passive receive only. For each BAND:CONTROL[:CENTER[:WIDTH]] argument the sniffer is
configured at that width and frames are counted for a few seconds by decoded PHY width and
802.11 frame type. Beacons heard on the channel are summarized by the operating width their
own VHT Operation or HE Operation element advertises, so a silent 160 MHz AP is visible as
"advertises 160, nothing decoded" rather than as an empty channel.

Output is counts and per-BSSID width claims only; no SSIDs, client addresses, or payloads.

Usage: width_probe.py 5GHz:132:138:80 6GHz:53:47:160 [--seconds 6]
Firmware is loaded from $MT7921_FW_DIR, defaulting to <repo>/firmware.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = os.environ.get("MT7921_FW_DIR", os.path.join(REPO_ROOT, "firmware"))
CHAN_BAND = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}
# Channel-switch and sniffer commands encode width differently (mt7921/mcu.c).
CMD_CBW = {20: m.CMD_CBW_20MHZ, 40: m.CMD_CBW_40MHZ, 80: m.CMD_CBW_80MHZ, 160: m.CMD_CBW_160MHZ}
SNIFFER_BW = {20: m.SNIFFER_BW_20, 40: m.SNIFFER_BW_20, 80: m.SNIFFER_BW_80, 160: m.SNIFFER_BW_160}
READ_TIMEOUT_MS = 250
# IEEE 802.11-2020 9.4.2.158 VHT Operation: Channel Width 0=20/40, 1=80/160/80+80 (with CCFS1).
VHT_WIDTH = {0: "20/40", 1: "80 or 160", 2: "160", 3: "80+80"}
# IEEE 802.11ax 9.4.2.249 HE Operation, 6 GHz Operation Information Control bits 0-1.
HE6_WIDTH = {0: 20, 1: 40, 2: 80, 3: 160}
EID_VHT_OPERATION = 192
EID_EXTENSION = 255
EXT_HE_OPERATION = 36


def parse_target(text: str) -> tuple[str, int, int, int]:
    parts = text.split(":")
    if len(parts) < 2 or parts[0] not in CHAN_BAND or not all(p.isdigit() for p in parts[1:]):
        raise argparse.ArgumentTypeError(f"bad target {text!r}; want BAND:CONTROL[:CENTER[:WIDTH]]")
    control = int(parts[1])
    center = int(parts[2]) if len(parts) > 2 else control
    width = int(parts[3]) if len(parts) > 3 else 20
    if width not in CMD_CBW:
        raise argparse.ArgumentTypeError(f"width {width} not in {sorted(CMD_CBW)}")
    return parts[0], control, center, width


def advertised_width(ie_list) -> str | None:
    """The operating width a beacon's own operation elements claim, as text."""
    for eid, val in ie_list:
        if eid == EID_EXTENSION and val and val[0] == EXT_HE_OPERATION and len(val) >= 7:
            params = int.from_bytes(val[1:4], "little")
            vht_present = bool(params & (1 << 14))
            cohosted = bool(params & (1 << 15))
            six_ghz = bool(params & (1 << 17))
            off = 1 + 3 + 1 + 2 + (3 if vht_present else 0) + (1 if cohosted else 0)
            if six_ghz and len(val) >= off + 5:
                _primary, control, ccfs0, ccfs1, _rate = val[off : off + 5]
                return f"he6 {HE6_WIDTH[control & 3]} ccfs0 {ccfs0} ccfs1 {ccfs1}"
    for eid, val in ie_list:
        if eid == EID_VHT_OPERATION and len(val) >= 3:
            return f"vht {VHT_WIDTH.get(val[0], val[0])} ccfs0 {val[1]} ccfs1 {val[2]}"
    return None


def probe(dev: m.Mt7921uDevice, band: str, control: int, center: int, width: int, secs: float):
    dev.set_chan_info(control_ch=control, center_ch=center, bw=CMD_CBW[width], band=CHAN_BAND[band])
    dev.config_sniffer(control_ch=control, center_ch=center, band_name=band, bw=SNIFFER_BW[width])
    by_width = collections.Counter()
    by_kind = collections.Counter()
    aps: dict[str, str | None] = {}
    frames = usb_errors = 0
    deadline = time.monotonic() + secs
    while time.monotonic() < deadline:
        try:
            raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
        except usb.core.USBTimeoutError:
            continue
        except usb.core.USBError as exc:
            usb_errors += 1
            print(f"usb error: {exc}", file=sys.stderr)
            continue
        d = rxd.decode(raw)
        if not d or not d.get("frame") or len(d["frame"]) < 10:
            continue
        frames += 1
        by_width[str((d.get("phy") or {}).get("bw_mhz", "?"))] += 1
        p = rxd.parse_80211(d["frame"])
        by_kind[p.get("kind", "?")] += 1
        if p.get("kind") == "Beacon" and p.get("addr3") and p["addr3"] not in aps:
            aps[p["addr3"]] = advertised_width(p.get("ie_list", []))
    return {
        "target": f"{band}:{control}",
        "center": center,
        "configured_width_mhz": width,
        "seconds": secs,
        "frames": frames,
        "usb_errors": usb_errors,
        "by_decoded_width_mhz": dict(by_width),
        "by_kind": dict(by_kind.most_common()),
        "beaconing_bssids": len(aps),
        "advertised_widths": dict(collections.Counter(w or "unknown" for w in aps.values())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("targets", nargs="+", type=parse_target)
    parser.add_argument("--seconds", type=float, default=6.0)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("--seconds must be between 1 and 60")
    with open(os.path.join(FW_DIR, "WIFI_MT7961_patch_mcu_1_2_hdr.bin"), "rb") as fh:
        patch = fh.read()
    with open(os.path.join(FW_DIR, "WIFI_RAM_CODE_MT7961_1.bin"), "rb") as fh:
        ram = fh.read()
    results = []
    with m.Mt7921uDevice() as dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        for band, control, center, width in args.targets:
            results.append(probe(dev, band, control, center, width, args.seconds))
    print(
        json.dumps(
            {"tool": "width_probe", "mt7921u_macos": m.__version__, "runs": results}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
