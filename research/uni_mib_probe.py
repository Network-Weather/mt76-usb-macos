#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Does the MT7925 keep the same occupancy counters, behind its own command space?

The MT7921's counters are reached with `MCU_EXT_CMD_GET_MIB_INFO`, and the MT7925 answers no
EXT command at all -- connac3 does not use that space. That silence says nothing about whether
the counters exist, only that they were asked for in the wrong language. This asks in the right
one: `MCU_UNI_CMD_GET_MIB_INFO` (0x22), framed the way `mt7996_mcu_get_chan_mib_info` frames it,
a `{u8 band, u8 rsv[3]}` header followed by `{le16 tag, le16 len, le32 offs}` entries.

Sweeps the offset space, reports which offsets the firmware echoes back, and reads each twice
around a dwell so a counter that is merely present can be told from one that is running.

**It does not name anything.** The MT7921's counters were identified by what they tracked across
channels and bandwidths and then corroborated against a vendor enum whose gaps matched what the
hardware refused. None of that has been done here, and the mt7996 offsets echo back reading
zero, so they are not this chip's numbering either. The output is a map of what answers, which
is where that work would start.

Passive receive only; no SET command is sent.

Usage: uni_mib_probe.py [--max 48] [--band 2.4GHz --channel 6] [--seconds 6]
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

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402

#: mt76 mt76_connac_mcu.h:1333.
MCU_UNI_CMD_GET_MIB_INFO = 0x22
#: enum { UNI_CMD_MIB_DATA } -- mt7996/mcu.h:1000, the only tag in its enum.
UNI_CMD_MIB_DATA = 0
#: sizeof each request entry: le16 tag, le16 len, le32 offs.
UNI_MIB_ENTRY_LEN = 8
#: The offsets mt7996 uses for the four quantities it reads (mt7996/mcu.h:346). They echo back
#: on the MT7925 and read zero, so they are recorded as tried rather than as this chip's map.
MT7996_OFFSETS = {26: "obss_airtime", 27: "non_wifi_time", 28: "tx_time", 29: "rx_time"}
PROBE_TIMEOUT_MS = 1500


def build_request(band: int, offs: int) -> bytes:
    """One entry, because a single-offset request is the shape whose reply is unambiguous."""
    return struct.pack("<B3xHHI", band, UNI_CMD_MIB_DATA, UNI_MIB_ENTRY_LEN, offs)


def parse_counter(body: bytes, offs: int) -> int | None:
    """Find the echoed offset in the reply and read the 64-bit counter beside it.

    Searching for the echo rather than trusting a fixed position means this works whatever
    header the chip prepends, and returns nothing rather than a misaligned number when the
    offset is not echoed at all.
    """
    for at in range(0, max(0, len(body) - 12), 2):
        _tag, length, echoed = struct.unpack_from("<HHI", body, at)
        if echoed == offs and length in (UNI_MIB_ENTRY_LEN, 16) and at + 16 <= len(body):
            return struct.unpack_from("<Q", body, at + 8)[0]
    return None


def read_offset(dev, offs: int, band: int = 0) -> int | None:
    try:
        body = dev.reply_body(
            dev.mcu_uni(MCU_UNI_CMD_GET_MIB_INFO, build_request(band, offs), query=True)
        )
    except (m.McuError, RuntimeError, usb.core.USBError):
        return None
    return parse_counter(body, offs)


def runs(values: list[int]) -> str:
    out: list[list[int]] = []
    for v in values:
        if out and v == out[-1][1] + 1:
            out[-1][1] = v
        else:
            out.append([v, v])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--max", type=int, default=48)
    parser.add_argument("--band", default="2.4GHz", choices=sorted(m.CHAN_BAND))
    parser.add_argument("--channel", type=int, default=6)
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--band-idx", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max <= 512:
        parser.error("--max must be between 1 and 512")
    if not 1 <= args.seconds <= 60:
        parser.error("--seconds must be between 1 and 60")

    dev = m.open_device()
    if not hasattr(dev, "mcu_uni"):
        print(f"{dev.CHIP} does not speak UNI commands; this probe is for connac3", file=sys.stderr)
        return 3
    patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        center = m.center_channel(args.band, args.channel, 20) or args.channel
        dev.tune(args.band, args.channel, center, 20)
        time.sleep(1.0)
        first = {o: read_offset(dev, o, args.band_idx) for o in range(args.max)}
        echoed = [o for o, v in first.items() if v is not None]
        started = time.monotonic()
        time.sleep(args.seconds)
        elapsed = time.monotonic() - started
        second = {o: read_offset(dev, o, args.band_idx) for o in echoed}

    counters = {}
    for o in echoed:
        a, b = first[o], second[o]
        counters[o] = {
            "before": a,
            "after": b,
            "delta": None if b is None else b - a,
            "mt7996_name": MT7996_OFFSETS.get(o),
        }
    moved = [o for o, c in counters.items() if c["delta"]]
    out = {
        "tool": "uni_mib_probe",
        "mt76_usb_macos": m.__version__,
        "chip": dev.CHIP,
        "channel": f"{args.band}:{args.channel}",
        "dwell_s": round(elapsed, 2),
        "probed": args.max,
        "echoed": echoed,
        "moved": moved,
        "counters": {str(k): v for k, v in counters.items()},
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"{dev.CHIP} on {args.band} ch{args.channel}, {elapsed:.1f}s dwell\n")
        print(f"echoed back ({len(echoed)} of {args.max}): {runs(echoed)}")
        print(f"advanced    ({len(moved)}): {runs(sorted(moved))}\n")
        for o in sorted(moved):
            c = counters[o]
            name = c["mt7996_name"] or ""
            print(
                f"  offs {o:>3} {name:<15} +{c['delta']:>12}  "
                f"({100.0 * c['delta'] / (elapsed * 1e6):6.2f}% of dwell if microseconds)"
            )
        print(
            "\nNo counter is named by this output. Which is which needs the identification "
            "the MT7921's counters got:\nbehaviour across channels and bandwidths, then a "
            "vendor enum whose gaps match what the hardware refuses."
        )
    return 0 if moved else 2


if __name__ == "__main__":
    sys.exit(main())
