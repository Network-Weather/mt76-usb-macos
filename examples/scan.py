#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Tri-band channel-hopping BSSID census. Passive receive only.

Brings the radio up once, then re-tunes per channel and dwells briefly on
each. Aggregates BSSIDs with SSID, RSSI, channel utilisation and station
count (from the BSS Load IE). Nothing here transmits.

Usage: scan.py [2.4|5|6|all]

Firmware is loaded from $MT7921_FW_DIR, defaulting to <repo>/firmware.
"""

import argparse
import os
import sys
import time
from collections import Counter, OrderedDict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = os.environ.get("MT7921_FW_DIR", os.path.join(REPO_ROOT, "firmware"))
DWELL = float(os.environ.get("DWELL_SECONDS", "1.5"))

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
# 6 GHz preferred scanning channels: an AP that wants to be found beacons here.
CH_6_PSC = [5, 21, 37, 53, 69, 85, 101, 117, 133, 149, 165, 181, 197, 213, 229]

PLANS = {
    "2.4": [("2.4GHz", c) for c in CH_24],
    "5": [("5GHz", c) for c in CH_5],
    "6": [("6GHz", c) for c in CH_6_PSC],
}
PLANS["all"] = PLANS["2.4"] + PLANS["5"] + PLANS["6"]
CHAN_BAND = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", nargs="?", choices=sorted(PLANS), default="all")
    parser.add_argument("--dwell", type=float, default=DWELL, help="seconds per channel")
    args = parser.parse_args()
    if not 0.05 <= args.dwell <= 10:
        parser.error("--dwell must be between 0.05 and 10 seconds")
    plan = PLANS[args.plan]

    with open(os.path.join(FW_DIR, "WIFI_MT7961_patch_mcu_1_2_hdr.bin"), "rb") as fh:
        patch = fh.read()
    with open(os.path.join(FW_DIR, "WIFI_RAM_CODE_MT7961_1.bin"), "rb") as fh:
        ram = fh.read()

    bss = OrderedDict()
    with m.Mt7921uDevice() as dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        print(
            f"scanning {len(plan)} channels, {args.dwell:g}s each "
            f"(~{len(plan) * args.dwell:.0f}s)\n"
        )

        for band, ch in plan:
            dev.set_chan_info(control_ch=ch, center_ch=ch, bw=m.CMD_CBW_20MHZ, band=CHAN_BAND[band])
            dev.config_sniffer(control_ch=ch, center_ch=ch, band_name=band, bw=m.SNIFFER_BW_20)
            time.sleep(0.05)
            kinds = Counter()
            n = 0
            deadline = time.monotonic() + args.dwell
            while time.monotonic() < deadline:
                try:
                    raw = bytes(dev.rx_read(timeout=250))
                except usb.core.USBError:
                    continue
                n += 1
                d = rxd.decode(raw)
                if d is None:
                    continue
                f = d.get("frame")
                if not f:
                    continue
                p = rxd.parse_80211(f)
                kinds[p["kind"]] += 1
                if p["kind"] in ("Beacon", "ProbeResp") and p.get("addr3"):
                    k = p["addr3"]
                    e = bss.setdefault(
                        k,
                        {
                            "ssid": p.get("ssid", "?"),
                            "band": band,
                            "ch": ch,
                            "n": 0,
                            "rssi": None,
                            "load": None,
                        },
                    )
                    e["n"] += 1
                    if d.get("rssi") is not None and (e["rssi"] is None or d["rssi"] > e["rssi"]):
                        e["rssi"] = d["rssi"]
                    if p.get("bss_load"):
                        e["load"] = p["bss_load"]
            bc = kinds["Beacon"] + kinds["ProbeResp"]
            mark = "*" if bc else " "
            print(f" {mark} {band:>6} ch {ch:>3}: {n:>5} xfers, {bc:>4} beacons/probe-resp")

    print()
    by_band = Counter(v["band"] for v in bss.values())
    print(f"{len(bss)} BSSIDs: " + ", ".join(f"{b} {c}" for b, c in by_band.items()))
    print()
    print(f"  {'BSSID':<19} {'band':>6} {'ch':>4} {'RSSI':>5} {'util':>5} {'sta':>4}  SSID")
    for k, v in sorted(
        bss.items(), key=lambda kv: (kv[1]["band"], kv[1]["ch"], -(kv[1]["rssi"] or -999))
    ):
        load = v["load"] or {}
        util = f"{load['channel_util_pct']}%" if load else ""
        sta = load.get("stations", "")
        r = str(v["rssi"]) if v["rssi"] is not None else "?"
        print(f"  {k:<19} {v['band']:>6} {v['ch']:>4} {r:>5} {util:>5} {sta!s:>4}  {v['ssid']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
