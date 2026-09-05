#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded passive MT7961 legacy PHY histogram, normal monitor mode only.

Firmware 0x936f16 defines reset/enable/freeze; callers request exactly11 bins.
Only three fixed volatile masks are changed and restored, then normal reload.
No arbitrary addresses/values, RF-test entry, TX, NVM, or capture export.
Exclusive radio ownership required: this resets shared PHY histogram state.
Threshold labels are firmware constants, not a demonstrated dBm calibration.
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

CONTROL = 0x83082004
RESET = 0x83088230
OPTIONS = 0x83088234
MASKS = {CONTROL: 7, RESET: 1 << 29, OPTIONS: 0x30000}
BIN_REGISTERS = tuple(0x83088600 + i * 4 for i in range(11))
THRESHOLDS = (-92, -89, -86, -83, -80, -75, -70, -65, -60, -55)


def masked_value(address, current, bits):
    if (
        type(address) is not int
        or address not in MASKS
        or type(current) is not int
        or not 0 <= current < 0xFFFFFFFF
        or type(bits) is not int
        or bits < 0
        or bits & ~MASKS[address]
    ):
        raise ValueError("only mapped fixed registers and source-defined masks")
    return (current & ~MASKS[address]) | bits


def set_bits(dev, address, bits):
    dev.wr(address, masked_value(address, dev.rr(address), bits))
    if dev.rr(address) & MASKS[address] != bits:
        raise RuntimeError("histogram control readback failed")


def bins(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned MT7961 counter bank only")
    return [dev.rr(address) for address in BIN_REGISTERS]


def reset(dev):
    # Exact clear/set/clear pulse from 0x936f18..0x936f32.
    for bits in (0, 1 << 29, 0):
        # The reset bit may self-clear, so verify only the final clear state.
        dev.wr(RESET, masked_value(RESET, dev.rr(RESET), bits))
    if dev.rr(RESET) & MASKS[RESET]:
        raise RuntimeError("histogram reset remained asserted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-histogram", action="store_true")
    args = parser.parse_args()
    if not args.enable_histogram:
        parser.error("explicit volatile histogram-write acknowledgment required")
    out = {
        "tool": "legacy_noise_hist_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "firmware_threshold_labels": THRESHOLDS,
        "rows": [],
    }
    original = {}
    wrote = False
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        def receive(duration):
            counts = collections.Counter()
            decoder = m.decoder_for(dev)
            started = time.monotonic()
            deadline = started + duration
            transfers = 0
            while time.monotonic() < deadline and transfers < 512:
                try:
                    raw = bytes(dev.rx_read(timeout=20))
                except usb.core.USBTimeoutError:
                    continue
                transfers += 1
                packet = decoder(raw)
                counts[packet.get("pkt_type_name", "unknown") if packet else "short"] += 1
            return {
                "elapsed_seconds": time.monotonic() - started,
                "transfers": transfers,
                "packet_types": dict(counts),
                "limit_reached": transfers == 512,
            }

        try:
            boot()
            for address in MASKS:
                word = dev.rr(address)
                masked_value(address, word, 0)
                original[address] = word & MASKS[address]
            out["original_masked_bits"] = {f"{a:08x}": v for a, v in original.items()}
            if original[CONTROL] or original[RESET]:
                raise RuntimeError("histogram already enabled or reset asserted")
            out["baseline_before"] = bins(dev)
            out["baseline_window"] = receive(0.25)
            out["baseline_after"] = bins(dev)
            for duration in (0.25, 1.0):
                row = {"requested_seconds": duration}
                out["rows"].append(row)
                wrote = True
                set_bits(dev, CONTROL, 0)
                reset(dev)
                row["after_reset"] = bins(dev)
                set_bits(dev, OPTIONS, 0x30000)
                set_bits(dev, CONTROL, 5)
                row["enabled_masked_bits"] = {
                    f"{a:08x}": dev.rr(a) & mask for a, mask in MASKS.items()
                }
                row["window"] = receive(duration)
                set_bits(dev, CONTROL, 0)
                row["stopped_bins"] = bins(dev)
                row["stopped_repeat"] = bins(dev)
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if wrote:
                out["restore"] = {}
                # Stop first; restore other masks independently, enable state last.
                try:
                    set_bits(dev, CONTROL, 0)
                except Exception as exc:
                    out["stop_error_type"] = type(exc).__name__
                for address in (OPTIONS, RESET, CONTROL):
                    try:
                        set_bits(dev, address, original[address])
                        out["restore"][f"{address:08x}"] = True
                    except Exception as exc:
                        out["restore"][f"{address:08x}"] = type(exc).__name__
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or "stop_error_type" in out
        or (wrote and not all(v is True for v in out["restore"].values()))
        or not out.get("cleanup_reload_alive")
    )


if __name__ == "__main__":
    raise SystemExit(main())
