#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read three independently ROM-resolved MT7925/MT7961 SR RMAC registers.

Five100ms passive windows and immediate paired reads; no direct writes, TX or
SR enable/reset. Counter reads may clear hardware state: exclusive ownership.
MT7925 query reads/clears its separate accumulator; legacy cache also separate.
Field names follow firmware packing, not independently validated BSS attribution.
"""

import argparse
import collections
import contextlib
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.legacy_spatial_reuse_query_probe import query as legacy_query
from research.spatial_reuse_query_probe import query

REGISTERS = (0x820E5198, 0x820E519C, 0x820E51A0)


def fields(words):
    if len(words) != 3 or any(type(v) is not int or not 0 <= v < 0xFFFFFFFF for v in words):
        raise ValueError("three bounded non-sentinel RMAC words required")
    return {
        "non_srg_valid": words[0] & 65535,
        "srg_valid": words[0] >> 16,
        # Firmware deliberately swaps the second register's halfwords.
        "intra_bss_ppdu": words[1] >> 16,
        "inter_bss_ppdu": words[1] & 65535,
        "non_srg_ppdu_valid": words[2] & 65535,
        "srg_ppdu_valid": words[2] >> 16,
    }


def read(dev):
    if dev.CHIP not in (m.CHIP_MT7925, m.CHIP_MT7921):
        raise ValueError("MT7925/MT7961 ROM-resolved registers only")
    opened = time.monotonic_ns()
    words = [dev.rr(a) for a in REGISTERS]
    elapsed = time.monotonic_ns() - opened
    return {"words": [hex(v) for v in words], "fields_raw": fields(words), "read_span_ns": elapsed}


def observe(dev):
    counts = collections.Counter()
    start = time.monotonic_ns()
    deadline = time.monotonic() + 0.1
    transfers = 0
    while time.monotonic() < deadline and transfers < 128:
        try:
            raw = bytes(dev.rx_read(timeout=20))
        except usb.core.USBTimeoutError:
            continue
        transfers += 1
        decoded = m.decoder_for(dev)(raw)
        if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
            counts[str(decoded.get("phy", {}).get("mode"))] += 1
    elapsed = time.monotonic_ns() - start
    first = read(dev)
    immediate = read(dev)
    return {
        "receive_span_ns": elapsed,
        "good_fcs_frames_by_phy_mode": dict(counts),
        "transfers": transfers,
        "transfer_limit_reached": transfers == 128,
        "first": first,
        "immediate_repeat": immediate,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("mt7925", "mt7961"), default="mt7925")
    parser.add_argument("--channel", type=int, choices=(1, 36), default=36)
    args = parser.parse_args()
    out = {
        "tool": "sr_rmac_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": args.channel,
        "device": args.device,
        "registers": [hex(a) for a in REGISTERS],
        "rows": [],
    }
    with m.open_device("0846:9072" if args.device == "mt7925" else "0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel == 1 else "5GHz", args.channel, args.channel, 20)

        try:
            boot()
            out["initial_read"] = read(dev)
            for _ in range(5):
                out["rows"].append(observe(dev))
            out["firmware_query"] = (
                query(dev, 0xCB) if args.device == "mt7925" else legacy_query(dev, 18)
            )
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
