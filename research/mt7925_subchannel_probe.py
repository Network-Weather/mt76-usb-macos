#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Passive MT7925 NAV/subchannel MIB characterization, not calibrated occupancy.

Only source-named, ROM-mapped UNI offsets; no TX or direct register reads.
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
    args = parser.parse_args()
    if not args.acknowledge_consuming_counters:
        parser.error("exclusive counter ownership and consuming-read acknowledgment required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "passive source/ROM-mapped MIB subchannel counters; offset94 excluded because translation=ffff; no raw register reads",
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
            for control, center, width in (
                (36, 36, 20),
                (36, 38, 40),
                (36, 42, 80),
                (48, 42, 80),
                (36, 50, 160),
                (64, 50, 160),
                (36, 36, 20),
            ):
                dev.tune("5GHz", control, center, width)
                collect(0.2)
                for _ in range(2):
                    row = {"control": control, "center": center, "width": width, "before": sample()}
                    out["windows"].append(row)
                    row["capture"] = collect(1)
                    row["after"] = sample()
                    row["delta"] = {
                        k: row["after"]["values"][k] - row["before"]["values"][k] for k in OFFSETS
                    }
                    row["width_summary"] = width_summary(row["delta"], width)
            for delay in (0, 0.002, 0.01, 0.1, 0.5, 1):
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
