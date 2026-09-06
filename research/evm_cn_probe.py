#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""MT7961 firmware-derived CN/EVM register sampling in normal monitor mode.

0x962584 -> 0x942d38 -> 0x936fda reads only0x83086088 for band0.
Ten bounded50ms passive windows. No TX, register writes, RF mode or calibration.
Raw firmware names only; units, freshness and per-frame attribution unverified.
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

REGISTER = 0x83086088


def fields(word):
    if type(word) is not int or not 0 <= word < 0xFFFFFFFF:
        raise ValueError("bounded non-sentinel CN/EVM word required")
    return {
        "cn_raw_u9": (word >> 7) & 511,
        "evm_rx0_raw_u8": word >> 24,
        "evm_rx1_raw_u8": (word >> 16) & 255,
    }


def read(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("MT7961 firmware-derived CN/EVM register only")
    word = dev.rr(REGISTER)
    return {"word": hex(word), "fields_raw": fields(word)}


def observe(dev):
    counts = collections.Counter()
    deadline = time.monotonic() + 0.05
    start = time.monotonic_ns()
    transfers = 0
    while time.monotonic() < deadline and transfers < 128:
        try:
            raw = bytes(dev.rx_read(timeout=15))
        except usb.core.USBTimeoutError:
            continue
        transfers += 1
        decoded = m.decoder_for(dev)(raw)
        if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
            counts[str(decoded.get("phy", {}).get("mode"))] += 1
    return {
        "receive_span_ns": time.monotonic_ns() - start,
        "good_fcs_by_phy": dict(counts),
        "transfers": transfers,
        "transfer_limit_reached": transfers == 128,
        "sample": read(dev),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, choices=(1, 36, 149), default=36)
    args = parser.parse_args()
    out = {
        "tool": "evm_cn_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": args.channel,
        "register": hex(REGISTER),
        "rows": [],
    }
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel == 1 else "5GHz", args.channel, args.channel, 20)

        try:
            boot()
            out["initial"] = read(dev)
            for _ in range(10):
                out["rows"].append(observe(dev))
            out["immediate_repeat"] = read(dev)
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
