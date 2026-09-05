#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Passive RX-vector report off/on/off control, normal mode only.

UNI08/tag1/length8, RX-enable byte and TX-enable byte, from pinned gen4m.
Explicitly enables RX reporting only; no TX, EDCCA changes, RF mode or raw export.
Each window is one second/512 transfers. OFF and full firmware reload on exit.
An ACK alone is not evidence that the requested reporting mode works.
"""

import argparse
import collections
import contextlib
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.rx_vector_probe import vectors


def report_register(dev):
    """MT7925 tag1 -> ROM keys0x620/621 -> ARB0x3014 bits8/7."""
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925-only traced report register")
    word = dev.rr(0x820E3014)
    if type(word) is not int or not 0 <= word < 0xFFFFFFFF:
        raise ValueError("invalid report register")
    return {
        "register": "0x820e3014",
        "raw": hex(word),
        "rx_bit7": (word >> 7) & 1,
        "tx_bit8": (word >> 8) & 1,
    }


def request(enabled):
    if type(enabled) is not bool:
        raise ValueError("boolean RX-only report control required")
    return struct.pack("<4xHHBB2x", 1, 8, int(enabled), 0)


def receive(dev, both_endpoints=False):
    counts = collections.Counter()
    groups = collections.Counter()
    other_sizes = collections.Counter()
    endpoints = collections.Counter()
    decoder = m.decoder_for(dev)
    started = time.monotonic()
    transfers = 0
    reads = 0
    selected = (dev.ep_in_pkt_rx, dev.ep_in_cmd_resp) if both_endpoints else (dev.ep_in_pkt_rx,)
    while time.monotonic() - started < 1 and transfers < 512:
        endpoint = selected[reads % len(selected)]
        reads += 1
        try:
            raw = bytes(dev.bulk_in(endpoint, 4096, 20 if both_endpoints else 50))
        except usb.core.USBTimeoutError:
            continue
        transfers += 1
        endpoints[f"{endpoint:02x}"] += 1
        packet = decoder(raw)
        if not packet:
            counts["short"] += 1
            continue
        name = packet["pkt_type_name"]
        counts[name] += 1
        if packet.get("frame"):
            counts["good_fcs_frames" if not packet.get("fcs_err") else "fcs_error_frames"] += 1
            group = vectors(raw, dev.CHIP)
            groups[str(group.get("mask", "error"))] += 1
        elif len(raw) >= 4:
            size = struct.unpack_from("<H", raw)[0]
            other_sizes[(name, size)] += 1
    return {
        "transfers": transfers,
        "elapsed_seconds": time.monotonic() - started,
        "limit_reached": transfers == 512,
        "packet_types": dict(counts),
        "endpoint_transfers": dict(endpoints),
        "frame_group_masks": dict(groups),
        "non_frame_sizes": [
            {"type": k[0], "size": k[1], "count": v} for k, v in other_sizes.items()
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chip", choices=("mt7961", "mt7925"), required=True)
    parser.add_argument("--enable-reporting", action="store_true")
    parser.add_argument("--registers", action="store_true", help="MT7925 exact report-bit readback")
    parser.add_argument(
        "--both-endpoints",
        action="store_true",
        help="also inspect the descriptor-resolved command-response IN endpoint",
    )
    args = parser.parse_args()
    if not args.enable_reporting:
        parser.error("explicit receive-report configuration opt-in required")
    if args.registers and args.chip != "mt7925":
        parser.error("register cross-check is MT7925-only")
    out = {
        "tool": "rxv_report_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "chip": args.chip,
        "channel": 1,
        "both_endpoints": args.both_endpoints,
        "rows": [],
    }
    uid = "0e8d:7961" if args.chip == "mt7961" else "0846:9072"
    with m.open_device(uid) as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 1, 1, 20)

        def control(enabled):
            if dev.uni_option(8, False) != 7:
                raise ValueError("SET/UNI/ACK option7 required")
            raw = dev.mcu_uni(8, request(enabled), query=False, timeout=1000)
            body = dev.reply_body(raw)
            result = {"body_bytes": len(body)}
            if len(body) >= 8 and struct.unpack_from("<I", body)[0] == 8:
                result["command_result_status"] = struct.unpack_from("<I", body, 4)[0]
            return result

        try:
            boot()
            if args.registers:
                out["hardware_initial"] = report_register(dev)
            for enabled in (False, True, False):
                row = {"rx_report_requested": enabled}
                out["rows"].append(row)
                row["reply"] = control(enabled)
                if row["reply"].get("command_result_status") not in (None, 0):
                    raise RuntimeError("report command refused")
                if args.registers:
                    row["hardware_before"] = report_register(dev)
                row["window"] = receive(dev, args.both_endpoints)
                if args.registers:
                    row["hardware_after"] = report_register(dev)
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                out["cleanup_off"] = control(False)
            except Exception as exc:
                out["cleanup_off_error_type"] = type(exc).__name__
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
                if args.registers:
                    out["hardware_after_reload"] = report_register(dev)
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
