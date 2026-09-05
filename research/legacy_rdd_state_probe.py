#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""MT7961 receiver-only CE8F STOP/START/STOP with traced RAM-state readback.

No ACK is assumed on this legacy route. Require the independently traced,
allocated on-chip RDD buffer and inactive host-state byte before START. No DMA
addresses supplied, raw buffer reads, TX, emulation or detector thresholds.
Three bounded one-second receive windows, then STOP and full normal reload.
RAM state proves handler execution only, not detector sensitivity/activation.
"""

import argparse
import contextlib
import datetime
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m
from research.rdd_stop_probe import collect

TABLE = 0x02003000 + 174232
STATE = 0x02037214


def allocation(data):
    """NDS32 93e7f8:18 records24B, selector0/8/20; base12/size16."""
    if len(data) != 18 * 24:
        raise ValueError("exact allocation table required")
    rows = []
    for offset in range(0, len(data), 24):
        a, _, b, base, size, _ = struct.unpack_from("<6I", data, offset)
        if (a, b, data[offset + 20]) == (0, 3, 0):
            rows.append({"base": hex(base), "bytes": size})
    if rows != [{"base": "0x401c00", "bytes": 1024}]:
        raise ValueError("expected unique pinned on-chip RDD allocation")
    return rows[0]


def snapshot(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned MT7961 only")
    word = dev.rr(STATE)
    if type(word) is not int or not 0 <= word < 0xFFFFFFFF:
        raise ValueError("invalid RDD state word")
    return {
        "address": hex(STATE),
        "raw": hex(word),
        "host_enabled_byte": word & 255,
        "detector_region_byte": (word >> 8) & 255,
    }


def request(enabled):
    if type(enabled) is not bool:
        raise ValueError("boolean STOP/START only")
    return struct.pack("<BBBB4x", int(enabled), 0, 0, int(enabled))


def control(dev, enabled):
    payload = request(enabled)
    before = snapshot(dev)
    if enabled:
        raw = b"".join(struct.pack("<I", dev.rr(a)) for a in range(TABLE, TABLE + 432, 4))
        memory = allocation(raw)
        if before["host_enabled_byte"] != 0:
            raise ValueError("exclusive inactive detector required")
    else:
        memory = None
    dev.mcu_cmd_word(m.MCU_CE_CMD(0x8F), payload, wait=False, timeout=1000)
    received = collect(dev)
    return {
        "requested_enabled": enabled,
        "before": before,
        "after": snapshot(dev),
        "allocation_checked": memory,
        "receive": received,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-passive-detector", action="store_true")
    args = parser.parse_args()
    if not args.enable_passive_detector:
        parser.error("explicit receiver-only detector opt-in required")
    out = {
        "tool": "legacy_rdd_state_probe",
        "chip": "mt7961",
        "channel": 36,
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": [],
    }
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        try:
            boot()
            for enabled in (False, True, False):
                out["rows"].append(control(dev, enabled))
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                out["cleanup_stop"] = control(dev, False)
            except Exception as exc:
                out["stop_error_type"] = type(exc).__name__
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
                out["cleanup_state"] = snapshot(dev)
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or not out.get("alive_after")
        or not out.get("cleanup_reload_alive")
        or out.get("cleanup_state", {}).get("host_enabled_byte") != 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
