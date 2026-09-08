#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""One firmware-traced UNI36/tag2 histogram activation, no TX.

Resets shared histogram history on BOTH control indices. Requires exclusive
ownership and explicit acknowledgment. Restores four fixed volatile masks and
reloads normal firmware even on timeout. No arbitrary tags or register writes.
"""

import argparse
import datetime
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mt76_histogram import build_histogram_request, parse_histogram_event
from research import mt7925_noise_hist_probe as hist
from research import mt7925_uni_dispatch_probe as dispatch
from research.txpower_register_probe import check_image, m, read_words

MASKS = {0x83082004: 7, 0x83088230: 1 << 29, 0x83092004: 7, 0x83098230: 1 << 29}


def request():
    return build_histogram_request("mt7925")


def masked(address, word, bits):
    if (
        type(address) is not int
        or address not in MASKS
        or type(word) is not int
        or not 0 <= word < 0xFFFFFFFF
        or type(bits) is not int
        or bits < 0
        or bits & ~MASKS[address]
    ):
        raise ValueError("only four pinned histogram masks with valid readbacks")
    return word & ~MASKS[address] | bits


def restore(dev, address, bits):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 only")
    dev.wr(address, masked(address, dev.rr(address), bits))
    word = dev.rr(address)
    masked(address, word, 0)
    if word & MASKS[address] != bits:
        raise RuntimeError("histogram restore readback mismatch")


def event_body(raw):
    if len(raw) < 44:
        return None
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if (
        not 44 <= size <= len(raw)
        or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT
        or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
    ):
        return None
    return raw[36], raw[37], raw[44:size]


def summarize(raw):
    try:
        report = parse_histogram_event("mt7925", raw)
    except ValueError as exc:
        raise ValueError("unexpected noise event") from exc
    return {
        "event_id": 0x36,
        "sequence": 0,
        "body_bytes": 96,
        "tag": 2,
        "tag_length": 92,
        "timer_index0": list(report.bins[0]),
        "timer_index1": list(report.bins[1]),
    }


def activate(dev):
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(0x36, False) != 7:
        raise ValueError("pinned MT7925 SET/ACK option7 required")
    dev.mcu_uni(0x36, request(), query=False, wait=False)
    return dev.msg_seq


def collect(dev, started, sequence):
    out = {"matching_acknowledgments": [], "noise_events": [], "transfers_attempted": 0}
    deadline = started + 3.0
    while time.monotonic() < deadline and out["transfers_attempted"] < 2048:
        for ep in (dev.ep_in_pkt_rx, dev.ep_in_cmd_resp):
            out["transfers_attempted"] += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            parsed = event_body(raw)
            if parsed is None:
                continue
            eid, seq, body = parsed
            if eid == 0x36 and seq == 0:
                row = summarize(raw)
                row["host_elapsed_seconds"] = time.monotonic() - started
                row["endpoint"] = ep
                out["noise_events"].append(row)
                return out
            if eid == 1 and seq == sequence and len(body) == 8:
                cid, status = struct.unpack("<II", body)
                if cid == 0x36:
                    out["matching_acknowledgments"].append({"cid": cid, "status": status})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-noise-histogram", action="store_true")
    parser.add_argument("--channel", type=int, choices=hist.CHANNELS, default=6)
    args = parser.parse_args()
    if not args.activate_noise_histogram:
        parser.error("explicit BOTH-index reset/enable acknowledgment required")
    images = m.load_firmware(m.CHIP_MT7925, m.firmware_dir())
    check_image(images[1])
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "firmware_sha256": [hashlib.sha256(b).hexdigest() for b in images],
        "channel": args.channel,
        "request_hex": request().hex(),
    }
    original, activated = {}, False
    with m.open_device("0846:9072") as dev:

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel <= 11 else "5GHz", args.channel, args.channel, 20)

        try:
            boot()
            out["code"] = hist.verify(dev) + dispatch.verify(dev)[:1]
            if not all(row["matches"] for row in out["code"]):
                raise ValueError("live histogram/dispatcher code mismatch")
            record = read_words(dev, 0x0221C04C, 8)
            if (
                struct.unpack_from("<H", record)[0] != 0x36
                or struct.unpack_from("<I", record, 4)[0] != 0xE0053786
            ):
                raise ValueError("noise command dispatch mismatch")
            for address, mask in MASKS.items():
                word = dev.rr(address)
                masked(address, word, 0)
                original[address] = word & mask
            out["original_masked_bits"] = {hex(a): b for a, b in original.items()}
            if any(original.values()):
                raise RuntimeError("a histogram index is already enabled or reset asserted")
            activated = True
            started = time.monotonic()
            sequence = activate(dev)
            out["request_sequence"] = sequence
            out["collection"] = collect(dev, started, sequence)
            out["after_event_controls"] = hist.controls(dev)
            out["after_event_banks"] = hist.banks(dev, True)
            time.sleep(0.05)
            out["after_event_banks_repeat"] = hist.banks(dev, True)
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if activated:
                out["restored"] = {}
                for address, bits in original.items():
                    try:
                        restore(dev, address, bits)
                        out["restored"][hex(address)] = True
                    except Exception as exc:
                        out["restored"][hex(address)] = type(exc).__name__
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or not out.get("alive_after")
        or not out.get("cleanup_reload_alive")
        or any(v is not True for v in out.get("restored", {}).values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
