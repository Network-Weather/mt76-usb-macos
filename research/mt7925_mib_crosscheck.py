#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Compare MT7925 UNI MIB candidates with identified MT7921 counters.

Both attached radios passively observe the same primary 20 MHz channel. The
MT7925 captures frames and samples its candidate counters; the MT7921 samples
its already identified P_CCA_TIME and CCA_NAV_TX_TIME counters over the same
window. No frame is transmitted by this tool.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mt7925_mib_perturb as experiment  # noqa: E402

import mt7921u as m  # noqa: E402

DEFAULT_OFFSETS = (0, 2, 11, 12, 13, 17, 18, 19, 20)


def parse_target(text: str) -> tuple[str, int]:
    band, separator, channel_text = text.partition(":")
    if not separator or band not in m.CHAN_BAND:
        raise argparse.ArgumentTypeError(f"bad target {text!r}; want BAND:CHANNEL")
    try:
        channel = int(channel_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad channel in {text!r}") from exc
    if m.center_channel(band, channel, 20) is None:
        raise argparse.ArgumentTypeError(f"{band} has no 20 MHz channel {channel}")
    return band, channel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("targets", nargs="+", type=parse_target)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--repeats", type=int, default=1, choices=(1, 2, 3))
    parser.add_argument(
        "--offsets",
        type=experiment.mib.parse_offsets,
        default=DEFAULT_OFFSETS,
    )
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("--seconds must be between 1 and 60")

    adapters = m.describe_supported_devices()
    receivers = [entry for entry in adapters if entry["chip"] == m.CHIP_MT7925]
    references = [entry for entry in adapters if entry["chip"] == m.CHIP_MT7921]
    if not receivers or not references:
        print("need one MT7925 and one MT7921 adapter", file=sys.stderr)
        return 2

    rx_entry = receivers[0]
    ref_entry = references[0]
    rx = m.open_device_at(rx_entry["address"])
    reference = m.open_device_at(ref_entry["address"])
    rx_patch, rx_ram = m.load_firmware(rx.CHIP, m.firmware_dir())
    ref_patch, ref_ram = m.load_firmware(reference.CHIP, m.firmware_dir())
    runs = []
    failures: list[str] = []

    with rx, reference:
        rx.bringup(rx_patch, rx_ram, log=lambda *a: None)
        reference.bringup(ref_patch, ref_ram, log=lambda *a: None)
        for dev in (rx, reference):
            dev.set_monitor_mode()
            dev.set_sniffer(True)

        for band, channel in args.targets:
            for repeat in range(args.repeats):
                rx.tune(band, channel, channel, 20)
                reference.tune(band, channel, channel, 20)
                time.sleep(0.5)

                phase = {"target": f"{band}:{channel}", "repeat": repeat + 1}
                ready = threading.Barrier(2)
                worker = threading.Thread(
                    target=experiment.receive_phase,
                    args=(
                        rx,
                        "passive",
                        args.seconds,
                        args.offsets,
                        ready,
                        phase,
                        failures,
                    ),
                )
                worker.start()
                before, before_at = experiment.legacy_sample(reference)
                try:
                    ready.wait(timeout=10)
                except threading.BrokenBarrierError:
                    failures.append("radios did not rendezvous before the dwell")
                    worker.join(timeout=1)
                    break
                time.sleep(args.seconds)
                after, after_at = experiment.legacy_sample(reference)
                worker.join(timeout=args.seconds + 10)
                if worker.is_alive():
                    failures.append("MT7925 receiver thread did not finish")
                    break
                phase["mt7921_reference"] = experiment.legacy_result(
                    before, after, before_at, after_at
                )
                runs.append(phase)

    print(
        json.dumps(
            {
                "tool": "mt7925_mib_crosscheck",
                "passive_receive_only": True,
                "mt7925": rx_entry["usb_id"],
                "mt7921_reference": ref_entry["usb_id"],
                "offsets": list(args.offsets),
                "runs": runs,
                "failures": failures,
            },
            indent=2,
        )
    )
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
