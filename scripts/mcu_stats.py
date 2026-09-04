#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Which MIB counters and PHY statistics will this firmware actually hand over?

The MCU keeps counters the register path does not reach, and the most interesting is
MIB_NON_WIFI_TIME: microseconds the medium was busy with energy that is not Wi-Fi at all.
A frame-counting sniffer cannot see that number by construction, and neither can a driver
that only reads CCA busy. It is reachable through MCU_EXT_CMD_GET_MIB_INFO, a command this
driver already knows how to frame.

The counter offsets are chip-specific and MT7921's are unpublished: mt7915 uses 81/82/86/87
and mt7916 uses 6/8/490/491 for the same four quantities (mt7915/mcu.h:186). So this sweeps
candidate offsets and reports which the firmware answers, rather than assuming either set.
The firmware refuses out-of-range indices -- its own string is
"MIB counter index = %d not supported" -- so a refusal is a real answer, not a timeout.

Everything here reads. No SET command is sent, nothing is transmitted, and no register is
written. See docs/FIRMWARE_RECON.md (Spike D).

Usage: mcu_stats.py [--band 5GHz --channel 36] [--seconds 4] [--sweep LO:HI] [--phy-max N]
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

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402

FW_DIR = m.firmware_dir()

# mt76 mt76_connac_mcu.h:1292 and :1309 at baseline c5a3bd91.
MCU_EXT_CMD_GET_MIB_INFO = 0x5A
MCU_EXT_CMD_PHY_STAT_INFO = 0xAD

# struct mt7915_mcu_mib { __le32 band; __le32 offs; __le64 data; } -- request and reply use
# the same 16-byte shape, the reply filling in `data` (mt7915/mcu.h).
MIB_ENTRY = "<IIQ"
MIB_ENTRY_LEN = struct.calcsize(MIB_ENTRY)  # 16; a test pins it against the struct

# enum mt7915_chan_mib_offs, mt7915/mcu.h:186. Two disjoint numbering schemes for the same
# four quantities, which is exactly why MT7921's cannot be assumed.
MIB_OFFSETS_V1 = {  # mt7915
    81: "tx_time",
    82: "rx_time",
    86: "obss_airtime",
    87: "non_wifi_time",
    88: "txop_init_count",
}
MIB_OFFSETS_V2 = {  # mt7916
    6: "tx_time",
    8: "rx_time",
    490: "obss_airtime",
    491: "non_wifi_time",
}
NAMED_OFFSETS = {**MIB_OFFSETS_V1, **MIB_OFFSETS_V2}

# Neither published mt76 scheme works on the MT7921. Measured on the reference adapter
# 2026-09-03 by sweeping every offset 0-127: exactly 19 are accepted (0-12, 14, 17, 20-23)
# and the rest return no reply at all, so this chip has its own numbering.
#
# The names below were arrived at by measurement first -- what each counter tracked across
# four channels and two bandwidths -- and then corroborated against MediaTek's own
# ENUM_MIB_COUNTER_T, which numbers the same quantities identically and is undefined at
# exactly the offsets that returned no reply here (13, 15, 16). See RELATED_WORK.md; that
# header is proprietary, so only the counters confirmed on hardware are named here rather
# than the enum being transcribed.
#
# Evidence for each, from the runs recorded in docs/FIRMWARE_RECON.md:
#   2   matched the decoder's own frame count to within one, on four channels
#   3   read exactly 65535 on every channel and every bandwidth; not a usable counter
#   7   ran about 2x the delivered MPDU count: preambles detected but not delivered
#   11  microseconds, >= the airtime of decoded frames on every channel
#   12  512 us at 20 MHz against 3224 and 3772 at 80 MHz -- it needs a secondary channel
#   14  microseconds, tracks 11 and exceeds it
MIB_OFFSETS_MT7921 = {
    2: "rx_mpdu",
    3: "channel_idle",
    7: "mdrdy",
    11: "p_cca_time_us",
    12: "s_cca_time_us",
    14: "cca_nav_tx_time_us",
}
#: The counter to use for channel occupancy: primary-channel CCA busy time, microseconds.
MIB_PRIMARY_CCA_TIME = 11
#: Offsets the firmware accepts. Anything else got no reply at all, which stalls a sweep.
MT7921_ACCEPTED_OFFSETS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 17, 20, 21, 22, 23)
# The counter sits at this byte of the reply body, which is 24 bytes of header followed by a
# copy of the request. Found by sweep, not from a published struct.
MIB_VALUE_OFFSET = 28

# mt7915 batches 5 entries per command; keep to that shape rather than inventing a larger
# one, since an over-long request is a plausible way to get a blanket refusal that says
# nothing about the individual offsets.
MIB_BATCH = 5

# enum at mt76_connac_mcu.h:1199. Five names upstream; whether the firmware answers more is
# the open question this sweep settles.
PHY_STATE_NAMES = {
    0: "TX_RATE",
    1: "RX_RATE",
    2: "RSSI",
    3: "CONTENTION_RX_RATE",
    4: "OFDMLQ_CNINFO",
}
PHY_CATEGORY_DEFAULT_MAX = 15

# The firmware's "I do not implement this command" reply, measured on an MT7921U 2026-09-03
# and calibrated against controls in both directions: exactly 16 bytes, the echoed ext_cid in
# the first word and 0xfe in the second. THERMAL_CTRL (0x2c, 1128 bytes of real data) and
# EFUSE_ACCESS (0x01, 32 bytes, valid=1) never produce it; SET_RADAR_TH (0x7c) and
# SET_FEATURE_CTRL (0x38), neither of which has a dispatch slot in the image, produce it
# exactly. It is a dispatch-level rejection, returned before any handler runs.
#
# Note what this cost: RX_AIRTIME_CTRL (0x4a) *has* a dispatch slot and is still refused, so
# a slot in the table is not evidence the command is implemented. Only this reply is.
MCU_UNSUPPORTED_STATUS = 0xFE
MCU_REFUSAL_LEN = 16


def is_refusal(body: bytes, cid: int) -> bool:
    """Did the firmware reject this command id outright?"""
    if len(body) != MCU_REFUSAL_LEN:
        return False
    echo, status = struct.unpack_from("<II", body, 0)
    return echo == cid and status == MCU_UNSUPPORTED_STATUS


# A counter that never moves across a dwell is either unimplemented or measuring something
# static; either way it is not the airtime figure we are looking for.
MIN_DWELL_S, MAX_DWELL_S = 1.0, 30.0
# The firmware answers a refused index somehow; we do not know how, so treat these two
# readings as "no counter here" rather than as data.
DEAD_VALUES = (0x0000000000000000, 0xFFFFFFFFFFFFFFFF)


def parse_sweep(text: str) -> range:
    try:
        lo_s, hi_s = text.split(":")
        lo, hi = int(lo_s, 0), int(hi_s, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bad sweep {text!r}; want LOW:HIGH") from exc
    if lo < 0 or hi <= lo:
        raise argparse.ArgumentTypeError("sweep needs 0 <= LOW < HIGH")
    if hi - lo > 1024:
        raise argparse.ArgumentTypeError("sweep is wider than 1024 offsets")
    return range(lo, hi)


def build_mib_request(band: int, offsets: list[int]) -> bytes:
    return b"".join(struct.pack(MIB_ENTRY, band, offs, 0) for offs in offsets)


def parse_mt7921_value(body: bytes) -> int | None:
    """The counter in a single-entry MT7921 GET_MIB_INFO reply.

    The documented reply shape does not apply here: the firmware returns 24 bytes of header
    plus a zeroed copy of the request, with the counter as a 32-bit word at byte 28 rather
    than in the entry's own `data` field. Measured, not published.
    """
    if len(body) < MIB_VALUE_OFFSET + 4:
        return None
    return struct.unpack_from("<I", body, MIB_VALUE_OFFSET)[0]


def parse_mib_reply(body: bytes, band: int, offsets: list[int]) -> dict[int, int]:
    """Find each echoed {band, offs} pair in the reply and read the counter beside it.

    mt7915 skips a fixed 20-byte preamble and mt7916 skips none (mt7915/mcu.c:3241), so the
    header length is chip-specific and MT7921's is unknown. Searching for the echoed pair
    instead of trusting an offset means this works whatever the preamble turns out to be,
    and it fails loudly rather than silently misaligning by 20 bytes.
    """
    found: dict[int, int] = {}
    for offs in offsets:
        needle = struct.pack("<II", band, offs)
        at = body.find(needle)
        if at < 0 or at + MIB_ENTRY_LEN > len(body):
            continue
        (value,) = struct.unpack_from("<Q", body, at + 8)
        found[offs] = value
    return found


def query_mib(dev, band: int, offsets: list[int], timeout: int = 3000) -> dict:
    """One GET_MIB_INFO round trip. Returns values keyed by offset, plus what went wrong."""
    req = build_mib_request(band, offsets)
    try:
        rxd = dev.mcu_cmd_word(m.MCU_EXT_CMD(MCU_EXT_CMD_GET_MIB_INFO), req, timeout=timeout)
    except (m.McuError, RuntimeError, usb.core.USBError) as exc:
        # An offset this chip does not implement never answers at all, so a timeout here is
        # an ordinary result. usb.core.USBError derives from OSError, not RuntimeError, and
        # leaving it uncaught crashed the sweep on hardware (2026-09-03).
        return {"offsets": offsets, "error": str(exc), "values": {}}
    body = dev.reply_body(rxd)
    if is_refusal(body, MCU_EXT_CMD_GET_MIB_INFO):
        return {
            "offsets": offsets,
            "refused": True,
            "values": {},
            "error": "firmware does not implement GET_MIB_INFO",
        }
    # This chip does not echo {band, offs} pairs back and does not fill the entry's `data`
    # field, so the documented parser finds nothing here. A single-entry request carries its
    # counter as one word at a fixed position instead; anything longer is read the documented
    # way, since that is the only shape parse_mib_reply can make sense of.
    if len(offsets) == 1:
        value = parse_mt7921_value(body)
        values = {offsets[0]: value} if value is not None else {}
    else:
        values = parse_mib_reply(body, band, offsets)
    result = {"offsets": offsets, "reply_bytes": len(body), "values": values}
    missing = [o for o in offsets if o not in values]
    if missing:
        # The firmware answered but did not echo these back: refused, or a reply shape we
        # do not understand. Either way it is not a counter we can read.
        result["not_echoed"] = missing
    return result


def query_phy_category(dev, band: int, category: int, timeout: int = 3000) -> dict:
    """One PHY_STAT_INFO round trip. Request shape from mt7915_mcu_get_rx_rate."""
    req = struct.pack("<BBH", category, band, 0)  # category, band, wcid
    entry = {"category": category, "name": PHY_STATE_NAMES.get(category, "unnamed")}
    try:
        rxd = dev.mcu_cmd_word(m.MCU_EXT_CMD(MCU_EXT_CMD_PHY_STAT_INFO), req, timeout=timeout)
    except (m.McuError, RuntimeError, usb.core.USBError) as exc:
        entry["answered"] = False
        entry["error"] = str(exc)
        return entry
    body = dev.reply_body(rxd)
    # A reply is not an implementation. Measured on an MT7921U 2026-09-03: every category,
    # including the five named upstream, answered with the same 8-byte prefix
    # `ad000000 fe000000` and varying uninitialised tail -- the echoed ext_cid followed by a
    # fixed non-zero byte. So the shape of the reply is recorded and the judgement about
    # what it means is made across categories, not from one.
    entry["answered"] = True
    entry["refused"] = is_refusal(body, MCU_EXT_CMD_PHY_STAT_INFO)
    entry["reply_bytes"] = len(body)
    entry["reply_prefix"] = body[:8].hex()
    entry["reply_head"] = body[:32].hex()
    entry["all_zero"] = not any(body)
    return entry


def judge_phy_sweep(entries: list[dict]) -> dict:
    """Did PHY_STAT_INFO behave like a command, or like a stub?

    A command that is implemented answers its categories differently from one another, and
    refuses the ones it does not know. One identical prefix across every category -- named
    and unnamed alike -- is a single code path that ignores the request.
    """
    answered = [e for e in entries if e["answered"]]
    if not answered:
        return {"verdict": "no category answered", "answered": 0, "distinct_prefixes": 0}
    refused = [e for e in answered if e.get("refused")]
    if len(refused) == len(answered):
        return {
            "verdict": "not implemented: every category got the firmware's unsupported-command "
            "reply, which is returned before any handler runs",
            "answered": len(answered),
            "refused": len(refused),
            "distinct_prefixes": len({e["reply_prefix"] for e in answered}),
        }
    prefixes = {e["reply_prefix"] for e in answered}
    if len(prefixes) == 1 and len(answered) > len(PHY_STATE_NAMES):
        verdict = "stub: every category returned an identical prefix, so the request is not read"
    elif len(prefixes) > 1:
        verdict = "categories answered differently; worth reading the payloads"
    else:
        # One reply, or too few to have compared anything. Saying they "answered differently"
        # here would promote a single sample into evidence about how the command behaves.
        verdict = (
            f"insufficient evidence: {len(answered)} categor"
            f"{'y' if len(answered) == 1 else 'ies'} answered, nothing to compare"
        )
    return {
        "verdict": verdict,
        "answered": len(answered),
        "distinct_prefixes": len(prefixes),
        "prefix": min(prefixes) if len(prefixes) == 1 else None,
    }


def names_for(published: bool) -> dict[int, str]:
    """The naming that goes with the offset scheme being swept.

    An explicit choice rather than something inferred from the offsets, because the two
    schemes overlap numerically and mean different things: 6 and 8 are `tx_time` and
    `rx_time` under mt7916's numbering, and are accepted-but-unidentified counters on the
    MT7921. Guessing from the offset set gets that backwards, and naming a sweep with the
    wrong map does not fail loudly -- it mislabels, which is worse.
    """
    return NAMED_OFFSETS if published else MIB_OFFSETS_MT7921


def sweep_mib(
    dev, band: int, offsets: list[int], seconds: float, names: dict[int, str] | None = None
) -> dict:
    """Read every offset twice around a dwell; a counter is only real if it moves."""
    names = names_for(offsets) if names is None else names
    # One offset per request. Batching is the documented shape and mt7915 uses it, but this
    # chip answers a single-entry request with one counter and no echo, so a batch would be
    # unreadable however it were parsed.
    batches = [[o] for o in offsets]
    before: dict[int, int] = {}
    errors = []
    for batch in batches:
        r = query_mib(dev, band, batch)
        before.update(r["values"])
        if r.get("error"):
            errors.append(r)
    time.sleep(seconds)
    after: dict[int, int] = {}
    for batch in batches:
        r = query_mib(dev, band, batch)
        after.update(r["values"])
        if r.get("error"):
            # Dropping this turns a failed second read into a silent "did not move", which
            # reads as a negative result rather than as a measurement that did not complete.
            errors.append(r)

    counters = {}
    for offs in offsets:
        if offs not in after:
            continue
        value = after[offs]
        # A missing baseline is not a zero baseline. Substituting one turns "we failed to
        # read this before the dwell" into a delta equal to the whole free-running counter,
        # which reads as a spectacular amount of traffic.
        base = before.get(offs)
        delta = None if base is None else value - base
        counters[offs] = {
            "name": names.get(offs),
            "before": base,
            "after": value,
            "delta": delta,
            # Only a counter that moved is evidence of a live measurement. A static
            # non-zero value may still be meaningful, so it is reported, not discarded.
            "moved": bool(delta and delta > 0),
            "dead_value": value in DEAD_VALUES,
        }
    return {
        "queried": len(offsets),
        "echoed": len(counters),
        "moved": sum(1 for c in counters.values() if c["moved"]),
        "errors": errors,
        "counters": {str(k): v for k, v in sorted(counters.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--band", default="5GHz", choices=sorted(m.CHAN_BAND))
    parser.add_argument("--channel", type=int, default=36)
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--sweep", type=parse_sweep, help="also try this offset range, e.g. 0:128")
    parser.add_argument(
        "--published",
        action="store_true",
        help="use the mt7915/mt7916 offsets instead; this chip refuses them, and the option "
        "exists so that result stays reproducible",
    )
    parser.add_argument("--phy-max", type=int, default=PHY_CATEGORY_DEFAULT_MAX)
    parser.add_argument("--band-idx", type=int, default=0, help="hardware band index")
    args = parser.parse_args()
    if not MIN_DWELL_S <= args.seconds <= MAX_DWELL_S:
        parser.error(f"--seconds must be between {MIN_DWELL_S} and {MAX_DWELL_S}")
    if not 0 <= args.phy_max <= 255:
        parser.error("--phy-max must be between 0 and 255")

    # Default to what this chip accepts, not to the published schemes it refuses -- each
    # unimplemented offset costs a full timeout and returns nothing. --published asks for
    # the mt7915/mt7916 numbering, which is how that negative result stays reproducible.
    offsets = sorted(NAMED_OFFSETS) if args.published else list(MT7921_ACCEPTED_OFFSETS)
    if args.sweep:
        offsets = sorted(set(offsets) | set(args.sweep))

    dev = m.open_device()
    patch, ram = m.load_firmware(dev.CHIP, FW_DIR)
    out: dict = {
        "tool": "mcu_stats",
        "mt76_usb_macos": m.__version__,
        "chip": dev.CHIP,
        "band": args.band,
        "channel": args.channel,
        "dwell_s": args.seconds,
    }
    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        dev.tune(args.band, args.channel, args.channel, 20)

        out["mib"] = sweep_mib(dev, args.band_idx, offsets, args.seconds, names_for(args.published))
        out["phy_stat"] = [
            query_phy_category(dev, args.band_idx, c) for c in range(args.phy_max + 1)
        ]
        out["phy_stat_verdict"] = judge_phy_sweep(out["phy_stat"])

    print(json.dumps(out, indent=2))

    mib = out["mib"]
    named_moved = [c["name"] for c in mib["counters"].values() if c["moved"] and c["name"]]
    print(
        f"\n{mib['echoed']}/{mib['queried']} offsets echoed, {mib['moved']} moved over "
        f"{args.seconds}s. Named counters that moved: {', '.join(sorted(set(named_moved))) or 'none'}",
        file=sys.stderr,
    )
    verdict = out["phy_stat_verdict"]
    print(
        f"PHY_STAT_INFO: {verdict['answered']}/{len(out['phy_stat'])} categories replied, "
        f"{verdict['distinct_prefixes']} distinct reply prefix(es) -- {verdict['verdict']}",
        file=sys.stderr,
    )
    if not mib["moved"]:
        print(
            "\nNo MIB counter moved. That is a result: record it in NEGATIVE_RESULTS.md with "
            "the offsets swept, and fall back to Spike B.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
