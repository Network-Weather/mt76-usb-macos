#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Correlate MT7925 UNI MIB counters with passive frame observations.

The script never transmits.  It tunes an already-supported MT7925 USB adapter,
samples selected UNI GET_MIB_INFO counters on both sides of each dwell, and
collects decoded frame count, aggregate-aware airtime, and decoded PHY width.

Usage:
  mt7925_mib_characterize.py 2.4GHz:1 5GHz:36:36:20 \
      5GHz:36:42:80 --seconds 8
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import struct
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

MCU_UNI_CMD_GET_MIB_INFO = 0x22
UNI_CMD_MIB_DATA = 0
UNI_MIB_ENTRY_LEN = 8
READ_TIMEOUT_MS = 200
DEFAULT_OFFSETS = (0, 2, 7, 11, 12, 13, 16, 17, 18, 19, 20, 32)


def parse_target(text: str) -> tuple[str, int, int, int]:
    parts = text.split(":")
    if len(parts) not in (2, 3, 4) or parts[0] not in m.CHAN_BAND:
        raise argparse.ArgumentTypeError(f"bad target {text!r}; want BAND:CONTROL[:CENTER[:WIDTH]]")
    try:
        control = int(parts[1])
        width = int(parts[3]) if len(parts) == 4 else 20
        center = int(parts[2]) if len(parts) >= 3 else m.center_channel(parts[0], control, width)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad numeric field in {text!r}") from exc
    if width not in m.WIDTH_TO_SNIFFER_BW:
        raise argparse.ArgumentTypeError(f"width {width} not in {sorted(m.WIDTH_TO_SNIFFER_BW)}")
    if center is None:
        raise argparse.ArgumentTypeError(
            f"target {text!r} needs an explicit center channel at {width} MHz"
        )
    return parts[0], control, center, width


def parse_offsets(text: str) -> tuple[int, ...]:
    try:
        values = tuple(dict.fromkeys(int(v) for v in text.split(",")))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("offsets must be comma-separated integers") from exc
    if not values or any(v < 0 or v > 511 for v in values):
        raise argparse.ArgumentTypeError("offsets must be between 0 and 511")
    return values


def build_request(band_idx: int, offsets: tuple[int, ...]) -> bytes:
    header = struct.pack("<B3x", band_idx)
    entries = b"".join(
        struct.pack("<HHI", UNI_CMD_MIB_DATA, UNI_MIB_ENTRY_LEN, offs) for offs in offsets
    )
    return header + entries


def parse_counter(body: bytes, offs: int) -> int | None:
    for at in range(0, max(0, len(body) - 12), 2):
        _tag, length, echoed = struct.unpack_from("<HHI", body, at)
        if echoed == offs and length in (UNI_MIB_ENTRY_LEN, 16) and at + 16 <= len(body):
            return struct.unpack_from("<Q", body, at + 8)[0]
    return None


def sample(dev, offsets: tuple[int, ...], band_idx: int) -> tuple[dict[int, int | None], float]:
    """Read all offsets in one UNI request, giving them one observation window."""
    opened = time.monotonic()
    try:
        body = dev.reply_body(
            dev.mcu_uni(
                MCU_UNI_CMD_GET_MIB_INFO,
                build_request(band_idx, offsets),
                query=True,
            )
        )
        values = {offs: parse_counter(body, offs) for offs in offsets}
    except (m.McuError, RuntimeError, usb.core.USBError):
        values = dict.fromkeys(offsets)
    closed = time.monotonic()
    return values, (opened + closed) / 2


def dwell(dev, target, seconds: float, offsets: tuple[int, ...], band_idx: int) -> dict:
    band, control, center, width = target
    dev.tune(band, control, center, width)
    time.sleep(0.5)

    dropped_before = getattr(dev, "mcu_wait_dropped_frames", 0)
    before, before_at = sample(dev, offsets, band_idx)

    decode = m.decoder_for(dev)
    aggregates = rxd.AggregationTracker()
    decoded_airtime_us = 0.0
    decoded_frames = 0
    usb_errors = 0
    read_timeouts = 0
    by_phy_width = collections.Counter()

    def bill(done) -> float:
        return sum(aggregate.airtime_us() or 0.0 for aggregate in done)

    started = time.monotonic()
    while time.monotonic() - started < seconds:
        try:
            raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
        except usb.core.USBTimeoutError:
            read_timeouts += 1
            continue
        except usb.core.USBError:
            usb_errors += 1
            continue
        if not raw:
            continue
        decoded = decode(raw)
        if not decoded or not decoded.get("frame"):
            continue
        decoded_frames += 1
        phy_width = (decoded.get("phy") or {}).get("bw_mhz", "unknown")
        by_phy_width[str(phy_width)] += 1
        parsed = rxd.parse_80211(decoded["frame"])
        decoded_airtime_us += bill(
            aggregates.feed(decoded, len(decoded["frame"]), parsed.get("addr2"))
        )
    decoded_airtime_us += bill(aggregates.flush())
    frame_window_us = (time.monotonic() - started) * 1e6

    after, after_at = sample(dev, offsets, band_idx)
    dropped = getattr(dev, "mcu_wait_dropped_frames", 0) - dropped_before
    elapsed_us = (after_at - before_at) * 1e6

    counters = {}
    for offs in offsets:
        first = before[offs]
        last = after[offs]
        delta = None if first is None or last is None else last - first
        counters[str(offs)] = {
            "before": first,
            "after": last,
            "delta": delta,
            "sample_interval_us": round(elapsed_us),
            "rate_per_s": (
                None if delta is None or elapsed_us <= 0 else round(delta * 1e6 / elapsed_us, 3)
            ),
            "fraction_if_us": (
                None if delta is None or elapsed_us <= 0 else round(delta / elapsed_us, 6)
            ),
        }

    return {
        "target": f"{band}:{control}",
        "center": center,
        "width_mhz": width,
        "frame_window_us": round(frame_window_us),
        "decoded_frames": decoded_frames,
        "decoded_aggregates": aggregates.completed,
        "decoded_airtime_us": round(decoded_airtime_us),
        "decoded_airtime_fraction": round(decoded_airtime_us / frame_window_us, 6),
        "decoded_frames_by_phy_width_mhz": dict(sorted(by_phy_width.items())),
        "frames_dropped_by_mcu_reads": dropped,
        "usb_errors": usb_errors,
        "read_timeouts": read_timeouts,
        "counters": counters,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("targets", nargs="+", type=parse_target)
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--band-idx", type=int, default=0)
    parser.add_argument(
        "--offsets",
        type=parse_offsets,
        default=DEFAULT_OFFSETS,
        help="comma-separated offsets (default: %(default)s)",
    )
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("--seconds must be between 1 and 60")

    dev = m.open_device()
    if dev.CHIP != "mt7925" or not hasattr(dev, "mcu_uni"):
        parser.error(f"attached device is {dev.CHIP}, not an MT7925 UNI device")
    patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
    runs = []
    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        for target in args.targets:
            runs.append(dwell(dev, target, args.seconds, args.offsets, args.band_idx))

    print(
        json.dumps(
            {
                "tool": "mt7925_mib_characterize",
                "mt76_usb_macos": m.__version__,
                "chip": dev.CHIP,
                "passive_receive_only": True,
                "offsets": list(args.offsets),
                "runs": runs,
            },
            indent=2,
        )
    )
    return 2 if any(run["usb_errors"] for run in runs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
