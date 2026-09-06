#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Passive MT7925 NAV/subchannel MIB characterization, not calibrated occupancy.

Only source-named, ROM-mapped UNI offsets; no TX or direct counter reads.
Optional reads of four source-defined MIB configuration words, never writes.
Normal firmware reload on exit. Width-invalid fields retained as raw evidence.
"""

import argparse
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import usb.core

import mt7921u as m
from research import mt7925_mib_characterize as mib

OFFSETS = (
    0,
    2,
    7,
    11,
    12,
    13,
    17,
    18,
    19,
    20,
    52,
    84,
    91,
    92,
    93,
    95,
    96,
    97,
    98,
    99,
    100,
    101,
    102,
)

PLANS = {
    "width": (
        (36, 36, 20),
        (36, 38, 40),
        (36, 42, 80),
        (48, 42, 80),
        (36, 50, 160),
        (64, 50, 160),
        (36, 36, 20),
    ),
    "primary80": tuple((primary, 42, 80) for primary in (36, 40, 44, 48, 36)),
    "centers80": ((36, 42, 80), (52, 58, 80), (100, 106, 80), (149, 155, 80), (36, 42, 80)),
}
CONTROL_REGISTERS = (0x820ED000, 0x820ED004, 0x820ED008, 0x820ED010)


def control_words(dev):
    """Read four source-defined configuration words, not any counter values."""
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925-only MIB control words")
    result = {}
    for address in CONTROL_REGISTERS:
        word = dev.rr(address)
        if type(word) is not int or not 0 <= word < 0xFFFFFFFF:
            raise ValueError("invalid MIB control word")
        result[hex(address)] = hex(word)
    return result


def width_summary(delta, width):
    """Retain index labels, not unverified physical channel assignments or units."""
    if type(width) is not int or width not in (20, 40, 80, 160):
        raise ValueError("only tested widths 20/40/80/160 allowed")
    active = width // 20
    return {
        "ed_enabled_width_indices": {i: delta[95 + i] for i in range(active)},
        "ed_outside_enabled_width_indices": {i: delta[95 + i] for i in range(active, 8)},
        "secondary_cca_within_width": {
            k: delta[k] for k, minimum in ((91, 40), (92, 80), (93, 160)) if width >= minimum
        },
        "idle_at_16bit_limit": delta[7] >= 65535,
        "physical_channel_mapping_validated": False,
        "units": "raw counter ticks, not calibrated percentages",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-consuming-counters", action="store_true")
    parser.add_argument("--suite", choices=tuple(PLANS), default="width")
    parser.add_argument(
        "--read-controls",
        action="store_true",
        help="read four MIB configuration words; no direct counter reads",
    )
    args = parser.parse_args()
    if not args.acknowledge_consuming_counters:
        parser.error("exclusive counter ownership and consuming-read acknowledgment required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "passive source/ROM-mapped MIB subchannel counters; offset94 excluded because translation=ffff; no direct counter reads",
        "suite": args.suite,
        "read_controls": args.read_controls,
        "windows": [],
        "idle_cadence": [],
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        out["firmware_sha256"] = [hashlib.sha256(image).hexdigest() for image in images]

        def sample(offsets=OFFSETS):
            values, at = mib.sample(dev, offsets, 0)
            if any(v is None for v in values.values()):
                raise ValueError("missing MIB value")
            return {"values": values, "host_monotonic": at}

        def collect(seconds):
            start = time.monotonic()
            transfers, good, bad = 0, 0, 0
            while time.monotonic() - start < seconds and transfers < 4096:
                try:
                    raw = bytes(dev.rx_read(timeout=10))
                except usb.core.USBTimeoutError:
                    continue
                transfers += 1
                decoded = m.decoder_for(dev)(raw)
                if decoded and decoded.get("frame"):
                    bad += bool(decoded.get("fcs_err"))
                    good += not bool(decoded.get("fcs_err"))
            return {
                "transfers": transfers,
                "good": good,
                "bad": bad,
                "seconds": time.monotonic() - start,
                "limit_reached": transfers == 4096,
            }

        try:
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            for control, center, width in PLANS[args.suite]:
                dev.tune("5GHz", control, center, width)
                collect(0.2)
                controls = control_words(dev) if args.read_controls else None
                for _ in range(2):
                    row = {"control": control, "center": center, "width": width, "before": sample()}
                    if controls is not None:
                        row["mib_control_words"] = controls
                    out["windows"].append(row)
                    row["capture"] = collect(1)
                    row["after"] = sample()
                    row["delta"] = {
                        k: row["after"]["values"][k] - row["before"]["values"][k] for k in OFFSETS
                    }
                    row["width_summary"] = width_summary(row["delta"], width)
            for delay in (0, 0.002, 0.01, 0.1, 0.5, 1) if args.suite == "width" else ():
                row = {"delay_requested": delay, "before": sample((7,))}
                out["idle_cadence"].append(row)
                time.sleep(delay)
                row["after"] = sample((7,))
                row["delta"] = row["after"]["values"][7] - row["before"]["values"][7]
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            dev.bringup(*images, log=lambda *_: None)
            out["cleanup_reload_alive"] = dev.alive()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
