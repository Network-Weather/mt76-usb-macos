#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Which firmware images are readable, and what RF machinery do they name?

Offline triage of the pinned firmware blobs: no adapter, no network, no firmware upload.
For each image it parses the connac header with the driver's own parser, measures Shannon
entropy per region, and classifies the image as readable (plaintext code with debug strings
intact) or opaque (encrypted or compressed, where a string search proves nothing). For a
readable image it inventories the symbols and format strings naming energy-domain
machinery: IPI histograms, EDCCA thresholds, radar detection, MIB counters.

Purpose is to decide what is worth disassembling before anyone disassembles it. See
docs/FIRMWARE_RECON.md; this is Spike C.

Usage: fw_triage.py [--json] [--strings-for NAME] [--min-len N]
Images come from $MT76_FW_DIR (or $MT7921_FW_DIR), defaulting to <repo>/firmware.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import mt7921u as m  # noqa: E402

# Entropy of an ideal uniform byte source is 8.000 bits/byte. Compiled code with an intact
# string table sits far below that because opcodes and ASCII are both skewed; the four
# pinned blobs measured 6.03/6.50 (MT7921 RAM/patch) against 7.96/8.00 (MT7925 RAM/patch)
# on 2026-09-03. The gap is wide enough that any cut inside it separates them, so the
# threshold below is a midpoint rounded to one decimal, not a tuned value. A blob landing
# between 6.6 and 7.4 is reported as "indeterminate" rather than forced into a bucket.
ENTROPY_READABLE_MAX = 6.6
ENTROPY_OPAQUE_MIN = 7.4
# Below this, a "string" is as likely to be three coincidental ASCII bytes in a code
# section as it is to be text; 6 is the conventional floor and matches strings(1) taste.
MIN_STRING_LEN = 6
# A readable image should yield strings that are overwhelmingly printable words rather than
# accidental runs. Used only to annotate the classification, never to override entropy.
READABLE_MIN_STRINGS = 500

# What we are hunting, and why each term is here. Grouped so the report says which class of
# instrument an image implements, not just that a word appeared.
SYMBOL_CLASSES = {
    "ipi": (
        r"ipi|irpi",
        "Idle Power Indicator: per-bin dwell histogram of received power, the basis for a "
        "noise floor (mt7915/mac.c:1200 derives one; mt792x_mac.c:216 returns 0)",
    ),
    "edcca": (
        r"edcca",
        "Energy Detect CCA thresholds, per band and per bandwidth: the level above which "
        "the PHY calls the medium busy",
    ),
    "radar": (
        r"\brdd|radar|\bdfs\b",
        "Radar detection: raw pulse reports, useful beyond DFS as a non-Wi-Fi energy source",
    ),
    "mib": (
        r"\bmib\b|sdr\d+|airtime|obss",
        "MIB counters: CCA busy, TX/RX/OBSS airtime, in microseconds",
    ),
    "spectrum": (
        r"spectrum|\bnf\b|noise",
        "Spectrum and noise-floor machinery",
    ),
}
PRINTABLE = re.compile(rb"[\x20-\x7e]{%d,}" % MIN_STRING_LEN)


def entropy(blob: bytes) -> float:
    """Shannon entropy in bits per byte; 8.0 is indistinguishable from random."""
    if not blob:
        return 0.0
    counts = collections.Counter(blob)
    n = len(blob)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def extract_strings(blob: bytes, min_len: int = MIN_STRING_LEN) -> list[str]:
    if min_len < 1:
        raise ValueError("min_len must be at least 1")
    pattern = PRINTABLE if min_len == MIN_STRING_LEN else re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    return [m_.group().decode("ascii") for m_ in pattern.finditer(blob)]


def classify(ent: float, n_strings: int) -> str:
    """Readable, opaque, or indeterminate. Entropy decides; string count only annotates."""
    if ent <= ENTROPY_READABLE_MAX:
        return "readable" if n_strings >= READABLE_MIN_STRINGS else "readable-few-strings"
    if ent >= ENTROPY_OPAQUE_MIN:
        return "opaque"
    return "indeterminate"


def symbol_inventory(strings: list[str]) -> dict:
    """Group the RF-relevant strings by what class of instrument they name."""
    out = {}
    for name, (pattern, why) in SYMBOL_CLASSES.items():
        rx = re.compile(pattern, re.IGNORECASE)
        hits = sorted({s.strip() for s in strings if rx.search(s)})
        out[name] = {"why": why, "count": len(hits), "samples": hits[:12]}
    return out


def triage(path: str, min_len: int = MIN_STRING_LEN) -> dict:
    with open(path, "rb") as fh:
        blob = fh.read()
    name = os.path.basename(path)
    # parse_patch/parse_ram are the driver's own header parsers, so a change to the on-wire
    # layout cannot leave this script reading a stale one.
    header: dict | str
    try:
        header = m.parse_patch(blob) if "patch" in name.lower() else m.parse_ram(blob)
    except (ValueError, KeyError, IndexError) as exc:
        header = f"unparsed: {exc}"
    strings = extract_strings(blob, min_len)
    ent = entropy(blob)
    result = {
        "image": name,
        "bytes": len(blob),
        "entropy_bits_per_byte": round(ent, 3),
        "strings": len(strings),
        "classification": classify(ent, len(strings)),
        "header": header,
    }
    if result["classification"].startswith("readable"):
        result["rf_symbols"] = symbol_inventory(strings)
    else:
        result["rf_symbols"] = None
        result["note"] = (
            "high entropy: a string search over this image proves nothing, and its absence "
            "of a symbol is not evidence the firmware lacks the feature"
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--strings-for", metavar="NAME", help="dump all strings of one image")
    parser.add_argument("--min-len", type=int, default=MIN_STRING_LEN)
    args = parser.parse_args()
    if args.min_len < 1:
        parser.error("--min-len must be at least 1")

    fw_dir = m.firmware_dir()
    images = sorted(str(p) for p in fw_dir.rglob("*.bin"))
    if not images:
        print(f"no firmware images under {fw_dir}; run setup.sh first", file=sys.stderr)
        return 2

    if args.strings_for:
        matches = [p for p in images if args.strings_for in os.path.basename(p)]
        if len(matches) != 1:
            print(
                f"--strings-for {args.strings_for!r} matched {len(matches)} images", file=sys.stderr
            )
            return 2
        with open(matches[0], "rb") as fh:
            for s in extract_strings(fh.read(), args.min_len):
                print(s)
        return 0

    results = [triage(p, args.min_len) for p in images]
    if args.json:
        print(
            json.dumps(
                {"tool": "fw_triage", "mt76_usb_macos": m.__version__, "images": results}, indent=2
            )
        )
        return 0

    for r in results:
        print(f"{r['image']}")
        print(
            f"  {r['bytes']:>9,} bytes   {r['entropy_bits_per_byte']:.3f} bits/byte   "
            f"{r['strings']:>5} strings   -> {r['classification']}"
        )
        hdr = r["header"]
        if isinstance(hdr, dict):
            date = hdr.get("build_date", "?")
            print(f"  build {date}   regions {hdr.get('n_region', '?')}")
        else:
            print(f"  header {hdr}")
        if r["rf_symbols"]:
            for cls, info in r["rf_symbols"].items():
                if info["count"]:
                    print(
                        f"    {cls:<9} {info['count']:>3} strings   e.g. {info['samples'][0][:60]}"
                    )
        else:
            print(f"    {r['note']}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
