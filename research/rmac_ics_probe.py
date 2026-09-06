#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded off/on/off RMAC ICS test; aggregate metadata only, no TX/filter changes."""

import argparse
import collections
import datetime
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import ics_trace_probe as trace
from research import rmac_ics_match as matching
from research.ics_control_probe import valid_word
from research.mt7925_noise_event_probe import event_body
from research.txpower_register_probe import check_image, m, read_words

MASKS = {0x820E50D0: 1, 0x820E705C: 1 << 24}
WINDOWS = (
    ("rmac", 0x82B670, 128, "819657a0ac661fa155bb710490bfd5d8978248e160ca879090c2704d69071376"),
    ("combined", 0x83238C, 192, "c0b268e334b341c39e1e787b9c239676e9e86b00f10b7553d1ae497a90d47f77"),
)


def request(start):
    if type(start) is not bool:
        raise ValueError("boolean action required")
    return struct.pack(
        "<4xHHBBHBBBB7H62x", 0, 88, 0, int(start), 0, 2, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0
    )


def aggregate_shape(raw):
    if len(raw) < 8:
        return None
    word = struct.unpack_from("<I", raw)[0]
    length, kind = word & 0xFFFF, (word >> 27) & 31
    if kind not in (12, 13):
        return None
    if not 8 <= length <= len(raw):
        raise ValueError("invalid ICS aggregate length")
    return {"type": kind, "bytes": length, "frame_count": (word >> 16) & 31}


def masks(dev):
    return {hex(a): valid_word(dev.rr(a)) & mask for a, mask in MASKS.items()}


def restore(dev, originals):
    if dev.CHIP != m.CHIP_MT7925 or set(originals) != set(MASKS):
        raise ValueError("only pinned RMAC ICS masks")
    out = {}
    for address, mask in MASKS.items():
        bits = originals[address]
        if type(bits) is not int or bits < 0 or bits & ~mask:
            raise ValueError("invalid restoration bits")
        dev.wr(address, valid_word(dev.rr(address)) & ~mask | bits)
        out[hex(address)] = valid_word(dev.rr(address)) & mask == bits
    return out


def send(dev, start):
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(0x49, False) != 7:
        raise ValueError("pinned MT7925 UNI49 required")
    dev.mcu_uni(0x49, request(start), query=False, wait=False)
    return dev.msg_seq


def collect(dev, sequence=None, match_rxd=False):
    types, shapes, acks = collections.Counter(), collections.Counter(), []
    normal, aggregates = [], []  # Local-only bounded buffers, never returned.
    start = time.monotonic()
    attempts, malformed = 0, 0
    while time.monotonic() - start < 0.4 and attempts < 512:
        for ep in (dev.ep_in_pkt_rx, dev.ep_in_cmd_resp):
            attempts += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            if len(raw) >= 4:
                kind = (struct.unpack_from("<I", raw)[0] >> 27) & 31
                types[(ep, kind)] += 1
                if match_rxd and kind == 2 and len(normal) < matching.LIMIT:
                    normal.append(bytes(raw))
            try:
                shape = aggregate_shape(raw)
            except ValueError:
                malformed += 1
                shape = None
            if shape:
                shapes[(ep, shape["type"], shape["bytes"], shape["frame_count"])] += 1
                if match_rxd and len(aggregates) < matching.LIMIT:
                    aggregates.append(bytes(raw[: shape["bytes"]]))
            parsed = event_body(raw)
            if parsed and parsed[:2] == (1, sequence) and len(parsed[2]) == 8:
                cid, status = struct.unpack("<II", parsed[2])
                if cid == 0x49:
                    acks.append({"cid": cid, "status": status})
    return {
        "elapsed_seconds": time.monotonic() - start,
        "attempts": attempts,
        "leading_packet_types": [
            {"endpoint": ep, "type": k, "count": n} for (ep, k), n in sorted(types.items())
        ],
        "aggregate_shapes": [
            {"endpoint": ep, "type": k, "bytes": size, "frame_count": frames, "count": n}
            for (ep, k, size, frames), n in sorted(shapes.items())
        ],
        "invalid_aggregate_lengths": malformed,
        "acknowledgments": acks,
        "in_memory_matching": matching.reduce_matches(normal, aggregates) if match_rxd else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-rmac-ics", action="store_true")
    parser.add_argument("--match-rxd-in-memory", action="store_true")
    parser.add_argument("--channel", type=int, choices=(6, 36), default=6)
    args = parser.parse_args()
    if not args.activate_rmac_ics:
        parser.error("explicit RMAC ICS acknowledgment required")
    images = m.load_firmware(m.CHIP_MT7925, m.firmware_dir())
    check_image(images[1])
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "start_request_hex": request(True).hex(),
        "channel": args.channel,
    }
    attempted, originals = False, {}
    with m.open_device("0846:9072") as dev:
        try:
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel == 6 else "5GHz", args.channel, args.channel, 20)
            out["verified"] = trace.verify(dev)
            out["rom"] = []
            for name, address, size, expected in WINDOWS:
                digest = hashlib.sha256(read_words(dev, address, size)).hexdigest()
                if digest != expected:
                    raise ValueError("RMAC ROM mismatch")
                out["rom"].append(
                    {"name": name, "address": hex(address), "bytes": size, "sha256": digest}
                )
            originals = {a: valid_word(dev.rr(a)) & mask for a, mask in MASKS.items()}
            if any(originals.values()):
                raise ValueError("ICS already enabled")
            out["before_masks"] = masks(dev)
            out["off_before"] = collect(dev, match_rxd=args.match_rxd_in_memory)
            attempted = True
            sequence = send(dev, True)
            out["on"] = collect(dev, sequence, args.match_rxd_in_memory)
            out["on_masks"] = masks(dev)
            sequence = send(dev, False)
            out["off_after"] = collect(dev, sequence, args.match_rxd_in_memory)
            out["off_after_masks"] = masks(dev)
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if attempted:
                try:
                    send(dev, False)
                    out["restored"] = restore(dev, originals)
                except Exception as exc:
                    out["restore_error_type"] = type(exc).__name__
            try:
                out["alive_before_reload"] = dev.alive()
                dev.bringup(*images, log=lambda *_: None)
                out["cleanup_reload_alive"] = dev.alive()
                out["reload_masks"] = masks(dev)
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        any(k.endswith("error_type") for k in out)
        or not out.get("cleanup_reload_alive")
        or not all(out.get("restored", {}).values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
