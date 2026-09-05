#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""STOP-only station radar-detector transport check on pinned MT7961/MT7925.

gen4m 8fddb9d7: CE8F eight-byte control, or UNI19/tag0/length12.
Only ctrl/index/rxsel/setval=0. No START, emulation, TXQ, thresholds or TX.
Normal channel36/20; two bounded dual-endpoint collections; full reload on exit.
Only event metadata and aggregate frame counts leave the receive loop.
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


def request(chip):
    if chip == m.CHIP_MT7921:
        return bytes(8)
    if chip == m.CHIP_MT7925:
        return struct.pack("<4xHH8x", 0, 12)
    raise ValueError("only pinned MT7961/MT7925")


def summarize(raw, chip, sequence):
    request(chip)
    header = 44 if chip == m.CHIP_MT7925 else 36
    offset = header - 8
    if len(raw) < header:
        return None
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if (
        not header <= size <= len(raw)
        or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT
        or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
    ):
        return None
    eid, seq = raw[offset : offset + 2]
    ext = raw[offset + 4]
    candidate = (
        eid == 0x11
        if chip == m.CHIP_MT7925
        else eid in (0x50, 0x60) or (eid == 0xED and ext == 0x3A)
    )
    if seq != sequence and not (candidate and seq == 0):
        return None
    body = raw[header:size]
    out = {
        "eid": eid,
        "ext_eid": ext,
        "sequence_matches": seq == sequence,
        "body_bytes": len(body),
        "candidate_rdd_event": candidate,
    }
    if eid == 0xFD:
        out["command_not_found_event"] = True
    cid = 0x19 if chip == m.CHIP_MT7925 else 0x8F
    if eid == 1 and seq == sequence and len(body) == 8 and struct.unpack_from("<I", body)[0] == cid:
        out["command_result_status"] = struct.unpack_from("<I", body, 4)[0]
    return out


def stop(dev):
    payload = request(dev.CHIP)
    if dev.CHIP == m.CHIP_MT7925:
        if dev.uni_option(0x19, False) != 7:
            raise ValueError("explicit UNI SET ACK7 required")
        dev.mcu_uni(0x19, payload, query=False, wait=False, timeout=1000)
    else:
        dev.mcu_cmd_word(m.MCU_CE_CMD(0x8F), payload, wait=False, timeout=1000)
    return collect(dev)


def collect(dev):
    """Collect metadata for the last command; never send any command."""
    sequence = dev.msg_seq
    started = time.monotonic()
    transfers = reads = 0
    frames = collections.Counter()
    endpoints = collections.Counter()
    events = []
    selected = (dev.ep_in_pkt_rx, dev.ep_in_cmd_resp)
    while time.monotonic() - started < 1 and transfers < 512:
        endpoint = selected[reads % 2]
        reads += 1
        try:
            # A quiet second endpoint must not throttle the busy one to50 reads/s.
            raw = bytes(dev.bulk_in(endpoint, 4096, 1))
        except usb.core.USBTimeoutError:
            continue
        transfers += 1
        endpoints[f"{endpoint:02x}"] += 1
        decoded = m.decoder_for(dev)(raw)
        if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
            frames[str(decoded.get("phy", {}).get("mode"))] += 1
        event = summarize(raw, dev.CHIP, sequence)
        if event is not None:
            events.append(event)
    return {
        "events": events,
        "good_fcs_frames_by_phy_mode": dict(frames),
        "endpoint_transfers": dict(endpoints),
        "transfers": transfers,
        "transfer_limit_reached": transfers == 512,
        "endpoint_timeout_ms": 1,
        "elapsed_seconds": time.monotonic() - started,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chip", choices=("mt7961", "mt7925"), required=True)
    args = parser.parse_args()
    out = {
        "tool": "rdd_stop_probe",
        "chip": args.chip,
        "channel": 36,
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": [],
    }
    with m.open_device("0e8d:7961" if args.chip == "mt7961" else "0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        try:
            boot()
            for _ in range(2):
                out["rows"].append(stop(dev))
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out or not out.get("alive_after") or not out.get("cleanup_reload_alive")
    )


if __name__ == "__main__":
    raise SystemExit(main())
