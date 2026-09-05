#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Pinned MT7961 CE93 RMAC diagnostics, bounded passive off/on/off and cleanup.

No TX, filter changes, PHY capture, opaque vector export or nonvolatile writes.
All four code windows and the relocated command record must match before START.
"""

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

import mt7921u as m
from research import rmac_ics_match as matching
from research.icap_status_probe import event_summary
from research.ics_control_probe import valid_word
from research.noise_self_tx_probe import OLD_RAM_SHA256
from research.rmac_ics_probe import aggregate_shape
from research.rmac_ics_probe import request as uni_request
from research.rx_vector_probe import DMA_DCR0, G5_ENABLE

MASKS = {0x820E50D0: 1, 0x820E705C: 1 << 24, 0x820E0004: (1 << 9) | (1 << 2), DMA_DCR0: G5_ENABLE}
WINDOWS = (
    (0x922CE4, 264, "cecd96d129e9f8aad976d02b514221c6a827f6307dfb61f74823ecf7ee71a043"),
    (0x96966C, 72, "420cd8569ea94754005f63cff51f9820f27532f5066b93780aeb6ce66110c097"),
    (0x93A3EC, 72, "0a6b5a5bf1d4d4d624f9e7a90d260056a68876b8cf4bb68a169efe1515fa2dd3"),
    (0x9369F8, 120, "44189697bbf47f7f75721622821279f58e8b769aa76f46d07e6818c4beeb4699"),
)
TABLE_WORDS = {0x02026114: 70, 0x02026338: 0x93, 0x0202633C: 0x922CE6}


def request(start):
    # Same84-byte source CMD_ICS_SNIFFER_INFO, without UNI header/TLV.
    return uni_request(start)[8:]


def verify(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned MT7961 only")
    out = {"code_windows": [], "command_record": {}}
    for address, size, expected in WINDOWS:
        raw = b"".join(
            struct.pack("<I", valid_word(dev.rr(a))) for a in range(address, address + size, 4)
        )
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected:
            raise ValueError("pinned live code mismatch")
        out["code_windows"].append({"address": hex(address), "bytes": size, "sha256": digest})
    for address, expected in TABLE_WORDS.items():
        value = valid_word(dev.rr(address))
        if value != expected:
            raise ValueError("relocated CE93 record mismatch")
        out["command_record"][hex(address)] = hex(value)
    return out


def masks(dev):
    return {hex(a): valid_word(dev.rr(a)) & mask for a, mask in MASKS.items()}


def restore(dev, originals):
    if dev.CHIP != m.CHIP_MT7921 or set(originals) != set(MASKS):
        raise ValueError("only pinned legacy diagnostic masks")
    out = {}
    for a, mask in MASKS.items():
        value = originals[a]
        if type(value) is not int or value < 0 or value & ~mask:
            raise ValueError("invalid original mask")
        dev.wr(a, valid_word(dev.rr(a)) & ~mask | value)
        out[hex(a)] = valid_word(dev.rr(a)) & mask == value
    return out


def send(dev, enabled):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("legacy CE93 only")
    dev.mcu_cmd_word(m.MCU_CE_CMD(0x93), request(enabled), wait=False, timeout=1000)
    return dev.msg_seq


def collect(dev, sequence=None, match_rxd=False):
    types, shapes, phy = collections.Counter(), collections.Counter(), collections.Counter()
    events, attempts, malformed = [], 0, 0
    normal, aggregates = [], []  # Bounded local-only traffic, reduced before returning.
    start = time.monotonic()
    decoder = m.decoder_for(dev)
    while time.monotonic() - start < 0.4 and attempts < 512:
        for ep in dict.fromkeys((dev.ep_in_pkt_rx, dev.ep_in_cmd_resp)):
            attempts += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            if len(raw) >= 4:
                kind = struct.unpack_from("<I", raw)[0] >> 27
                types[(ep, kind)] += 1
                if match_rxd and kind == 2 and len(normal) < matching.LIMIT:
                    normal.append(bytes(raw))
            decoded = decoder(raw)
            if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
                phy[decoded.get("phy", {}).get("mode_name", "unknown")] += 1
            try:
                shape = aggregate_shape(raw)
                if shape:
                    shapes[(ep, shape["type"], shape["bytes"], shape["frame_count"])] += 1
                    if match_rxd and len(aggregates) < matching.LIMIT:
                        aggregates.append(bytes(raw[: shape["bytes"]]))
            except ValueError:
                malformed += 1
            event = event_summary(raw, sequence)
            if event and event["sequence_matches"]:
                row = {k: event[k] for k in ("eid", "ext_eid", "body_bytes", "sequence_matches")}
                size = struct.unpack_from("<H", raw)[0]
                if event["body_bytes"] == 8 and struct.unpack_from("<I", raw, 36)[0] == 0x93:
                    row["command_result_status"] = struct.unpack_from("<I", raw[:size], 40)[0]
                events.append(row)
    return {
        "elapsed_seconds": time.monotonic() - start,
        "attempts": attempts,
        "good_fcs_by_phy": dict(phy),
        "leading_packet_types": [
            {"endpoint": ep, "type": kind, "count": n} for (ep, kind), n in sorted(types.items())
        ],
        "aggregate_shapes": [
            {"endpoint": ep, "type": kind, "bytes": size, "frame_count": frames, "count": n}
            for (ep, kind, size, frames), n in sorted(shapes.items())
        ],
        "invalid_aggregate_lengths": malformed,
        "matched_events": events,
        "in_memory_matching": matching.reduce_matches(normal, aggregates, legacy=True)
        if match_rxd
        else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-legacy-rmac-ics", action="store_true")
    parser.add_argument("--match-rxd-in-memory", action="store_true")
    parser.add_argument("--enable-group5", action="store_true")
    parser.add_argument("--channel", type=int, choices=(6, 36), default=6)
    args = parser.parse_args()
    if not args.activate_legacy_rmac_ics:
        parser.error("explicit legacy RMAC diagnostic acknowledgment required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": args.channel,
        "request_hex": request(True).hex(),
    }
    originals, attempted = {}, False
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        if hashlib.sha256(images[1]).hexdigest() != OLD_RAM_SHA256:
            raise ValueError("pinned image required")

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel == 6 else "5GHz", args.channel, args.channel, 20)

        try:
            boot()
            out["verified"] = verify(dev)
            originals = {a: valid_word(dev.rr(a)) & mask for a, mask in MASKS.items()}
            if originals[0x820E50D0] or originals[0x820E705C] or valid_word(dev.rr(0x820E4120)) & 1:
                raise ValueError("MAC diagnostics already enabled")
            out["before_masks"] = masks(dev)
            if args.enable_group5:
                # Previously qualified mt792x RXD-report mask; not a PHY gain/control.
                attempted = True
                dev.wr(DMA_DCR0, valid_word(dev.rr(DMA_DCR0)) | G5_ENABLE)
            out["group5_requested"] = args.enable_group5
            out["off_before"] = collect(dev, match_rxd=args.match_rxd_in_memory)
            attempted = True
            out["on"] = collect(dev, send(dev, True), args.match_rxd_in_memory)
            out["on_masks"] = masks(dev)
            out["off_after"] = collect(dev, send(dev, False), args.match_rxd_in_memory)
            out["off_after_masks"] = masks(dev)
            out["alive_after"] = dev.alive()
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
                boot()
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
