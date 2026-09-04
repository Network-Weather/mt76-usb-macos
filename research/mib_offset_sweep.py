#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Which MIB counter offsets does this chip accept, and what does each one track?

The experiment that found this chip's counter numbering. `MCU_EXT_CMD_GET_MIB_INFO` takes an
offset, and the published numbering differs per chip -- mt7915 uses 81/82/86/87, mt7916 uses
6/8/490/491 -- with the MT7921's published nowhere. So ask it: every offset in a range gets a
single-entry request, and the ones that answer are its numbering. Offsets it does not
implement return nothing at all, so a silent offset costs a full timeout.

Each accepted offset is then read twice around a dwell, beside the decoder's own frame count
and summed airtime, so a counter can be identified by what it tracks rather than guessed.
That is how offsets 2, 7, 11, 12 and 14 were named; see docs/FIRMWARE_RECON.md.

Passive receive only; no SET command is sent.

Usage: mib_offset_sweep.py [--max 128] [--band 5GHz --channel 36] [--seconds 8]
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
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import mcu_stats as mcs  # noqa: E402
import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

#: Short, because a silent offset costs the whole timeout and most of them are silent.
PROBE_TIMEOUT_MS = 700
READ_TIMEOUT_MS = 200


def read_offset(dev, offs: int, band: int = 0) -> int | None:
    try:
        body = dev.reply_body(
            dev.mcu_cmd_word(
                m.MCU_EXT_CMD(mcs.MCU_EXT_CMD_GET_MIB_INFO),
                struct.pack("<IIQ", band, offs, 0),
                timeout=PROBE_TIMEOUT_MS,
            )
        )
    except (m.McuError, RuntimeError, usb.core.USBError):
        return None
    return mcs.parse_mt7921_value(body)


def runs(values: list[int]) -> str:
    """Collapse a sorted list into ranges, so a 128-offset result reads in one line."""
    out: list[list[int]] = []
    for v in values:
        if out and v == out[-1][1] + 1:
            out[-1][1] = v
        else:
            out.append([v, v])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--max", type=int, default=128, help="highest offset to try")
    parser.add_argument("--band", default="5GHz", choices=sorted(m.CHAN_BAND))
    parser.add_argument("--channel", type=int, default=36)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max <= 1024:
        parser.error("--max must be between 1 and 1024")
    if not 1 <= args.seconds <= 60:
        parser.error("--seconds must be between 1 and 60")

    dev = m.open_device()
    patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        dev.tune(args.band, args.channel, args.channel, 20)
        time.sleep(0.5)

        accepted = [o for o in range(args.max) if read_offset(dev, o) is not None]
        before = {o: read_offset(dev, o) for o in accepted}

        started = time.monotonic()
        frames = 0
        airtime = 0.0
        decode = m.decoder_for(dev)
        # One preamble per aggregate, not per subframe; the identification compares decoded
        # airtime against the counters, and the naive sum inflates it severalfold.
        aggregates = rxd.AggregationTracker()
        while time.monotonic() - started < args.seconds:
            try:
                raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
            except usb.core.USBError:
                continue
            if not raw:
                continue
            d = decode(raw)
            if not d or not d.get("frame"):
                continue
            frames += 1
            parsed = rxd.parse_80211(d["frame"])
            for aggregate in aggregates.feed(d, len(d["frame"]), parsed.get("addr2")):
                airtime += aggregate.airtime_us() or 0.0
        for aggregate in aggregates.flush():
            airtime += aggregate.airtime_us() or 0.0
        elapsed_us = (time.monotonic() - started) * 1e6
        after = {o: read_offset(dev, o) for o in accepted}

    counters = {}
    for o in accepted:
        a, b = before.get(o), after.get(o)
        counters[o] = {
            "name": mcs.MIB_OFFSETS_MT7921.get(o),
            "delta": None if (a is None or b is None) else b - a,
        }
    result = {
        "tool": "mib_offset_sweep",
        "mt76_usb_macos": m.__version__,
        "channel": f"{args.band}:{args.channel}",
        "dwell_us": round(elapsed_us),
        "frames_decoded": frames,
        "decoded_airtime_us": round(airtime),
        "probed": args.max,
        "accepted": accepted,
        "counters": {str(k): v for k, v in counters.items()},
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    silent = [o for o in range(args.max) if o not in accepted]
    print(
        f"{args.band} ch{args.channel}, {elapsed_us / 1e6:.1f}s dwell, "
        f"{frames} frames decoded, {airtime:.0f} us decoded airtime\n"
    )
    print(f"accepted ({len(accepted)}): {runs(accepted)}")
    print(f"silent   ({len(silent)}): {runs(silent)}\n")
    for o in accepted:
        c = counters[o]
        d = c["delta"]
        extra = ""
        if d and o in (11, 12, 14):
            extra = f"   {100.0 * d / elapsed_us:6.2f}% of dwell"
        elif d and o in (2, 7):
            extra = f"   {d / (elapsed_us / 1e6):8.1f}/s"
        print(f"  offs {o:>3} {c['name'] or '':<20} delta={d if d is not None else '-':>10}{extra}")
    return 0 if accepted else 2


if __name__ == "__main__":
    sys.exit(main())
