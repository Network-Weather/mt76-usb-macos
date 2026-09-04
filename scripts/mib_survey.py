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
#: A --registers dwell must stay clear of the 24-bit wrap above.
REGISTER_DWELL_MAX_S = 10.0
#: The MCU counter is 32-bit, so the ceiling here is patience, not arithmetic.
MCU_DWELL_MAX_S = 120.0

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


def read_mcu_offset(dev, offs: int, band_idx: int = 0) -> int | None:
    """One MIB counter over the MCU. Free-running, so callers difference two reads."""
    try:
        body = dev.reply_body(
            dev.mcu_cmd_word(
                m.MCU_EXT_CMD(mcs.MCU_EXT_CMD_GET_MIB_INFO),
                struct.pack("<IIQ", band_idx, offs, 0),
                timeout=MCU_TIMEOUT_MS,
            )
        )
    except (m.McuError, RuntimeError, usb.core.USBError):
        # USBError derives from OSError; an unimplemented offset simply never answers.
        return None
    return mcs.parse_mt7921_value(body)


def read_cca(dev, band_idx: int = 0) -> int | None:
    """Primary-channel CCA busy time, the one counter the dwell window must bracket."""
    return read_mcu_offset(dev, mcs.MIB_PRIMARY_CCA_TIME, band_idx)


def mcu_counters(dev, band_idx: int = 0) -> dict[str, int | None]:
    """The occupancy counters, over the MCU. Free-running, so callers difference them."""
    return {
        name: read_mcu_offset(dev, offs, band_idx) for offs, name in mcs.MIB_OFFSETS_MT7921.items()
    }


def dwell(
    dev, band: str, control: int, center: int, width: int, secs: float, use_registers: bool = False
) -> dict:
    dev.tune(band, control, center, width)
    before = mcu_counters(dev)
    if use_registers:
        reset_counters(dev)
    # The CCA counter is read last before the dwell and first after it, so the interval it
    # measures is the interval `elapsed_us` describes. Reading it further out puts occupancy
    # from the intervening MCU round trips into the numerator but not the denominator.
    cca_before = read_cca(dev)
    started = time.monotonic()
    frames = 0
    usb_errors = 0
    timeouts = 0
    decode = m.decoder_for(dev)
    # A-MPDU subframes arrive as separate transfers, and charging each one a full preamble is
    # the single largest error in naive airtime accounting (rxd.py). The tracker groups them
    # so an aggregate is billed one preamble, which matters here because this figure is
    # subtracted from measured occupancy: inflating it hides exactly what we are looking for.
    aggregates = rxd.AggregationTracker()
    decoded_airtime_us = 0.0

    def bill(done):
        total = 0.0
        for aggregate in done:
            air = aggregate.airtime_us()
            if air:
                total += air
        return total

    while time.monotonic() - started < secs:
        try:
            raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
        except usb.core.USBTimeoutError:
            # A quiet channel produces one of these every READ_TIMEOUT_MS. Counting them as
            # transport errors made a healthy adapter look like a failing one.
            timeouts += 1
            continue
        except usb.core.USBError:
            usb_errors += 1
            continue
        if not raw:
            continue
        d = decode(raw)
        if not d or not d.get("frame"):
            continue
        frames += 1
        parsed = rxd.parse_80211(d["frame"])
        decoded_airtime_us += bill(aggregates.feed(d, len(d["frame"]), parsed.get("addr2")))
    decoded_airtime_us += bill(aggregates.flush())
    elapsed_us = (time.monotonic() - started) * 1e6
    cca_after = read_cca(dev)
    after = mcu_counters(dev)
    mcu = {
        k: (after[k] - before[k]) if (after[k] is not None and before[k] is not None) else None
        for k in after
    }
    mcu["p_cca_time_us"] = (
        None if (cca_before is None or cca_after is None) else cca_after - cca_before
    )
    busy_us = mcu.get("p_cca_time_us")
    counters = read_counters(dev) if use_registers else dict.fromkeys(COUNTERS, 0)
    result = {
        "target": f"{band}:{control}",
        "center": center,
        "width_mhz": width,
        "dwell_us": round(elapsed_us),
        "mcu_counters": mcu,
        # `busy_us or 0` would discard a genuine zero, which is exactly what a silent
        # channel reports and is a result worth keeping.
        "busy_fraction": (
            round(busy_us / elapsed_us, 4) if (busy_us is not None and elapsed_us) else None
        ),
        "frames_decoded": frames,
        "aggregates": aggregates.completed,
        "decoded_airtime_us": round(decoded_airtime_us),
        # The number this script exists to produce: occupancy the frame decoder never saw.
        # Both terms are airtime over the same interval, so a persistently negative value
        # means the decoded side is being over-counted rather than that the channel is quiet.
        "undecoded_busy_us": (round(busy_us - decoded_airtime_us) if busy_us is not None else None),
        "usb_errors": usb_errors,
        "read_timeouts": timeouts,
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
    if busy_us == 0:
        result["warnings"].append(
            "zero occupancy: a real reading on a silent channel, but "
            "also what a stopped counter looks like"
        )
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
    # The register counters are 24-bit and wrap after 16.78 s at one microsecond per tick, so
    # a --registers dwell must stay well under that for the wrap check to mean anything. The
    # MCU counter is 32-bit -- offset 0 was observed above 51 million in a 12 s window -- so
    # the default path is not bound by that limit.
    limit = REGISTER_DWELL_MAX_S if args.registers else MCU_DWELL_MAX_S
    if not 1 <= args.seconds <= limit:
        parser.error(f"--seconds must be between 1 and {limit:g}")

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
