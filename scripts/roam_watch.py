#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Watch one channel for roaming and steering events. Passive receive only.

Two modes:

  roam_watch.py --find SSID
      Sweep 2.4/5/6 GHz and list every BSSID advertising SSID with its channel and the
      802.11k/v/r flags it advertises. Use this to learn which channel a client's current
      AP is on before locking.

  roam_watch.py --lock BAND:CHANNEL [--width MHZ] [--client MAC] [--duration SECONDS]
      Lock the radio to one channel and print every management event the decoder
      classifies (BTM query/request/response, neighbor reports, deauth/disassoc with
      reason, authentication, association, reassociation, FT variants) with a timestamp.
      With --client, data frames to or from that address are counted per second so the
      client's last data frame on this channel is visible next to the steering events.
      --width matches the AP's operating width; a 20 MHz sniffer misses the wider PPDUs
      a modern client sends, so a client that is talking can look silent.

  An 802.11be client uses a different address on each of its links and shows only its
  MLD address in some management frames. --client therefore matches every address the
  Multi-Link element of a captured (re)association frame ties to the same station, and
  reports each address it learns.

This is a diagnostic for the operator's own network. Output includes MAC addresses and
SSIDs; treat the terminal output as sensitive and do not commit it.
Firmware is loaded from $MT76_FW_DIR (or the older $MT7921_FW_DIR), defaulting to
<repo>/firmware; the pinned SHA-256s are checked.
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

FW_DIR = m.firmware_dir()  # $MT76_FW_DIR, then $MT7921_FW_DIR, then <repo>/firmware
CHAN_BAND = m.CHAN_BAND
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


def load_firmware(chip: str) -> tuple[bytes, bytes]:
    return m.load_firmware(chip, FW_DIR)


def tune(dev: m.Mt7921uDevice, band: str, chan: int, width_mhz: int = 20) -> None:
    center = m.center_channel(band, chan, width_mhz)
    if center is None:
        raise ValueError(f"no {width_mhz} MHz channel on {band} contains control channel {chan}")
    dev.tune(band, chan, center, width_mhz)


def frames(dev: m.Mt7921uDevice, seconds: float):
    """Yield (decoded_descriptor, parsed_frame) for `seconds`."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
        except usb.core.USBTimeoutError:
            continue  # quiet channel
        except usb.core.USBError as exc:
            # A transport failure means events can be missed; say so rather than hide it.
            print(f"usb error, frames may be missing: {exc}", file=sys.stderr)
            continue
        d = m.decoder_for(dev)(raw)
        if not d or not d.get("frame") or len(d["frame"]) < 10:
            continue
        yield d, rxd.parse_80211(d["frame"])


def ap_flags(p: dict) -> dict:
    """The 802.11k/v/r advertisement bits of one beacon."""
    rrm = p.get("rrm_capabilities") or {}
    return {
        "k_neighbor_report": bool(rrm.get("neighbor_report")),
        "v_bss_transition": bool(p.get("bss_transition")),
        "r_mobility_domain": (p.get("mobility_domain") or {}).get("id"),
        "load": p.get("bss_load"),
    }


def on_channel(d: dict, band: str, chan: int) -> bool:
    """True if the RX descriptor says this frame was received on (band, chan).

    Transfers queued before a retune and adjacent-channel 2.4 GHz frames carry the
    channel the radio was actually on; evidence for a locked channel must exclude them.
    """
    return d.get("band") == band and d.get("channel") == chan


def note_bssid(found: dict[str, dict], d: dict, p: dict, ssid: str) -> None:
    """Record one beacon or probe response for `ssid` into `found`, keyed by BSSID.

    The channel comes from the frame, never from where the radio was tuned: frames
    queued before a retune and adjacent-channel 2.4 GHz beacons both arrive while the
    radio is elsewhere. The DS Parameter Set IE is the AP's own statement and wins; the
    RX descriptor's channel (authoritative in the capture path) is the fallback.
    """
    if p.get("kind") not in ("Beacon", "ProbeResp") or p.get("ssid") != ssid:
        return
    bssid = p.get("addr3")
    if not bssid or not d.get("band"):
        return
    entry = found.setdefault(bssid, {"band": d["band"], "channel": d.get("channel"), "rssi": None})
    if p.get("ds_channel"):
        entry["band"], entry["channel"], entry["channel_source"] = d["band"], p["ds_channel"], "ds"
    elif entry.get("channel_source") != "ds":
        entry["band"], entry["channel"], entry["channel_source"] = (
            d["band"],
            d.get("channel"),
            "rxd",
        )
    entry.update(ap_flags(p))
    rssi = d.get("rssi")
    if rssi is not None and (entry["rssi"] is None or rssi > entry["rssi"]):
        entry["rssi"] = rssi


def find(dev: m.Mt7921uDevice, ssid: str) -> int:
    found: dict[str, dict] = {}
    for band, chan in SWEEP:
        tune(dev, band, chan)
        for d, p in frames(dev, FIND_DWELL_SECONDS):
            note_bssid(found, d, p, ssid)
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


def watch(
    dev: m.Mt7921uDevice,
    band: str,
    chan: int,
    client: str | None,
    duration: float,
    width_mhz: int = 20,
) -> int:
    tune(dev, band, chan, width_mhz)
    where = f"{band}:{chan} at {width_mhz} MHz"
    print(f"locked to {where}; watching {duration:g}s" + (f" for {client}" if client else ""))
    start = time.monotonic()
    events = Counter()
    client_data_per_sec: dict[int, int] = defaultdict(int)
    last_client_data = None
    aps: dict[str, dict] = {}
    off_channel = 0
    # Every address known to belong to the client. An 802.11be client uses a different
    # address per link, so a set seeded with one address grows as (re)association frames
    # reveal the rest. Addresses are only ever added from a frame the client itself
    # transmitted, so an AP's own Multi-Link element never joins this set.
    client_addresses = {client} if client else set()
    learned: list[tuple[float, str]] = []

    for d, p in frames(dev, duration):
        t = time.monotonic() - start
        if not on_channel(d, band, chan):
            off_channel += 1
            continue
        if p.get("kind") in ("Beacon", "ProbeResp") and p.get("addr3"):
            # On 2.4 GHz the radio hears overlapping channels, and the descriptor still
            # names the tuned channel. Keep the AP's own DS Parameter Set channel beside
            # it so an adjacent-channel AP is visible as such rather than presumed local.
            aps.setdefault(
                p["addr3"],
                {"ssid": p.get("ssid"), "ds_channel": p.get("ds_channel"), **ap_flags(p)},
            )
            continue
        if client_addresses:
            transmitted = rxd.station_addresses(p)
            if transmitted & client_addresses:
                for address in sorted(transmitted - client_addresses):
                    learned.append((t, address))
                    print(
                        f"{t:8.3f}s  client address learned from its Multi-Link element: {address}"
                    )
                client_addresses |= transmitted
        if client_addresses and p.get("ftype") == FTYPE_DATA:
            if client_addresses & {p.get("addr1"), p.get("addr2")}:
                client_data_per_sec[int(t)] += 1
                last_client_data = t
            continue
        ev = rxd.management_event(p)
        if ev is None:
            continue
        name, detail = ev
        if client_addresses and not client_addresses & {
            p.get("addr1"),
            p.get("addr2"),
            p.get("addr3"),
        }:
            continue
        events[name] += 1
        # Management frames carry no channel IE, so the only provenance is where the
        # radio was tuned when it received them; say that rather than "on channel".
        print(
            f"{t:8.3f}s  rx {d['band']}:{d['channel']}  {name:<22} "
            f"{p.get('addr2', '?')} -> {p.get('addr1', '?')}  bssid {p.get('addr3', '?')}  "
            f"{json.dumps(detail, default=str)}"
        )

    print()
    print(f"APs heard while tuned to {where} (ds = channel the AP itself advertises):")
    for bssid, e in aps.items():
        ds = e["ds_channel"]
        note = "ds ?" if ds is None else (f"ds {ds}" if ds == chan else f"ds {ds} ADJACENT")
        print(
            f"  {bssid}  {note:<14} {e['ssid']!r}  k={e['k_neighbor_report']} "
            f"v={e['v_bss_transition']} r={bool(e['r_mobility_domain'])}"
        )
    print("management events:", dict(events) or "none")
    print(f"frames ignored because the descriptor named another channel: {off_channel}")
    if client:
        secs = sorted(client_data_per_sec)
        print(f"client addresses matched: {' '.join(sorted(client_addresses))}")
        if learned:
            print(f"  {len(learned)} of them learned from Multi-Link elements during this watch")
        else:
            print("  no Multi-Link element from this client was captured on this channel")
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
    parser.add_argument(
        "--width",
        type=int,
        default=20,
        choices=sorted(m.WIDTH_TO_SNIFFER_BW),
        help="sniffer bandwidth in MHz for --lock (default 20); match the AP's width, "
        "since a 20 MHz sniffer does not decode the wider PPDUs a modern client sends",
    )
    args = parser.parse_args()
    if not 1 <= args.duration <= 3600:
        parser.error("--duration must be between 1 and 3600 seconds")
    client = args.client.lower() if args.client else None

    # Resolve the channel before touching USB: an unusable width should fail here, not
    # after a firmware download.
    band = chan = None
    if args.lock:
        band, _, chan_text = args.lock.partition(":")
        if band not in CHAN_BAND or not chan_text.isdigit():
            parser.error("--lock wants BAND:CHANNEL, for example 5GHz:44")
        chan = int(chan_text)
        if m.center_channel(band, chan, args.width) is None:
            parser.error(f"no {args.width} MHz channel on {band} contains control channel {chan}")

    dev = m.open_device()
    patch, ram = load_firmware(dev.CHIP)
    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        if args.find:
            return find(dev, args.find)
        return watch(dev, band, chan, client, args.duration, args.width)


if __name__ == "__main__":
    sys.exit(main())
