#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Which firmware regions are readable, and what RF machinery do they name?

Offline triage of the pinned firmware images: no adapter, no network, no firmware upload.
Each image is a header plus several regions with their own load addresses, and the regions
differ from one another far more than the images do -- one holds compiled code, another
holds every format string in the firmware, another is never downloaded to the chip at all.
Averaging them together tells you almost nothing, so this works per region.

Whether a region is encrypted is not inferred: `feature_set` bit 0 is FW_FEATURE_SET_ENCRYPT
(mt76 mt76_connac_mcu.h:9), and the loader consults it to decide the download mode. Entropy
is measured alongside as corroboration -- and to distinguish plain code from a region that
is merely compressed -- but the declared flag is what decides readability.

For readable regions the script inventories the symbols and format strings naming
energy-domain machinery: IPI histograms, EDCCA thresholds, radar detection, MIB counters.
The purpose is to decide what is worth disassembling before anyone disassembles it.

See docs/FIRMWARE_RECON.md; this is Spike C.

Usage: fw_triage.py [--json] [--strings-for NAME] [--region N] [--min-len N]
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

# struct mt76_connac2_fw_region.feature_set bits, mt76 mt76_connac_mcu.h:9-13 at baseline
# c5a3bd91. Bit 0 is the one that matters here: the loader ORs DL_MODE_ENCRYPT into the
# download mode when it is set (mt76_connac_mcu_gen_dl_mode), so a set bit means the region
# bytes in the file are ciphertext.
FW_FEATURE_SET_ENCRYPT = 1 << 0
FW_FEATURE_SET_KEY_IDX = 0b110  # GENMASK(2, 1)
FW_FEATURE_ENCRY_MODE = 1 << 4
FW_FEATURE_OVERRIDE_ADDR = 1 << 5
FW_FEATURE_NON_DL = 1 << 6
FEATURE_NAMES = (
    (FW_FEATURE_SET_ENCRYPT, "ENCRYPT"),
    (FW_FEATURE_ENCRY_MODE, "ENCRY_MODE"),
    (FW_FEATURE_OVERRIDE_ADDR, "OVERRIDE_ADDR"),
    (FW_FEATURE_NON_DL, "NON_DL"),
)

# A patch image has no feature_set. It declares encryption in the top byte of each section's
# sec_key_idx word instead, which mt76_connac2_get_data_mode reads through
# PATCH_SEC_ENC_TYPE_MASK (mt76 mt76_connac_mcu.h:31-34). Same fact, different field.
PATCH_SEC_ENC_TYPE_SHIFT = 24  # GENMASK(31, 24)
PATCH_SEC_ENC_TYPES = {0x00: "PLAIN", 0x01: "AES", 0x02: "SCRAMBLE"}
PATCH_SEC_NOT_SUPPORT = 0xFFFFFFFF

# Entropy of an ideal uniform byte source is 8.000 bits/byte. These bounds only sort a
# *readable* region into a rough kind; they never decide encryption, which the header
# declares. Measured on the MT7921 RAM image, 2026-09-03: the string region sits at 2.548,
# a table region at 3.953, and the two code regions at 6.874 and 6.799. Compiled code with
# no strings in it lands close to but below the compressed/encrypted floor, which is why a
# region above COMPRESSED_MIN is called packed rather than code.
ENTROPY_TEXT_MAX = 4.5  # strings and sparse tables
ENTROPY_COMPRESSED_MIN = 7.5  # indistinguishable from random at this point
# Below this, a "string" is as likely to be six coincidental ASCII bytes inside compiled
# code as it is to be text. 6 is the conventional floor and matches strings(1) taste.
MIN_STRING_LEN = 6
# Strings per kilobyte. The MT7921 string region measured 5.35/kB against 0.62/kB for its
# code regions and 0.13/kB for a table with none at all; anything at or above this is
# carrying real text rather than accidental ASCII runs.
STRING_DENSITY_TEXTUAL = 2.0

# What we are hunting, and why each term is here. Grouped so the report says which class of
# instrument a region implements, not just that a word appeared.
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
# The MT7921 image carries __FILE__ paths from its own build tree, which map the firmware's
# modules far better than symbol names do: wifi/core/wificore/rlm/rdm_phy.c is where the
# rdmGetIpiHist and RDD strings come from. Matched loosely because the paths are relative,
# absolute, and build-tree-relative in the same image.
SOURCE_PATH = re.compile(r"[\w./-]*\w+\.[ch]\b")


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
    return [hit.group().decode("ascii") for hit in pattern.finditer(blob)]


def feature_flags(feature_set: int) -> list[str]:
    """Name the set bits, including the key index the loader passes through."""
    names = [name for bit, name in FEATURE_NAMES if feature_set & bit]
    if feature_set & FW_FEATURE_SET_ENCRYPT:
        names.append(f"KEY_IDX={(feature_set & FW_FEATURE_SET_KEY_IDX) >> 1}")
    return names


def patch_section_encryption(sec_key_idx: int) -> str:
    """Name a patch section's encryption from its declared type byte."""
    if sec_key_idx == PATCH_SEC_NOT_SUPPORT:
        return "PLAIN"  # PATCH_SEC_NOT_SUPPORT short-circuits before any mode is applied
    enc = (sec_key_idx >> PATCH_SEC_ENC_TYPE_SHIFT) & 0xFF
    return PATCH_SEC_ENC_TYPES.get(enc, f"UNKNOWN(0x{enc:02x})")


def classify_region(feature_set: int, ent: float, n_strings: int, size: int) -> str:
    """What kind of region this is. Encryption comes from the header, never from entropy."""
    if feature_set & FW_FEATURE_SET_ENCRYPT:
        return "encrypted"
    if not size:
        return "empty"
    if feature_set & FW_FEATURE_NON_DL:
        # Never downloaded to the chip, so it is not firmware in any executable sense
        # whatever its entropy says. Both images carry one, and both are packed.
        return "not-downloaded"
    density = n_strings * 1000 / size
    if ent >= ENTROPY_COMPRESSED_MIN:
        # Not encrypted by declaration, yet indistinguishable from random: packed or
        # compressed. Readable only after whatever packed it is undone.
        return "packed"
    if ent <= ENTROPY_TEXT_MAX and density >= STRING_DENSITY_TEXTUAL:
        return "text"
    if ent <= ENTROPY_TEXT_MAX:
        return "table"
    return "code"


#: Region kinds whose bytes are meaningful to read as text or instructions.
READABLE_KINDS = frozenset({"text", "table", "code"})
#: Kinds that carry no readable bytes, each for a different and stated reason.
UNREADABLE_REASONS = {
    "encrypted": "the header declares this region encrypted",
    "packed": "not declared encrypted, yet indistinguishable from random: packed or compressed",
    "not-downloaded": "flagged NON_DL, so it is never loaded onto the chip",
    "empty": "the region is zero bytes long",
}


def source_files(strings: list[str]) -> list[str]:
    """The firmware's own __FILE__ paths, deduplicated by basename-bearing full path."""
    found = set()
    for s in strings:
        for hit in SOURCE_PATH.findall(s):
            if "/" in hit or hit.count(".") == 1:
                found.add(hit)
    return sorted(found)


def symbol_inventory(strings: list[str]) -> dict:
    """Group the RF-relevant strings by what class of instrument they name."""
    out = {}
    for name, (pattern, why) in SYMBOL_CLASSES.items():
        rx = re.compile(pattern, re.IGNORECASE)
        hits = sorted({s.strip() for s in strings if rx.search(s)})
        out[name] = {"why": why, "count": len(hits), "samples": hits[:12]}
    return out


def split_regions(blob: bytes, header: dict) -> list[dict]:
    """Slice a RAM image into its declared regions, in file order."""
    out = []
    offset = 0
    for index, region in enumerate(header.get("regions", [])):
        length = region["len"]
        out.append(
            {
                "index": index,
                "load_addr": f"0x{region['addr']:08x}",
                "bytes": length,
                "feature_set": f"0x{region['feature_set']:02x}",
                "flags": feature_flags(region["feature_set"]),
                "type": region["type"],
                "_data": blob[offset : offset + length],
                "_feature_set": region["feature_set"],
            }
        )
        offset += length
    return out


def describe_region(region: dict, min_len: int) -> dict:
    data = region.pop("_data")
    feature_set = region.pop("_feature_set")
    strings = extract_strings(data, min_len)
    ent = entropy(data)
    region["entropy_bits_per_byte"] = round(ent, 3)
    region["strings"] = len(strings)
    region["strings_per_kb"] = round(len(strings) * 1000 / len(data), 2) if data else 0.0
    region["kind"] = classify_region(feature_set, ent, len(strings), len(data))
    if region["kind"] in READABLE_KINDS:
        region["rf_symbols"] = symbol_inventory(strings)
        region["source_files"] = source_files(strings)
    else:
        region["rf_symbols"] = None
        region["note"] = (
            f"{UNREADABLE_REASONS[region['kind']]}; a string search over these bytes proves "
            f"nothing, and a missing symbol is not evidence the firmware lacks the feature"
        )
    return region


def triage(path: str, min_len: int = MIN_STRING_LEN) -> dict:
    with open(path, "rb") as fh:
        blob = fh.read()
    name = os.path.basename(path)
    is_patch = "patch" in name.lower()
    # parse_patch/parse_ram are the driver's own header parsers, so a change to the on-wire
    # layout cannot leave this script reading a stale one.
    try:
        header = m.parse_patch(blob) if is_patch else m.parse_ram(blob)
    except (ValueError, KeyError, IndexError) as exc:
        return {"image": name, "bytes": len(blob), "header": f"unparsed: {exc}", "regions": []}

    result = {
        "image": name,
        "bytes": len(blob),
        "build_date": header.get("build_date", "?"),
        "entropy_whole_file": round(entropy(blob), 3),
        "regions": [],
    }
    if is_patch:
        sections = []
        for index, sec in enumerate(header.get("sections", [])):
            enc = patch_section_encryption(sec["sec_key_idx"])
            body = blob[sec["offs"] : sec["offs"] + sec["size"]]
            entry = {
                "index": index,
                "load_addr": f"0x{sec['addr']:08x}",
                "bytes": sec["size"],
                "encryption": enc,
                "entropy_bits_per_byte": round(entropy(body), 3),
            }
            strings = extract_strings(body, min_len)
            entry["strings"] = len(strings)
            entry["kind"] = "code" if enc == "PLAIN" else "encrypted"
            entry["rf_symbols"] = symbol_inventory(strings) if enc == "PLAIN" else None
            if enc != "PLAIN":
                entry["note"] = f"declared {enc}; its bytes are ciphertext"
            sections.append(entry)
        result["sections"] = sections
        return result

    result["regions"] = [describe_region(r, min_len) for r in split_regions(blob, header)]
    return result


def extract_regions(images: list[str], out_dir: str, min_len: int) -> int:
    """Split every image into per-region files named for their load address and kind.

    Written outside the repository by intent: firmware/ is gitignored and the blobs are
    licensed (NOTICE.md), so these stay reproducible from the pinned images rather than
    stored. Regenerate rather than keep.
    """
    os.makedirs(out_dir, exist_ok=True)
    written = 0
    for path in images:
        with open(path, "rb") as fh:
            blob = fh.read()
        stem = os.path.basename(path).removesuffix(".bin")
        is_patch = "patch" in stem.lower()
        try:
            header = m.parse_patch(blob) if is_patch else m.parse_ram(blob)
        except (ValueError, KeyError, IndexError) as exc:
            print(f"skipping {stem}: {exc}", file=sys.stderr)
            continue
        if is_patch:
            pieces = [
                (
                    f"s{i}",
                    sec["addr"],
                    blob[sec["offs"] : sec["offs"] + sec["size"]],
                    "code" if patch_section_encryption(sec["sec_key_idx"]) == "PLAIN" else "enc",
                )
                for i, sec in enumerate(header.get("sections", []))
            ]
        else:
            pieces = []
            for region in split_regions(blob, header):
                data = region["_data"]
                feature_set = region["_feature_set"]
                kind = classify_region(feature_set, entropy(data), 0, len(data))
                if kind not in ("encrypted", "not-downloaded", "empty"):
                    kind = classify_region(
                        feature_set, entropy(data), len(extract_strings(data, min_len)), len(data)
                    )
                pieces.append((f"r{region['index']}", int(region["load_addr"], 16), data, kind))
        for tag, addr, data, kind in pieces:
            name = f"{stem}.{tag}.0x{addr:08x}.{kind}.bin"
            with open(os.path.join(out_dir, name), "wb") as fh:
                fh.write(data)
            print(f"{name:<62} {len(data):>9,} B")
            written += 1
    print(f"\n{written} regions written to {out_dir}", file=sys.stderr)
    return 0 if written else 2


def print_report(results: list[dict]) -> None:
    for r in results:
        print(f"{r['image']}   {r['bytes']:,} bytes   build {r.get('build_date', '?')}")
        if isinstance(r.get("header"), str):
            print(f"  {r['header']}\n")
            continue
        for sec in r.get("sections", []):
            print(
                f"  s{sec['index']} {sec['load_addr']} {sec['bytes']:>8,} B  "
                f"{sec['entropy_bits_per_byte']:5.3f} b/B  {sec['strings']:>5} str  "
                f"{sec['encryption']:<22} -> {sec['kind']}"
            )
            for cls, info in (sec["rf_symbols"] or {}).items():
                if info["count"]:
                    print(f"       {cls:<9} {info['count']:>3}  e.g. {info['samples'][0][:56]}")
        if r.get("sections"):
            print()
            continue
        for reg in r["regions"]:
            flags = ",".join(reg["flags"]) or "-"
            print(
                f"  r{reg['index']} {reg['load_addr']} {reg['bytes']:>8,} B  "
                f"{reg['entropy_bits_per_byte']:5.3f} b/B  {reg['strings']:>5} str "
                f"({reg['strings_per_kb']:>5.2f}/kB)  {flags:<22} -> {reg['kind']}"
            )
            for cls, info in (reg["rf_symbols"] or {}).items():
                if info["count"]:
                    print(f"       {cls:<9} {info['count']:>3}  e.g. {info['samples'][0][:56]}")
            src = reg.get("source_files") or []
            if src:
                print(f"       {'sources':<9} {len(src):>3}  e.g. {src[-1][:56]}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--strings-for", metavar="NAME", help="dump strings of one image")
    parser.add_argument("--region", type=int, help="with --strings-for, limit to one region")
    parser.add_argument("--min-len", type=int, default=MIN_STRING_LEN)
    parser.add_argument(
        "--extract-regions",
        metavar="DIR",
        help="write every region to DIR as <image>.r<N>.<load_addr>.<kind>.bin, for "
        "disassembly experiments. The blobs are licensed and must never be committed.",
    )
    args = parser.parse_args()
    if args.min_len < 1:
        parser.error("--min-len must be at least 1")
    if args.region is not None and not args.strings_for:
        parser.error("--region only means something with --strings-for")

    fw_dir = m.firmware_dir()
    images = sorted(str(p) for p in fw_dir.rglob("*.bin"))
    if not images:
        print(f"no firmware images under {fw_dir}; run setup.sh first", file=sys.stderr)
        return 2

    if args.strings_for:
        matches = [p for p in images if args.strings_for in os.path.basename(p)]
        if len(matches) != 1:
            print(
                f"--strings-for {args.strings_for!r} matched {len(matches)} images",
                file=sys.stderr,
            )
            return 2
        with open(matches[0], "rb") as fh:
            blob = fh.read()
        data = blob
        if args.region is not None:
            regions = split_regions(blob, m.parse_ram(blob))
            if not 0 <= args.region < len(regions):
                print(f"image has {len(regions)} regions", file=sys.stderr)
                return 2
            data = regions[args.region]["_data"]
        for s in extract_strings(data, args.min_len):
            print(s)
        return 0

    if args.extract_regions:
        return extract_regions(images, args.extract_regions, args.min_len)

    results = [triage(p, args.min_len) for p in images]
    if args.json:
        print(
            json.dumps(
                {"tool": "fw_triage", "mt76_usb_macos": m.__version__, "images": results},
                indent=2,
            )
        )
        return 0
    print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
