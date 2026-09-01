#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
#
# ============================================================================
# WARNING: injection on this radio is RESEARCH-GRADE and RATE-LIMITED.
#
# Transmit has been confirmed only at scan rates (a few frames, spaced out).
# SUSTAINED TRANSMIT CAN PANIC THE MCU and force a physical replug. Do not
# loop this at high rate. Only ever transmit on frequencies you are legally
# permitted to use in your regulatory domain.
#
# This demo sends a single wildcard Probe Request: the frame every station on
# earth emits continuously, asking an AP a question it is built to answer. If
# an AP replies with a Probe Response addressed to our MAC, the frame
# demonstrably reached the air. Nothing else is transmitted.
# ============================================================================
"""Minimal probe-request injection demo.

Usage: inject_demo.py [channel] [band] --acknowledge-experimental-transmit

Firmware is loaded from $MT7921_FW_DIR, defaulting to <repo>/firmware.
"""

import argparse
import os
import sys
import time
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = os.environ.get("MT7921_FW_DIR", os.path.join(REPO_ROOT, "firmware"))
CHAN_BAND = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}

# Rate limit: a handful of frames, spaced out. Do NOT raise these.
PROBES = 3
PROBE_GAP = 0.05


def listen(dev, our_mac_str, secs=1.5):
    """Look for a Probe Response addressed to us, and count what else arrives."""
    kinds = Counter()
    directed = []
    deadline = time.monotonic() + secs
    while time.monotonic() < deadline:
        try:
            raw = bytes(dev.rx_read(timeout=250))
        except usb.core.USBError:
            continue
        d = rxd.decode(raw)
        if d is None:
            continue
        f = d.get("frame")
        if not f:
            continue
        p = rxd.parse_80211(f)
        kinds[p["kind"]] += 1
        if p["kind"] == "ProbeResp" and p.get("addr1") == our_mac_str:
            directed.append((p.get("addr3"), p.get("ssid"), d.get("rssi")))
    return kinds, directed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=int, nargs="?", default=6)
    parser.add_argument("band", nargs="?", choices=sorted(CHAN_BAND), default="2.4GHz")
    parser.add_argument(
        "--acknowledge-experimental-transmit",
        action="store_true",
        help="confirm that this sends frames and can panic the MCU",
    )
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("refusing to transmit without --acknowledge-experimental-transmit")
    if not 1 <= args.channel <= 255:
        parser.error("channel must be between 1 and 255")
    chan = args.channel
    band = args.band

    with open(os.path.join(FW_DIR, "WIFI_MT7961_patch_mcu_1_2_hdr.bin"), "rb") as fh:
        patch = fh.read()
    with open(os.path.join(FW_DIR, "WIFI_RAM_CODE_MT7961_1.bin"), "rb") as fh:
        ram = fh.read()

    with m.Mt7921uDevice() as dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        caps = dev.get_nic_capability()
        mac = bytes(caps.get(0x07, b"\x00" * 6)[:6])
        mac_str = rxd.mac(mac)
        print(f"radio {mac_str}, channel {chan} ({band})")

        dev.set_monitor_mode()
        dev.set_sniffer(True)
        dev.set_chan_info(control_ch=chan, center_ch=chan, bw=m.CMD_CBW_20MHZ, band=CHAN_BAND[band])
        dev.config_sniffer(control_ch=chan, center_ch=chan, band_name=band, bw=m.SNIFFER_BW_20)
        time.sleep(0.2)

        base, _ = listen(dev, mac_str, 1.0)
        print(f"baseline receive works: {sum(base.values())} frames, {base['Beacon']} beacons")
        print(f"chip alive before transmit: {dev.alive()}\n")

        frame = m.build_probe_request(mac)
        seq = 0
        sent_ok = True
        try:
            for _ in range(PROBES):
                seq += 1
                dev.inject(frame, m.TX_ENDPOINTS[0], seq)
                time.sleep(PROBE_GAP)
        except Exception as exc:
            sent_ok = False
            print(f"bulk write failed: {exc}")

        alive = dev.alive()
        print(f"write accepted: {sent_ok}   chip alive after: {alive}")
        if not alive:
            print("MCU appears to have panicked; replug the radio")
            return 3

        kinds, directed = listen(dev, mac_str, 1.5)
        print(f"receive still working: {sum(kinds.values())} frames")
        if directed:
            print(f"*** {len(directed)} Probe Response(s) addressed to us:")
            for bssid, ssid, rssi in directed[:6]:
                print(f"      from {bssid} rssi={rssi} ssid={ssid!r}")
            print("TRANSMIT CONFIRMED")
        else:
            print("no directed Probe Response seen")
        print(f"\nfinal: chip alive={dev.alive()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
