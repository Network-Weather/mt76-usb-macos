#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Which MIB counters and PHY statistics will this firmware actually hand over?

The MCU keeps counters the register path does not reach, and the most interesting is
MIB_NON_WIFI_TIME: microseconds the medium was busy with energy that is not Wi-Fi at all.
A frame-counting sniffer cannot see that number by construction, and neither can a driver
that only reads CCA busy. It is reachable through MCU_EXT_CMD_GET_MIB_INFO, a command this
driver already knows how to frame.

The counter offsets are chip-specific and MT7921's are unpublished: mt7915 uses 81/82/86/87
and mt7916 uses 6/8/490/491 for the same four quantities (mt7915/mcu.h:186). So this sweeps
candidate offsets and reports which the firmware answers, rather than assuming either set.
The firmware refuses out-of-range indices -- its own string is
"MIB counter index = %d not supported" -- so a refusal is a real answer, not a timeout.

Everything here reads. No SET command is sent, nothing is transmitted, and no register is
written. See docs/FIRMWARE_RECON.md (Spike D).

Usage: mcu_stats.py [--band 5GHz --channel 36] [--seconds 4] [--sweep LO:HI] [--phy-max N]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import mt7921u as m  # noqa: E402

FW_DIR = m.firmware_dir()

# mt76 mt76_connac_mcu.h:1292 and :1309 at baseline c5a3bd91.
MCU_EXT_CMD_GET_MIB_INFO = 0x5A
MCU_EXT_CMD_PHY_STAT_INFO = 0xAD

# struct mt7915_mcu_mib { __le32 band; __le32 offs; __le64 data; } -- request and reply use
# the same 16-byte shape, the reply filling in `data` (mt7915/mcu.h).
MIB_ENTRY = "<IIQ"
MIB_ENTRY_LEN = struct.calcsize(MIB_ENTRY)  # 16; a test pins it against the struct

# enum mt7915_chan_mib_offs, mt7915/mcu.h:186. Two disjoint numbering schemes for the same
# four quantities, which is exactly why MT7921's cannot be assumed.
MIB_OFFSETS_V1 = {  # mt7915
    81: "tx_time",
    82: "rx_time",
    86: "obss_airtime",
    87: "non_wifi_time",
    88: "txop_init_count",
}
MIB_OFFSETS_V2 = {  # mt7916
    6: "tx_time",
    8: "rx_time",
    490: "obss_airtime",
    491: "non_wifi_time",
}
NAMED_OFFSETS = {**MIB_OFFSETS_V1, **MIB_OFFSETS_V2}

# mt7915 batches 5 entries per command; keep to that shape rather than inventing a larger
# one, since an over-long request is a plausible way to get a blanket refusal that says
# nothing about the individual offsets.
MIB_BATCH = 5

# enum at mt76_connac_mcu.h:1199. Five names upstream; whether the firmware answers more is
# the open question this sweep settles.
PHY_STATE_NAMES = {
    0: "TX_RATE",
    1: "RX_RATE",
    2: "RSSI",
    3: "CONTENTION_RX_RATE",
    4: "OFDMLQ_CNINFO",
}
PHY_CATEGORY_DEFAULT_MAX = 15

# A counter that never moves across a dwell is either unimplemented or measuring something
# static; either way it is not the airtime figure we are looking for.
MIN_DWELL_S, MAX_DWELL_S = 1.0, 30.0
# The firmware answers a refused index somehow; we do not know how, so treat these two
# readings as "no counter here" rather than as data.
DEAD_VALUES = (0x0000000000000000, 0xFFFFFFFFFFFFFFFF)


def parse_sweep(text: str) -> range:
    try:
        lo_s, hi_s = text.split(":")
        lo, hi = int(lo_s, 0), int(hi_s, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad sweep {text!r}; want LOW:HIGH") from exc
    if lo < 0 or hi <= lo:
        raise argparse.ArgumentTypeError("sweep needs 0 <= LOW < HIGH")
    if hi - lo > 1024:
        raise argparse.ArgumentTypeError("sweep is wider than 1024 offsets")
    return range(lo, hi)


def build_mib_request(band: int, offsets: list[int]) -> bytes:
    return b"".join(struct.pack(MIB_ENTRY, band, offs, 0) for offs in offsets)


def parse_mib_reply(body: bytes, band: int, offsets: list[int]) -> dict[int, int]:
    """Find each echoed {band, offs} pair in the reply and read the counter beside it.

    mt7915 skips a fixed 20-byte preamble and mt7916 skips none (mt7915/mcu.c:3241), so the
    header length is chip-specific and MT7921's is unknown. Searching for the echoed pair
    instead of trusting an offset means this works whatever the preamble turns out to be,
    and it fails loudly rather than silently misaligning by 20 bytes.
    """
    found: dict[int, int] = {}
    for offs in offsets:
        needle = struct.pack("<II", band, offs)
        at = body.find(needle)
        if at < 0 or at + MIB_ENTRY_LEN > len(body):
            continue
        (value,) = struct.unpack_from("<Q", body, at + 8)
        found[offs] = value
    return found


def query_mib(dev, band: int, offsets: list[int], timeout: int = 3000) -> dict:
    """One GET_MIB_INFO round trip. Returns values keyed by offset, plus what went wrong."""
    req = build_mib_request(band, offsets)
    try:
        rxd = dev.mcu_cmd_word(m.MCU_EXT_CMD(MCU_EXT_CMD_GET_MIB_INFO), req, timeout=timeout)
    except (m.McuError, RuntimeError) as exc:
        return {"offsets": offsets, "error": str(exc), "values": {}}
    body = dev.reply_body(rxd)
    values = parse_mib_reply(body, band, offsets)
    result = {"offsets": offsets, "reply_bytes": len(body), "values": values}
    missing = [o for o in offsets if o not in values]
    if missing:
        # The firmware answered but did not echo these back: refused, or a reply shape we
        # do not understand. Either way it is not a counter we can read.
        result["not_echoed"] = missing
    return result


def query_phy_category(dev, band: int, category: int, timeout: int = 3000) -> dict:
    """One PHY_STAT_INFO round trip. Request shape from mt7915_mcu_get_rx_rate."""
    req = struct.pack("<BBH", category, band, 0)  # category, band, wcid
    entry = {"category": category, "name": PHY_STATE_NAMES.get(category, "unnamed")}
    try:
        rxd = dev.mcu_cmd_word(m.MCU_EXT_CMD(MCU_EXT_CMD_PHY_STAT_INFO), req, timeout=timeout)
    except (m.McuError, RuntimeError) as exc:
        entry["answered"] = False
        entry["error"] = str(exc)
        return entry
    body = dev.reply_body(rxd)
    entry["answered"] = True
    entry["reply_bytes"] = len(body)
    entry["reply_head"] = body[:32].hex()
    entry["all_zero"] = not any(body)
    return entry


def sweep_mib(dev, band: int, offsets: list[int], seconds: float) -> dict:
    """Read every offset twice around a dwell; a counter is only real if it moves."""
    batches = [offsets[i : i + MIB_BATCH] for i in range(0, len(offsets), MIB_BATCH)]
    before: dict[int, int] = {}
    errors = []
    for batch in batches:
        r = query_mib(dev, band, batch)
        before.update(r["values"])
        if r.get("error"):
            errors.append(r)
    time.sleep(seconds)
    after: dict[int, int] = {}
    for batch in batches:
        r = query_mib(dev, band, batch)
        after.update(r["values"])

    counters = {}
    for offs in offsets:
        if offs not in after:
            continue
        value = after[offs]
        delta = value - before.get(offs, 0)
        counters[offs] = {
            "name": NAMED_OFFSETS.get(offs),
            "before": before.get(offs),
            "after": value,
            "delta": delta,
            # Only a counter that moved is evidence of a live measurement. A static
            # non-zero value may still be meaningful, so it is reported, not discarded.
            "moved": delta > 0,
            "dead_value": value in DEAD_VALUES,
        }
    return {
        "queried": len(offsets),
        "echoed": len(counters),
        "moved": sum(1 for c in counters.values() if c["moved"]),
        "errors": errors,
        "counters": {str(k): v for k, v in sorted(counters.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--band", default="5GHz", choices=sorted(m.CHAN_BAND))
    parser.add_argument("--channel", type=int, default=36)
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--sweep", type=parse_sweep, help="also try this offset range, e.g. 0:128")
    parser.add_argument("--phy-max", type=int, default=PHY_CATEGORY_DEFAULT_MAX)
    parser.add_argument("--band-idx", type=int, default=0, help="hardware band index")
    args = parser.parse_args()
    if not MIN_DWELL_S <= args.seconds <= MAX_DWELL_S:
        parser.error(f"--seconds must be between {MIN_DWELL_S} and {MAX_DWELL_S}")
    if not 0 <= args.phy_max <= 255:
        parser.error("--phy-max must be between 0 and 255")

    offsets = sorted(NAMED_OFFSETS)
    if args.sweep:
        offsets = sorted(set(offsets) | set(args.sweep))

    dev = m.open_device()
    patch, ram = m.load_firmware(dev.CHIP, FW_DIR)
    out: dict = {
        "tool": "mcu_stats",
        "mt76_usb_macos": m.__version__,
        "chip": dev.CHIP,
        "band": args.band,
        "channel": args.channel,
        "dwell_s": args.seconds,
    }
    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        dev.tune(args.band, args.channel, args.channel, 20)

        out["mib"] = sweep_mib(dev, args.band_idx, offsets, args.seconds)
        out["phy_stat"] = [
            query_phy_category(dev, args.band_idx, c) for c in range(args.phy_max + 1)
        ]

    print(json.dumps(out, indent=2))

    mib = out["mib"]
    named_moved = [c["name"] for c in mib["counters"].values() if c["moved"] and c["name"]]
    print(
        f"\n{mib['echoed']}/{mib['queried']} offsets echoed, {mib['moved']} moved over "
        f"{args.seconds}s. Named counters that moved: {', '.join(sorted(set(named_moved))) or 'none'}",
        file=sys.stderr,
    )
    answered = [e for e in out["phy_stat"] if e["answered"]]
    unnamed = [e["category"] for e in answered if e["name"] == "unnamed"]
    print(
        f"PHY_STAT_INFO answered {len(answered)}/{len(out['phy_stat'])} categories"
        + (f"; unnamed ones that answered: {unnamed}" if unnamed else ""),
        file=sys.stderr,
    )
    if not mib["moved"]:
        print(
            "\nNo MIB counter moved. That is a result: record it in NEGATIVE_RESULTS.md with "
            "the offsets swept, and fall back to Spike B.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
