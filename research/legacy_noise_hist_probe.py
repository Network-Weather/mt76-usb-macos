#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded MT7961 legacy PHY histogram, normal monitor mode only.

Firmware 0x936f16 defines reset/enable/freeze; callers request exactly11 bins.
Only three fixed volatile masks are changed and restored, then normal reload.
Passive by default. Explicit --stimulus plus TX acknowledgment permits at most
12 synthetic no-ACK frames from MT7925, with exact good-FCS receipt checks.
No arbitrary addresses/values, RF-test entry, NVM, or capture export.
Exclusive radio ownership required: this resets shared PHY histogram state.
Threshold labels are firmware constants, not a demonstrated dBm calibration.
"""

import argparse
import collections
import contextlib
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.mt7925_tx_probe import controlled_frame
from research.phy_tx_probe import descriptor, program_rate
from scripts import mcu_stats

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
    readback = dev.rr(address)
    masked_value(address, readback, 0)
    if readback & MASKS[address] != bits:
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


def cca_sample(dev):
    """Existing MT7961 primary CCA counter; MCU wait may consume RX frames."""
    opened = time.monotonic()
    raw = dev.mcu_cmd_word(m.MCU_EXT_CMD(0x5A), struct.pack("<IIQ", 0, 11, 0), timeout=1000)
    closed = time.monotonic()
    value = mcu_stats.parse_mt7921_value(dev.reply_body(raw))
    if value is None:
        raise ValueError("missing primary CCA counter")
    return value, opened, closed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-histogram", action="store_true")
    parser.add_argument("--stimulus", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--channel", type=int, choices=(1, 6, 11, 36, 149), default=36)
    parser.add_argument("--cca-crosscheck", action="store_true")
    args = parser.parse_args()
    if not args.enable_histogram:
        parser.error("explicit volatile histogram-write acknowledgment required")
    if args.stimulus and not args.acknowledge_experimental_transmit:
        parser.error("stimulus requires explicit TX acknowledgment")
    if args.stimulus and args.channel != 36:
        parser.error("controlled TX is pinned to channel36")
    out = {
        "tool": "legacy_noise_hist_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "firmware_threshold_labels": THRESHOLDS,
        "channel": args.channel,
        "maximum_submissions": 12 if args.stimulus else 0,
        "submitted": 0,
        "rows": [],
    }
    original = {}
    wrote = False
    with contextlib.ExitStack() as stack:
        dev = stack.enter_context(m.open_device("0e8d:7961"))
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        tx = stack.enter_context(m.open_device("0846:9072")) if args.stimulus else None
        tx_images = m.load_firmware(tx.CHIP, m.firmware_dir()) if tx else None
        marker = b"\xdd\x0c\x02NW\x01" + os.urandom(8)
        frames = {i: controlled_frame(i) + marker for i in range(12)} if tx else {}
        rate = (1 << 10) | (2 << 6) | 8

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            band = "2.4GHz" if args.channel <= 11 else "5GHz"
            dev.tune(band, args.channel, args.channel, 20)

        def boot_tx():
            with contextlib.redirect_stdout(sys.stderr):
                tx.bringup(*tx_images, log=lambda *_: None)
            tx.set_monitor_mode()
            tx.set_sniffer(True)
            tx.tune("5GHz", 36, 36, 20)

        def receive(duration):
            counts = collections.Counter()
            decoder = m.decoder_for(dev)
            started = time.monotonic()
            deadline = started + duration
            transfers = 0
            first = out["submitted"]
            seen = set()
            phy = collections.Counter()
            next_tx = started
            while time.monotonic() < deadline and transfers < 512:
                now = time.monotonic()
                if tx and out["submitted"] < first + 4 and now >= next_tx:
                    seq = out["submitted"]
                    body = descriptor(tx, frames[seq], seq, rate) + frames[seq]
                    wire = struct.pack("<I", len(body)) + body
                    wire += bytes((-len(wire)) % 4 + 4)
                    tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                    out["submitted"] += 1
                    next_tx = time.monotonic() + 0.05
                try:
                    raw = bytes(dev.rx_read(timeout=20))
                except usb.core.USBTimeoutError:
                    continue
                transfers += 1
                packet = decoder(raw)
                counts[packet.get("pkt_type_name", "unknown") if packet else "short"] += 1
                if tx and packet and not packet.get("fcs_err"):
                    for seq in range(first, first + 4):
                        if packet.get("frame") == frames[seq]:
                            seen.add(seq)
                            fields = packet.get("phy", {})
                            phy[
                                tuple(fields.get(k) for k in ("mode_name", "mcs", "nss", "bw_mhz"))
                            ] += 1
            result = {
                "elapsed_seconds": time.monotonic() - started,
                "transfers": transfers,
                "packet_types": dict(counts),
                "limit_reached": transfers == 512,
            }
            if tx:
                result["exact_frames"] = len(seen)
                result["submitted"] = out["submitted"] - first
                result["phy"] = [
                    {"mode": k[0], "mcs": k[1], "nss": k[2], "width_mhz": k[3], "count": n}
                    for k, n in phy.items()
                ]
            return result

        try:
            boot()
            if tx:
                boot_tx()
                program_rate(tx, rate)
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
            if tx and not out["baseline_window"]["exact_frames"]:
                raise RuntimeError("no independent baseline receipt")
            for duration in (0.25, 1.0):
                row = {"requested_seconds": duration}
                out["rows"].append(row)
                wrote = True
                set_bits(dev, CONTROL, 0)
                reset(dev)
                row["after_reset"] = bins(dev)
                set_bits(dev, OPTIONS, 0x30000)
                if args.cca_crosscheck:
                    cca_before, cca_open, cca_open_end = cca_sample(dev)
                enable_open = time.monotonic()
                set_bits(dev, CONTROL, 5)
                enable_closed = time.monotonic()
                row["enabled_masked_bits"] = {
                    f"{a:08x}": dev.rr(a) & mask for a, mask in MASKS.items()
                }
                row["window"] = receive(duration)
                stop_open = time.monotonic()
                set_bits(dev, CONTROL, 0)
                stop_closed = time.monotonic()
                row["enabled_seconds_bounds"] = (
                    stop_open - enable_closed,
                    stop_closed - enable_open,
                )
                if args.cca_crosscheck:
                    cca_after, cca_close, cca_close_end = cca_sample(dev)
                    row["cca_crosscheck"] = {
                        "delta_us": (cca_after - cca_before) % (1 << 32),
                        "sample_seconds_bounds": (
                            cca_close - cca_open_end,
                            cca_close_end - cca_open,
                        ),
                        "extra_window_seconds_upper": (
                            enable_closed - cca_open + cca_close_end - stop_open
                        ),
                    }
                row["stopped_bins"] = bins(dev)
                row["stopped_repeat"] = bins(dev)
                if tx and not row["window"]["exact_frames"]:
                    raise RuntimeError("no independent enabled receipt")
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
            if tx:
                try:
                    boot_tx()
                    out["tx_cleanup_reload_alive"] = tx.alive()
                except Exception as exc:
                    out["tx_cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or "stop_error_type" in out
        or (wrote and not all(v is True for v in out["restore"].values()))
        or not out.get("cleanup_reload_alive")
        or (args.stimulus and not out.get("tx_cleanup_reload_alive"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
