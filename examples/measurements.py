#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Compose installed APIs: passive channel6 capture and raw interval measurements.

Run after installing the package: python examples/measurements.py --usb-id 0846:9072
Uses checksum-pinned firmware from MT76_FW_DIR. No research imports or RF transmit.
Output contains aggregate counts only, not frames, addresses, SSIDs or CSI arrays.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time

import mt7921u as m
from mt76_measurements import Counter, read_counters, read_thermal
from mt76_session import AcquisitionSession, SessionError


def collect(session, seconds=10, emit=print):
    """Consume one caller-owned running session; caller must stop it before USB close.

    No concurrent retunes, consumers or measurement callers in this small example.
    A callback serializes USB commands, not the hardware sampling clocks. The C
    equivalent is examples/measurements.c. Errors propagate; never export a fake zero.
    """
    if type(seconds) is not int or not 1 <= seconds <= 60:
        raise ValueError("seconds must be an integer in 1..60")
    started = time.monotonic()
    next_sample = started
    frames = 0
    while time.monotonic() - started < seconds:
        packet = session.read(timeout=0.05)
        if packet is not None:
            frames += 1  # Classified RX packets, not a good-FCS decode guarantee.
        while session.read(timeout=0, events=True) is not None:
            pass
        before = session.snapshot()
        if before["state"] != "running":
            raise SessionError("acquisition worker stopped")
        if time.monotonic() < next_sample:
            continue
        counters, thermal = session.call(
            lambda dev: (
                read_counters(dev, (Counter.RX_MPDU, Counter.PRIMARY_CCA)),
                read_thermal(dev),
            )
        )
        after = session.snapshot()
        if (
            after["state"] != "running"
            or after["epoch_ns"] != before["epoch_ns"]
            or after["channel_generation"] != before["channel_generation"]
        ):
            raise SessionError("measurement context changed")
        emit(
            json.dumps(
                {
                    "event": "measurement",
                    "schema": 1,
                    "epoch_ns": after["epoch_ns"],
                    "channel_generation": after["channel_generation"],
                    "requested_channel": after["requested_channel"],
                    "frames_consumed": frames,
                    "counter_opened_us": counters.opened_us,
                    "counter_closed_us": counters.closed_us,
                    "counters": [
                        {
                            "name": r.descriptor.name,
                            "raw": r.raw,
                            "unit": int(r.descriptor.unit),
                            "tick_ns": r.descriptor.tick_ns,
                        }
                        for r in counters.readings
                    ],
                    "reported_temperature_c": thermal.reported_temperature_c,
                    "thermal_opened_us": thermal.opened_us,
                    "thermal_closed_us": thermal.closed_us,
                    "channel_busy_fraction": None,  # Unknown duration scaling/coverage.
                    "session": after,  # Queue loss and command failures remain visible.
                }
            )
        )
        next_sample = time.monotonic() + 1
    return frames


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb-id", required=True, choices=("0e8d:7961", "0846:9072"))
    parser.add_argument("--seconds", type=int, choices=range(1, 61), default=10)
    args = parser.parse_args(argv)
    with m.open_device(args.usb_id) as dev:
        patch, ram = m.load_firmware(dev.CHIP)
        dev.bringup(patch, ram, log=lambda *_: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        dev.tune("2.4GHz", 6)
        print(
            json.dumps(
                {
                    "event": "ready",
                    "chip": dev.CHIP,
                    "patch_sha256": hashlib.sha256(patch).hexdigest(),
                    "ram_sha256": hashlib.sha256(ram).hexdigest(),
                }
            ),
            flush=True,
        )
        # The inner context joins the USB worker before the outer closes USB.
        with AcquisitionSession(dev) as session:
            frames = collect(session, args.seconds)
    return 0 if frames else 2  # Zero received packets is inconclusive, not an RX pass.


if __name__ == "__main__":
    raise SystemExit(main())
