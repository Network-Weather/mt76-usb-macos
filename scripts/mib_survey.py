#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""How busy is this channel, including the energy we cannot demodulate?

Reports channel occupancy from the chip's own CCA counters rather than from frames, so the
busy figure includes energy the sniffer never resolves: distant APs, hidden nodes, non-Wi-Fi
interferers. Each dwell also sums the airtime of the frames that *were* decoded, so both
numbers appear side by side. The gap between them is the part of the channel a frame-counting
sniffer is blind to, and it is why this script exists. Measured 2026-09-03 on 2.4 GHz
channel 6: 1,184,019 us of occupancy against 972,163 us of decoded airtime over 12 s.

The counters are read over MCU_EXT_CMD_GET_MIB_INFO. **The MIB registers do not work on this
part** -- every duration counter reads zero however it is armed, which is recorded with its
diagnosis in NEGATIVE_RESULTS.md; `--registers` still reads them so that result stays
reproducible. The MCU offsets are this chip's own numbering, established by sweep and
corroborated against the vendor enum; see docs/FIRMWARE_RECON.md and scripts/mcu_stats.py.

Passive receive only: nothing is transmitted, and with the default MCU path nothing is
written at all.

Usage: mib_survey.py 2.4GHz:6 5GHz:36:36:20 [--seconds 5] [--registers]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import mcu_stats as mcs  # noqa: E402
import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = m.firmware_dir()
READ_TIMEOUT_MS = 250
MCU_TIMEOUT_MS = 700

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


def mcu_counters(dev, band_idx: int = 0) -> dict[str, int | None]:
    """The occupancy counters, over the MCU. Free-running, so callers difference them."""
    out = {}
    for offs, name in mcs.MIB_OFFSETS_MT7921.items():
        try:
            body = dev.reply_body(
                dev.mcu_cmd_word(
                    m.MCU_EXT_CMD(mcs.MCU_EXT_CMD_GET_MIB_INFO),
                    struct.pack("<IIQ", band_idx, offs, 0),
                    timeout=MCU_TIMEOUT_MS,
                )
            )
            out[name] = mcs.parse_mt7921_value(body)
        except (m.McuError, RuntimeError):
            out[name] = None
    return out


def dwell(
    dev, band: str, control: int, center: int, width: int, secs: float, use_registers: bool = False
) -> dict:
    dev.tune(band, control, center, width)
    before = mcu_counters(dev)
    if use_registers:
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
    after = mcu_counters(dev)
    mcu = {
        k: (after[k] - before[k]) if (after[k] is not None and before[k] is not None) else None
        for k in after
    }
    busy_us = mcu.get("p_cca_time_us")
    counters = read_counters(dev) if use_registers else dict.fromkeys(COUNTERS, 0)
    result = {
        "target": f"{band}:{control}",
        "center": center,
        "width_mhz": width,
        "dwell_us": round(elapsed_us),
        "mcu_counters": mcu,
        "busy_fraction": round(busy_us / elapsed_us, 4) if (busy_us and elapsed_us) else None,
        "frames_decoded": frames,
        "decoded_airtime_us": round(decoded_airtime_us),
        # The number this script exists to produce. Positive means the hardware counted
        # occupancy the frame decoder never saw. Small negatives are expected and are not an
        # error: rxd.airtime_us models preamble plus payload at the decoded rate, so a
        # per-frame overestimate of a few microseconds accumulates over hundreds of frames.
        # Read the sign as "the decoder saw essentially all of it", not as a fault. Measured
        # 2026-09-03: +149,217 us on 2.4 GHz channel 6 against -8,836 us on 5 GHz channel 36
        # in the same run.
        "undecoded_busy_us": round(busy_us - decoded_airtime_us) if busy_us else None,
        "usb_errors": usb_errors,
        "warnings": [],
    }
    if use_registers:
        result["register_counters_raw"] = counters
        warn = plausible(counters)
        if warn:
            result["warnings"].append(f"registers: {warn}")
    if busy_us is None:
        result["warnings"].append("the MCU did not return a CCA counter")
        return result
    # A counter wrap over a short dwell would also land here, which is why the wrap period is
    # stated above: at 1 us/tick nothing under 16 s can wrap once.
    if busy_us > elapsed_us:
        result["warnings"].append(
            f"busy {busy_us:.0f} us exceeds the {elapsed_us:.0f} us dwell: the tick is not "
            f"1 us, the counter wrapped, or the block is not what we think it is"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("targets", nargs="+", type=parse_target)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument(
        "--registers",
        action="store_true",
        help="also read the MIB registers, which are known dead on this part "
        "(NEGATIVE_RESULTS.md); kept so that result stays reproducible",
    )
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
        if args.registers:
            arm_counters(dev)
        for band, control, center, width in args.targets:
            runs.append(dwell(dev, band, control, center, width, args.seconds, args.registers))
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
