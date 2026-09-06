#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Six passive MT7925 windows demonstrating shared read-clear MIB ownership.

No TX or counter-control writes. Explicit opt-in because reads consume samples.
Normal firmware reload on exit; only anonymous frame counts are exported.
"""

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import usb.core

import mt7921u as m
from research import mt7925_mib_characterize as mib
from research.mt7925_mib_fields import paired_sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-consuming-counters", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_consuming_counters:
        parser.error("exclusive counter ownership and consuming-read acknowledgment required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "passive MT7925 counter ownership; no TX",
        "windows": [],
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def sample():
            values, at = mib.sample(dev, (0, 2), 0)
            if any(v is None for v in values.values()):
                raise ValueError("missing MIB value")
            return {"values": values, "host_monotonic": at}

        def direct():
            return paired_sample(dev)

        def collect():
            deadline = time.monotonic() + 1
            transfers, good, bad = 0, 0, 0
            while time.monotonic() < deadline and transfers < 2048:
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
                "limit_reached": transfers == 2048,
            }

        try:
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)
            collect()
            for order in (
                "firmware_first",
                "direct_first",
                "firmware_first",
                "direct_first",
                "firmware_first",
                "direct_first",
            ):
                row = {"order": order, "before": sample()}
                out["windows"].append(row)
                row["capture"] = collect()
                if order == "firmware_first":
                    row["after"] = sample()
                    row["direct"] = direct()
                else:
                    row["direct"] = direct()
                    row["after"] = sample()
                row["firmware_delta"] = {
                    k: row["after"]["values"][k] - row["before"]["values"][k] for k in (0, 2)
                }
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            dev.bringup(*images, log=lambda *_: None)
            out["cleanup_reload_alive"] = dev.alive()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
