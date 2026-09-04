#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Is there an IPI histogram behind the PHY register window, and can we reach it?

The mt7921 driver reports no noise floor: mt792x_mac.c:216 mt792x_phy_get_nf() is
`return 0;`. The sibling AP driver derives one at mt7915/mac.c:1200 from an Idle Power
Indicator histogram -- eleven bins counting how long the receiver sat at each power level,
independent of whether anything demodulated. That is the measurement this driver is missing.

Whether an MT7921U can reach it is an open question. MT_WF_IRPI_BASE is 0x83000000 and
MT_WF_PHY_BASE is 0x83080000 on mt7915, but no 0x83xxxxxx region appears in mt7921's own
headers or in its PCI fixed_map, so the block may be at a different address, or unreachable
through the USB register window entirely.

This script is READ ONLY. It never writes to 0x83xxxxxx. Enabling IPI accumulation means
setting MT_WF_PHY_RX_CTRL1_IPI_EN in a register block we have not identified, and writing
to an unidentified PHY register on a live radio is how you brick a capture session. Reads
first; --enable is refused until a read pass has produced evidence, and even then it is
gated behind an explicit flag.

Usage: ipi_probe.py [--band 5GHz --channel 36] [--window 0x83000000:0x8300c000]
See docs/FIRMWARE_RECON.md (Spike B) for the acceptance criteria.
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

FW_DIR = m.firmware_dir()

# mt7915/regs.h at baseline c5a3bd91. Named here as the hypothesis under test, not as an
# established mt7921 address:
#   MT_WF_IRPI_BASE       0x83000000
#   MT_WF_IRPI_NSS(p, n)  MT_WF_IRPI(0x6000 + (p << 20) + (n << 16))
#   MT_WF_PHY_BASE        0x83080000
MT_WF_IRPI_BASE = 0x83000000
MT_WF_IRPI_NSS_OFFSET = 0x6000  # mt7915 layout; MT7916 uses 0x1000 for the same thing
MT_WF_IRPI_NSS_STRIDE = 1 << 16
MT_WF_PHY_BASE = 0x83080000
# mt7915/mac.c:1201 nf_power[]: the dBm magnitude each of the 11 bins represents. Applied
# only after a read pass shows the words behave like bin counts.
NF_POWER = (92, 89, 86, 83, 80, 75, 70, 65, 60, 55, 52)
IRPI_BINS = len(NF_POWER)

# A read that returns one of these for every word in a region means the region is not
# backed by anything, not that the histogram is empty.
DEAD_VALUES = (0x00000000, 0xFFFFFFFF)
# A region needs more distinct values than this before "varied data" is a fair description;
# two distinct values across a whole window is a pattern, not a measurement.
MIN_DISTINCT_FOR_LIVE = 3
# Each word costs one USB control transfer, so a window is a time budget as much as an
# address range. The default covers the neighbourhood of MT_WF_IRPI_NSS(0, 0) generously
# rather than sweeping the whole 0x83xxxxxx space; the two fixed head probes below answer
# the cheaper question of whether either base responds at all.
DEFAULT_WINDOW = (
    MT_WF_IRPI_BASE + MT_WF_IRPI_NSS_OFFSET,
    MT_WF_IRPI_BASE + MT_WF_IRPI_NSS_OFFSET + 0x1000,
)
HEAD_PROBE_BYTES = 0x100  # enough to tell "mapped" from "dead" without a long sweep
MAX_WORDS = 4096  # about ten seconds of control transfers


def parse_window(text: str) -> tuple[int, int]:
    try:
        lo_s, hi_s = text.split(":")
        lo, hi = int(lo_s, 0), int(hi_s, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad window {text!r}; want LOW:HIGH") from exc
    if lo % 4 or hi % 4 or hi <= lo:
        raise argparse.ArgumentTypeError("window bounds must be 4-byte aligned with HIGH > LOW")
    if (hi - lo) // 4 > MAX_WORDS:
        raise argparse.ArgumentTypeError(f"window is more than {MAX_WORDS} words")
    return lo, hi


def scan(dev, lo: int, hi: int, step: int = 4) -> dict:
    """Read a register window and describe what came back, without interpreting it."""
    words: dict[int, int] = {}
    errors = 0
    for addr in range(lo, hi, step):
        try:
            words[addr] = dev.rr(addr)
        except (RuntimeError, usb.core.USBError):
            errors += 1
    if not words:
        return {
            "low": hex(lo),
            "high": hex(hi),
            "read": 0,
            "errors": errors,
            "verdict": "no word in this window could be read",
        }
    values = list(words.values())
    distinct = set(values)
    live = [a for a, v in words.items() if v not in DEAD_VALUES]
    if len(distinct) < MIN_DISTINCT_FOR_LIVE:
        verdict = (
            f"unmapped or constant: {len(distinct)} distinct value(s) across "
            f"{len(values)} words ({', '.join(hex(v) for v in sorted(distinct))})"
        )
    else:
        verdict = f"varied: {len(distinct)} distinct values, {len(live)} words not 0/all-ones"
    return {
        "low": hex(lo),
        "high": hex(hi),
        "read": len(values),
        "errors": errors,
        "distinct_values": len(distinct),
        "live_words": len(live),
        "first_live": [{"addr": hex(a), "value": hex(words[a])} for a in live[:16]],
        "verdict": verdict,
    }


def irpi_bins(dev, nss: int) -> list[int]:
    """Read the 11 words where mt7915 keeps one chain's histogram."""
    base = MT_WF_IRPI_BASE + MT_WF_IRPI_NSS_OFFSET + nss * MT_WF_IRPI_NSS_STRIDE
    return [dev.rr(base + 4 * i) for i in range(IRPI_BINS)]


def looks_like_histogram(before: list[int], after: list[int]) -> tuple[bool, str]:
    """Acceptance criterion: bins must be non-negative and must grow while receiving."""
    if all(v in DEAD_VALUES for v in after):
        return False, "all bins read 0 or all-ones: nothing is accumulating here"
    if len(set(after)) < 2:
        return False, f"all bins read the same value ({hex(after[0])}); not a distribution"
    grew = sum(1 for b, a in zip(before, after, strict=True) if a > b)
    shrank = sum(1 for b, a in zip(before, after, strict=True) if a < b)
    if grew == 0:
        return False, "no bin grew across the dwell; these are not free-running counters"
    if shrank > grew:
        return False, f"{shrank} bins decreased against {grew} that grew; not monotonic counts"
    return True, f"{grew} of {IRPI_BINS} bins grew across the dwell"


def noise_floor_dbm(bins: list[int]) -> float | None:
    """mt7915_phy_get_nf: weight each bin by its dBm magnitude, then negate the mean."""
    total = sum(bins)
    if not total:
        return None
    return -round(sum(b * p for b, p in zip(bins, NF_POWER, strict=True)) / total, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--band", default="5GHz", choices=sorted(m.CHAN_BAND))
    parser.add_argument("--channel", type=int, default=36)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument(
        "--window",
        type=parse_window,
        default=DEFAULT_WINDOW,
        help="register range to survey, e.g. 0x83000000:0x8300c000",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="refused: writing IPI_EN needs an identified PHY block first",
    )
    args = parser.parse_args()
    if args.enable:
        parser.error(
            "--enable is not implemented on purpose; see the module docstring and "
            "docs/FIRMWARE_RECON.md. Identify the block with read passes first."
        )
    if not 1 <= args.seconds <= 30:
        parser.error("--seconds must be between 1 and 30")

    dev = m.open_device()
    patch, ram = m.load_firmware(dev.CHIP, FW_DIR)
    out: dict = {
        "tool": "ipi_probe",
        "mt76_usb_macos": m.__version__,
        "chip": dev.CHIP,
        "hypothesis": "mt7915 MT_WF_IRPI_BASE 0x83000000 also backs the MT7921 PHY",
    }
    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        dev.tune(args.band, args.channel, args.channel, 20)

        out["irpi_base_probe"] = scan(dev, MT_WF_IRPI_BASE, MT_WF_IRPI_BASE + HEAD_PROBE_BYTES)
        out["phy_base_probe"] = scan(dev, MT_WF_PHY_BASE, MT_WF_PHY_BASE + HEAD_PROBE_BYTES)
        out["window_scan"] = scan(dev, *args.window)

        chains = {}
        for nss in (0, 1):
            before = irpi_bins(dev, nss)
            time.sleep(args.seconds)
            after = irpi_bins(dev, nss)
            ok, why = looks_like_histogram(before, after)
            chains[f"nss{nss}"] = {
                "before": before,
                "after": after,
                "delta": [a - b for b, a in zip(before, after, strict=True)],
                "histogram_like": ok,
                "why": why,
                # Only meaningful if histogram_like; reported alongside so the reader can
                # see what the number would be rather than having to rerun.
                "noise_floor_dbm_if_valid": noise_floor_dbm(after) if ok else None,
            }
        out["irpi_chains"] = chains

    print(json.dumps(out, indent=2))
    found = any(c["histogram_like"] for c in out["irpi_chains"].values())
    if not found:
        print(
            "\nNo IRPI histogram at the mt7915 addresses. This is a result, not a failure: "
            "record it in NEGATIVE_RESULTS.md with the window scanned.",
            file=sys.stderr,
        )
    return 0 if found else 2


if __name__ == "__main__":
    sys.exit(main())
