#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read source-traced MT7925 signed PHY comparison inputs; no activation or TX.

Three receive-only channel6/36/6 dwells, ten100ms windows each. Four exact
registers only; no assumed RSSI units, antenna labels, or interference verdict.
The firmware comparison is meaningful only with selector3. Normal reload on exit.
"""

import collections
import datetime
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import mt7925_csi_input_trace as trace
from research.legacy_signal_fields import s8, u32

m = trace.m
WINDOWS = (
    (
        "input_and_threshold_getters",
        0xE005A338,
        120,
        "775f95df00543e41c7267a5990593f8bd8f3a3ad9317843b6c9426bec1147f88",
    ),
    (
        "signed_comparator",
        0xE0078F2C,
        160,
        "00c764e762f3aaf69e3518c1438f4191730c6b2aa1e8e459794e1c4bde05c81e",
    ),
    (
        "selector_getter",
        0xE005A404,
        64,
        "2ff8b1aa2c40408977253863f9b5812635626ee6d52ecbfb4d9160627d8aca83",
    ),
    (
        "instruction_table",
        0x9171E8,
        4096,
        "d24962d144ffa01a10c0a19b5192e4afa1fccdccc179dfbe126274b2a68cb153",
    ),
)
REGISTERS = (0x830A6090, 0x830A6094, 0x8308838C, 0x8308863C)


def decode(words):
    if set(words) != set(REGISTERS):
        raise ValueError("exact four traced band0 words required")
    for word in words.values():
        u32(word)
        if word == 0xFFFFFFFF:
            raise ValueError("ambiguous all-one hardware read")
    inputs = [s8(words[a]) for a in REGISTERS[:2]]
    raw_thresholds = [s8(words[REGISTERS[2]] >> shift) for shift in (24, 16)]
    thresholds = [value or -51 for value in raw_thresholds]
    selector = (words[REGISTERS[3]] >> 18) & 15
    return {
        "input_raw_signed8": inputs,
        "threshold_raw_signed8": raw_thresholds,
        "threshold_effective_signed8": thresholds,
        "selector_raw_u4": selector,
        "comparison_available": selector == 3,
        "either_input_at_least_threshold": (
            any(x >= y for x, y in zip(inputs, thresholds, strict=True)) if selector == 3 else None
        ),
        "physical_units_validated": False,
    }


def snapshot(dev):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925-only PHY layout")
    return decode({address: dev.rr(address) for address in REGISTERS})


def verify(dev):
    rows = []
    for name, address, size, expected in WINDOWS:
        raw = b"".join(struct.pack("<I", u32(dev.rr(a))) for a in range(address, address + size, 4))
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected:
            raise ValueError("pinned PHY code mismatch")
        rows.append(
            {
                "name": name,
                "address": hex(address),
                "bytes": size,
                "sha256": digest,
                "matches": True,
            }
        )
    return rows


def collect(dev):
    before, counts = snapshot(dev), collections.Counter()
    start, attempts = time.monotonic(), 0
    while time.monotonic() - start < 0.1 and attempts < 256:
        attempts += 1
        try:
            raw = dev.bulk_in(dev.ep_in_pkt_rx, 4096, timeout=1)
        except m.usb.core.USBError as exc:
            if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                continue
            raise
        decoded = m.decoder_for(dev)(raw)
        if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
            counts[decoded.get("phy", {}).get("mode_name", "unknown")] += 1
    return {
        "before": before,
        "after": snapshot(dev),
        "ordinary_good_by_phy": dict(counts),
        "elapsed_seconds": time.monotonic() - start,
        "attempts": attempts,
        "transfer_ceiling_reached": attempts == 256,
    }


def main():
    images = m.load_firmware(m.CHIP_MT7925, m.firmware_dir())
    trace.check_image(images[1])
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transmissions": 0,
        "experimental_register_writes": 0,
        "dwells": [],
    }
    with m.open_device("0846:9072") as dev:

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            boot()
            out["verified"] = verify(dev)
            for channel in (6, 36, 6):
                dev.tune("2.4GHz" if channel == 6 else "5GHz", channel, channel, 20)
                row = {"channel": channel, "samples": []}
                out["dwells"].append(row)
                for _ in range(10):
                    row["samples"].append(collect(dev))
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception:
                out["cleanup_reload_alive"] = False
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out.get("alive_after") or not out["cleanup_reload_alive"])


if __name__ == "__main__":
    raise SystemExit(main())
