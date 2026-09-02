#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Watch one channel for roaming and steering events. Passive receive only.

Two modes:

  roam_watch.py --find SSID
      Sweep 2.4/5/6 GHz and list every BSSID advertising SSID with its channel and the
      802.11k/v/r flags it advertises. Use this to learn which channel a client's current
      AP is on before locking.

  roam_watch.py --lock BAND:CHANNEL [--client MAC] [--duration SECONDS]
      Lock the radio to one channel and print every management event the decoder
      classifies (BTM query/request/response, neighbor reports, deauth/disassoc with
      reason, authentication, association, reassociation, FT variants) with a timestamp.
      With --client, data frames to or from that address are counted per second so the
      client's last data frame on this channel is visible next to the steering events.

This is a diagnostic for the operator's own network. Output includes MAC addresses and
SSIDs; treat the terminal output as sensitive and do not commit it.
Firmware is loaded from $MT7921_FW_DIR, defaulting to <repo>/firmware.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = os.environ.get("MT7921_FW_DIR", os.path.join(REPO_ROOT, "firmware"))
CHAN_BAND = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}
# Sweep set for --find: the 2.4 GHz non-overlapping channels, every 5 GHz 20 MHz channel
# an AP in the US can sit on, and the 6 GHz preferred scanning channels.
SWEEP = (
    [("2.4GHz", c) for c in (1, 6, 11)]
    + [("5GHz", c) for c in (36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120)]
    + [("5GHz", c) for c in (124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165)]
    + [("6GHz", c) for c in (5, 21, 37, 53, 69, 85, 101, 117, 133, 149, 165, 181, 197, 213, 229)]
)
# Dwell per sweep channel: several beacon intervals (102.4 ms nominal) per AP.
FIND_DWELL_SECONDS = 0.6
READ_TIMEOUT_MS = 250
FTYPE_DATA = 2


def load_firmware() -> tuple[bytes, bytes]:
    with open(os.path.join(FW_DIR, "WIFI_MT7961_patch_mcu_1_2_hdr.bin"), "rb") as fh:
        patch = fh.read()
    with open(os.path.join(FW_DIR, "WIFI_RAM_CODE_MT7961_1.bin"), "rb") as fh:
        ram = fh.read()
    return patch, ram


def tune(dev: m.Mt7921uDevice, band: str, chan: int) -> None:
    dev.set_chan_info(control_ch=chan, center_ch=chan, bw=m.CMD_CBW_20MHZ, band=CHAN_BAND[band])
    dev.config_sniffer(control_ch=chan, center_ch=chan, band_name=band, bw=m.SNIFFER_BW_20)


def frames(dev: m.Mt7921uDevice, seconds: float):
    """Yield (decoded_descriptor, parsed_frame) for `seconds`."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
        except usb.core.USBError:
            continue
        d = rxd.decode(raw)
        if not d or not d.get("frame") or len(d["frame"]) < 10:
            continue
        yield d, rxd.parse_80211(d["frame"])


def ap_flags(p: dict) -> dict:
    """The 802.11k/v/r advertisement bits a house call cares about, from one beacon."""
    rrm = p.get("rrm_capabilities") or {}
    return {
        "k_neighbor_report": bool(rrm.get("neighbor_report")),
        "v_bss_transition": bool(p.get("bss_transition")),
        "r_mobility_domain": (p.get("mobility_domain") or {}).get("id"),
        "load": p.get("bss_load"),
    }


def find(dev: m.Mt7921uDevice, ssid: str) -> int:
    found: dict[str, dict] = {}
    for band, chan in SWEEP:
        tune(dev, band, chan)
        for d, p in frames(dev, FIND_DWELL_SECONDS):
            if p.get("kind") not in ("Beacon", "ProbeResp") or p.get("ssid") != ssid:
                continue
            bssid = p.get("addr3")
            if not bssid:
                continue
            entry = found.setdefault(bssid, {"band": band, "channel": chan, "rssi": d.get("rssi")})
            entry.update(ap_flags(p))
            if d.get("rssi") is not None and (entry["rssi"] is None or d["rssi"] > entry["rssi"]):
                entry["rssi"] = d["rssi"]
    if not found:
        print(f"no beacons for SSID {ssid!r} on any swept channel", file=sys.stderr)
        return 2
    for bssid, e in sorted(found.items(), key=lambda kv: (kv[1]["band"], kv[1]["channel"])):
        flags = "k" if e["k_neighbor_report"] else "-"
        flags += "v" if e["v_bss_transition"] else "-"
        flags += "r" if e["r_mobility_domain"] else "-"
        load = e["load"] or {}
        print(
            f"{bssid}  {e['band']:>6}:{e['channel']:<3}  rssi {e['rssi']!s:>4}  {flags}  "
            f"stations {load.get('stations', '?')}  util {load.get('channel_util_pct', '?')}%"
        )
    return 0


def watch(dev: m.Mt7921uDevice, band: str, chan: int, client: str | None, duration: float) -> int:
    tune(dev, band, chan)
    print(f"locked to {band}:{chan}; watching {duration:g}s" + (f" for {client}" if client else ""))
    start = time.monotonic()
    events = Counter()
    client_data_per_sec: dict[int, int] = defaultdict(int)
    last_client_data = None
    aps: dict[str, dict] = {}

    for _d, p in frames(dev, duration):
        t = time.monotonic() - start
        if p.get("kind") in ("Beacon", "ProbeResp") and p.get("addr3"):
            aps.setdefault(p["addr3"], {"ssid": p.get("ssid"), **ap_flags(p)})
            continue
        if client and p.get("ftype") == FTYPE_DATA:
            if client in (p.get("addr1"), p.get("addr2")):
                client_data_per_sec[int(t)] += 1
                last_client_data = t
            continue
        ev = rxd.management_event(p)
        if ev is None:
            continue
        name, detail = ev
        if client and client not in (p.get("addr1"), p.get("addr2"), p.get("addr3")):
            continue
        events[name] += 1
        print(
            f"{t:8.3f}s  {name:<22} {p.get('addr2', '?')} -> {p.get('addr1', '?')}  "
            f"bssid {p.get('addr3', '?')}  {json.dumps(detail, default=str)}"
        )

    print()
    print("APs beaconing on this channel:")
    for bssid, e in aps.items():
        print(
            f"  {bssid}  {e['ssid']!r}  k={e['k_neighbor_report']} v={e['v_bss_transition']} r={bool(e['r_mobility_domain'])}"
        )
    print("management events:", dict(events) or "none")
    if client:
        secs = sorted(client_data_per_sec)
        print(
            f"client data frames: {sum(client_data_per_sec.values())} over "
            f"{len(secs)} active seconds; last at {last_client_data!s:>6}s"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--find", metavar="SSID", help="sweep and list BSSIDs of this SSID")
    mode.add_argument("--lock", metavar="BAND:CHANNEL", help="lock to one channel and watch")
    parser.add_argument("--client", metavar="MAC", help="only report events involving this MAC")
    parser.add_argument("--duration", type=float, default=120.0, help="seconds to watch")
    args = parser.parse_args()
    if not 1 <= args.duration <= 3600:
        parser.error("--duration must be between 1 and 3600 seconds")
    client = args.client.lower() if args.client else None

    patch, ram = load_firmware()
    with m.Mt7921uDevice() as dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        if args.find:
            return find(dev, args.find)
        band, _, chan = args.lock.partition(":")
        if band not in CHAN_BAND or not chan.isdigit():
            parser.error("--lock wants BAND:CHANNEL, for example 5GHz:44")
        return watch(dev, band, int(chan), client, args.duration)


if __name__ == "__main__":
    sys.exit(main())
