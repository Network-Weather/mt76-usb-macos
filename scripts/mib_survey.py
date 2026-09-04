#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""How busy is this channel, including the energy we cannot demodulate?

Reads the MAC's own airtime counters over the dwell rather than counting frames. The chip
accumulates CCA busy, TX, RX and OBSS time in hardware, so the busy figure includes energy
the sniffer never resolves into a frame: distant APs, hidden nodes, non-Wi-Fi interferers.
Each dwell also sums the airtime of the frames that *were* decoded, so the report shows both
numbers side by side. The gap between them is the part of the channel a frame-counting
sniffer is blind to, and it is the reason this script exists.

Passive receive only; no frame is transmitted and no register outside the MIB and RMAC
counter blocks is written. Output is per-channel totals with no BSSIDs or payloads.

See docs/FIRMWARE_RECON.md (Spike A) for what must be true before these numbers are trusted.
Upstream reference: mt792x_mac.c:226 mt792x_phy_update_channel() reads the same four
counters for cfg80211 survey dump, and mt792x_mac.c:195 mt792x_mac_reset_counters() is the
clear sequence reproduced here.

Usage: mib_survey.py 2.4GHz:6 5GHz:36:36:20 [--seconds 5]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = m.firmware_dir()
READ_TIMEOUT_MS = 250

# Register addresses, band 0, transcribed from mt76 mt792x_regs.h at baseline c5a3bd91.
# Band 1 exists in the header (MIB 0x820fd000, RMAC 0x820f5000) but the USB parts are
# single-band, so only band 0 is defined here.
MT_WF_MIB_BASE = 0x820ED000  # MT_WF_MIB_BASE(0)
MT_MIB_SCR1 = MT_WF_MIB_BASE + 0x004  # MT_MIB_SCR1(0)
MT_MIB_TXDUR_EN = 1 << 8  # MT_MIB_TXDUR_EN
MT_MIB_RXDUR_EN = 1 << 9  # MT_MIB_RXDUR_EN
MT_MIB_SDR9 = MT_WF_MIB_BASE + 0x02C  # MT_MIB_SDR9(0), CCA busy
MT_MIB_SDR36 = MT_WF_MIB_BASE + 0x054  # MT_MIB_SDR36(0), TX airtime
MT_MIB_SDR37 = MT_WF_MIB_BASE + 0x058  # MT_MIB_SDR37(0), RX airtime

MT_WF_RMAC_BASE = 0x820E5000  # MT_WF_RMAC_BASE(0)
MT_WF_RMAC_MIB_AIRTIME0 = MT_WF_RMAC_BASE + 0x380  # MT_WF_RMAC_MIB_AIRTIME0(0)
MT_WF_RMAC_MIB_AIRTIME14 = MT_WF_RMAC_BASE + 0x3B8  # MT_WF_RMAC_MIB_AIRTIME14(0), OBSS
MT_WF_RMAC_MIB_TIME0 = MT_WF_RMAC_BASE + 0x3C4  # MT_WF_RMAC_MIB_TIME0(0)
MT_WF_RMAC_MIB_RXTIME_CLR = 1 << 31  # MT_WF_RMAC_MIB_RXTIME_CLR

# All four counters are 24-bit fields (MT_MIB_SDR9_BUSY_MASK, SDR36_TXTIME_MASK,
# SDR37_RXTIME_MASK, MT_MIB_OBSSTIME_MASK are each GENMASK(23, 0)).
COUNTER_MASK = (1 << 24) - 1
COUNTER_WRAP_US = 1 << 24  # 16.78 s at 1 us/tick; dwells are bounded well below this

# mt76 adds these fields straight into mt76_channel_state's cc_busy/cc_tx/cc_rx, which
# cfg80211 reports as milliseconds after dividing by 1000 (mt76/mac80211.c), so upstream
# treats one tick as one microsecond. That is an inherited assumption, not something this
# script has measured; acceptance criterion 3 in docs/FIRMWARE_RECON.md is the check that
# busy time never exceeds wall-clock dwell time, which is what would falsify it.
US_PER_TICK = 1.0

COUNTERS = {
    "cca_busy": (MT_MIB_SDR9, "MT_MIB_SDR9 bits 23:0: CCA busy time"),
    "tx_airtime": (MT_MIB_SDR36, "MT_MIB_SDR36 bits 23:0: TX airtime"),
    "rx_airtime": (MT_MIB_SDR37, "MT_MIB_SDR37 bits 23:0: RX airtime"),
    "obss_airtime": (MT_WF_RMAC_MIB_AIRTIME14, "MT_WF_RMAC_MIB_AIRTIME14 bits 23:0: OBSS"),
}


def parse_target(text: str) -> tuple[str, int, int, int]:
    parts = text.split(":")
    if len(parts) < 2 or parts[0] not in m.CHAN_BAND or not all(p.isdigit() for p in parts[1:]):
        raise argparse.ArgumentTypeError(f"bad target {text!r}; want BAND:CONTROL[:CENTER[:WIDTH]]")
    control = int(parts[1])
    center = int(parts[2]) if len(parts) > 2 else control
    width = int(parts[3]) if len(parts) > 3 else 20
    if width not in m.WIDTH_TO_SNIFFER_BW:
        raise argparse.ArgumentTypeError(f"width {width} not in {sorted(m.WIDTH_TO_SNIFFER_BW)}")
    return parts[0], control, center, width


def arm_counters(dev) -> None:
    """Enable TX/RX duration accounting (mt792x_mac.c:299)."""
    dev.set_bits(MT_MIB_SCR1, MT_MIB_TXDUR_EN | MT_MIB_RXDUR_EN)


def reset_counters(dev) -> None:
    """mt792x_mac_reset_counters: the SDRs clear on read, the RMAC ones on an explicit bit."""
    for addr, _why in COUNTERS.values():
        if addr != MT_WF_RMAC_MIB_AIRTIME14:
            dev.rr(addr)
    dev.set_bits(MT_WF_RMAC_MIB_TIME0, MT_WF_RMAC_MIB_RXTIME_CLR)
    dev.set_bits(MT_WF_RMAC_MIB_AIRTIME0, MT_WF_RMAC_MIB_RXTIME_CLR)


def read_counters(dev) -> dict[str, int]:
    return {name: dev.rr(addr) & COUNTER_MASK for name, (addr, _why) in COUNTERS.items()}


def plausible(counters: dict[str, int]) -> str | None:
    """Acceptance criterion 1: reject the two readings that mean 'nothing is mapped here'."""
    values = list(counters.values())
    if all(v == 0 for v in values):
        return "every counter read 0: the block is unmapped, unarmed, or the dwell saw nothing"
    if all(v == COUNTER_MASK for v in values):
        return "every counter read all-ones: the register block is almost certainly unmapped"
    return None


def dwell(dev, band: str, control: int, center: int, width: int, secs: float) -> dict:
    dev.tune(band, control, center, width)
    reset_counters(dev)
    started = time.monotonic()
    frames = 0
    usb_errors = 0
    decoded_airtime_us = 0.0
    decode = m.decoder_for(dev)
    while time.monotonic() - started < secs:
        try:
            raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
        except usb.core.USBError:
            usb_errors += 1
            continue
        if not raw:
            continue
        d = decode(raw)
        if not d or not d.get("frame"):
            continue
        frames += 1
        phy = d.get("phy") or {}
        air = rxd.airtime_us(len(d["frame"]), phy.get("mode"), phy.get("rate_mbps"))
        if air:
            decoded_airtime_us += air
    elapsed_us = (time.monotonic() - started) * 1e6
    counters = read_counters(dev)

    ticks_to_us = {k: v * US_PER_TICK for k, v in counters.items()}
    busy_us = ticks_to_us["cca_busy"]
    result = {
        "target": f"{band}:{control}",
        "center": center,
        "width_mhz": width,
        "dwell_us": round(elapsed_us),
        "counters_raw": counters,
        "counters_us": {k: round(v) for k, v in ticks_to_us.items()},
        "busy_fraction": round(busy_us / elapsed_us, 4) if elapsed_us else None,
        "frames_decoded": frames,
        "decoded_airtime_us": round(decoded_airtime_us),
        # The number this script exists to produce. Positive means the hardware counted
        # occupancy the frame decoder never saw.
        "undecoded_busy_us": round(busy_us - decoded_airtime_us),
        "usb_errors": usb_errors,
        "warnings": [],
    }
    warn = plausible(counters)
    if warn:
        result["warnings"].append(warn)
    # Acceptance criterion 3. A counter wrap over a short dwell would also land here, which
    # is why the wrap period is stated above: at 1 us/tick nothing under 16 s can wrap once.
    if busy_us > elapsed_us:
        result["warnings"].append(
            f"busy {busy_us:.0f} us exceeds the {elapsed_us:.0f} us dwell: the tick is not "
            f"1 us, the counter wrapped, or the block is not what we think it is"
        )
    if any(v >= COUNTER_MASK for v in counters.values()):
        result["warnings"].append("a counter saturated its 24-bit field; shorten --seconds")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("targets", nargs="+", type=parse_target)
    parser.add_argument("--seconds", type=float, default=5.0)
    args = parser.parse_args()
    # The 24-bit counters wrap after 16.78 s at the assumed tick, so a dwell must stay well
    # under that for the wrap check above to mean anything.
    if not 1 <= args.seconds <= 10:
        parser.error("--seconds must be between 1 and 10 (24-bit counters wrap at ~16.8 s)")

    dev = m.open_device()
    patch, ram = m.load_firmware(dev.CHIP, FW_DIR)
    runs = []
    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        arm_counters(dev)
        for band, control, center, width in args.targets:
            runs.append(dwell(dev, band, control, center, width, args.seconds))
    print(
        json.dumps(
            {
                "tool": "mib_survey",
                "mt76_usb_macos": m.__version__,
                "us_per_tick_assumed": US_PER_TICK,
                "runs": runs,
            },
            indent=2,
        )
    )
    return 1 if any(r["warnings"] for r in runs) else 0


if __name__ == "__main__":
    sys.exit(main())
