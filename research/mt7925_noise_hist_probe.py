#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded firmware-traced MT7925 histogram test, control index0 only, no TX.

Requires exclusive ownership and explicit acknowledgment: resets shared histogram
history. Only reset bit29 and capture bits2:0 are changed, restored, then normal
firmware is reloaded. No UNI36 activation, index1 writes, or calibration claims.
"""

import argparse
import datetime
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import mt7925_mib_characterize as mib
from research.txpower_register_probe import check_image, m, read_words

WINDOWS = (
    (
        "initializer",
        0xE00532BC,
        116,
        "e4158899f546948c3e8ffcbd2dc37ceefb7c7fc498835f238390977b62cdb2e0",
    ),
    (
        "dispatcher",
        0xE0053784,
        24,
        "d56cec41febf572897e78e110db687cb3cac5ebfd43b73455b9296c414acd646",
    ),
    (
        "callback_and_event",
        0xE0054118,
        204,
        "805c85b8e38fbd80868a56c69ca5323be047ff706bf11832a468d66e780dbcb0",
    ),
    (
        "histogram_helpers",
        0xE005AE5C,
        256,
        "27d5f4a173e83944ecb15b9e51c4d023e7404ad075f370490d233085fa0d7d83",
    ),
    (
        "instruction_table",
        0x9171E8,
        4096,
        "d24962d144ffa01a10c0a19b5192e4afa1fccdccc179dfbe126274b2a68cb153",
    ),
)
CONTROL = 0x83082004
RESET = 0x83088230
MASKS = {CONTROL: 7, RESET: 1 << 29}
BANKS = {"ordinary_getter": 0x83088600, "timer_getter": 0x83001000}
OTHER_VIEWS = {"ordinary_index1": 0x83098600, "timer_index1": 0x83011000}
DURATIONS = (0.25, 1.0)
CHANNELS = (1, 6, 11, 36)
MIB_OFFSETS = (11, 12, 13, 17, 19, 20, 52)
THRESHOLD_ADDRESS = 0x02216F2C  # Traced GP+18220; ten signed labels, not calibration.


def verify(dev):
    result = []
    for name, address, size, expected in WINDOWS:
        digest = hashlib.sha256(read_words(dev, address, size)).hexdigest()
        result.append(
            {
                "name": name,
                "address": hex(address),
                "bytes": size,
                "sha256": digest,
                "expected_sha256": expected,
                "matches": digest == expected,
            }
        )
    return result


def masked(address, word, bits):
    if (
        type(address) is not int
        or address not in MASKS
        or type(word) is not int
        or not 0 <= word < 0xFFFFFFFF
        or type(bits) is not int
        or bits < 0
        or bits & ~MASKS[address]
    ):
        raise ValueError("only pinned histogram masks and valid readbacks")
    return word & ~MASKS[address] | bits


def set_bits(dev, address, bits):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 histogram only")
    dev.wr(address, masked(address, dev.rr(address), bits))
    value = dev.rr(address)
    masked(address, value, 0)
    if value & MASKS[address] != bits:
        raise RuntimeError("histogram mask readback failed")


def reset(dev):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 histogram only")
    for bits in (0, 1 << 29, 0):
        dev.wr(RESET, masked(RESET, dev.rr(RESET), bits))
    word = dev.rr(RESET)
    masked(RESET, word, 0)
    if word & MASKS[RESET]:
        raise RuntimeError("histogram reset remained asserted")


def banks(dev, compare_views=False):
    selected = BANKS | OTHER_VIEWS if compare_views else BANKS
    return {
        name: list(struct.unpack("<11I", read_words(dev, base, 44)))
        for name, base in selected.items()
    }


def controls(dev):
    return {
        hex(address): struct.unpack("<I", read_words(dev, address, 4))[0] & 7
        for address in (CONTROL, 0x83092004)
    }


def mib_sample(dev):
    opened = time.monotonic()
    values, midpoint = mib.sample(dev, MIB_OFFSETS, 0)
    closed = time.monotonic()
    if any(values.get(offset) is None for offset in MIB_OFFSETS):
        raise ValueError("missing source-named histogram crosscheck counter")
    return {"values": values, "opened_s": opened, "midpoint_s": midpoint, "closed_s": closed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-histogram", action="store_true")
    parser.add_argument("--channel", type=int, choices=CHANNELS, default=6)
    parser.add_argument(
        "--compare-views",
        action="store_true",
        help="read two traced index1 windows too; no index1 writes",
    )
    parser.add_argument("--mib-crosscheck", action="store_true")
    parser.add_argument("--acknowledge-consuming-counters", action="store_true")
    args = parser.parse_args()
    if not args.enable_histogram:
        parser.error("explicit histogram reset/enable acknowledgment required")
    if args.mib_crosscheck and not args.acknowledge_consuming_counters:
        parser.error("MIB crosscheck requires exclusive consuming-counter acknowledgment")
    images = m.load_firmware(m.CHIP_MT7925, m.firmware_dir())
    check_image(images[1])
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "firmware_sha256": [hashlib.sha256(b).hexdigest() for b in images],
        "bank_addresses": {
            k: hex(v) for k, v in (BANKS | OTHER_VIEWS if args.compare_views else BANKS).items()
        },
        "channel": args.channel,
        "mib_offsets": MIB_OFFSETS if args.mib_crosscheck else [],
        "rows": [],
    }
    original = {}
    wrote = False
    with m.open_device("0846:9072") as dev:

        def snapshot():
            return banks(dev, args.compare_views)

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel <= 11 else "5GHz", args.channel, args.channel, 20)

        try:
            boot()
            out["code"] = verify(dev)
            if not all(r["matches"] for r in out["code"]):
                raise ValueError("live histogram code mismatch")
            out["threshold_labels_raw"] = list(
                struct.unpack("<10b", read_words(dev, THRESHOLD_ADDRESS, 12)[:10])
            )
            for address in MASKS:
                word = dev.rr(address)
                masked(address, word, 0)
                original[address] = word & MASKS[address]
            out["original_masked_bits"] = {hex(a): v for a, v in original.items()}
            if any(original.values()):
                raise RuntimeError("histogram already enabled or reset asserted")
            out["baseline_before"] = snapshot()
            if args.compare_views:
                out["baseline_controls"] = controls(dev)
            time.sleep(0.25)
            out["baseline_after"] = snapshot()
            for duration in DURATIONS:
                wrote = True
                reset(dev)
                row = {"duration_requested": duration, "after_reset": snapshot()}
                out["rows"].append(row)
                if args.mib_crosscheck:
                    row["mib_before"] = mib_sample(dev)
                start = time.monotonic()
                set_bits(dev, CONTROL, 5)
                if args.compare_views:
                    row["enabled_controls"] = controls(dev)
                time.sleep(duration)
                set_bits(dev, CONTROL, 0)
                if args.compare_views:
                    row["stopped_controls"] = controls(dev)
                row["host_enable_stop_seconds"] = time.monotonic() - start
                if args.mib_crosscheck:
                    row["mib_after"] = mib_sample(dev)
                    row["mib_delta"] = {
                        offset: (
                            row["mib_after"]["values"][offset] - row["mib_before"]["values"][offset]
                        )
                        & 0xFFFFFFFFFFFFFFFF
                        for offset in MIB_OFFSETS
                    }
                row["stopped"] = snapshot()
                time.sleep(0.05)
                row["stopped_repeat"] = snapshot()
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if wrote:
                out["restored"] = {}
                for address in MASKS:
                    try:
                        set_bits(dev, address, original[address])
                        out["restored"][hex(address)] = True
                    except Exception as exc:
                        out["restored"][hex(address)] = type(exc).__name__
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or not out.get("alive_after")
        or not out.get("cleanup_reload_alive")
        or any(v is not True for v in out.get("restored", {}).values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
