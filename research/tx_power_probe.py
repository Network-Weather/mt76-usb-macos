#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Test per-packet TX power-offset codes against an independent receive vector.

Explicitly gated TX: 100 directed no-ACK OFDM probes, 50 ms apart, 20 MHz on
5 GHz channel 36 or 149. Alternate zero and hypothesized negative signed codes.
No persistent power configuration changes; no absolute dBm claim. Both receivers
run throughout. No ambient frame bytes/identifiers are serialized.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import contextlib
import datetime
import hashlib
import json
import os
import statistics
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.dual_radio_probe import SOURCE, SSID, fixed_rate_txwi
from research.rx_vector_probe import vectors

PHASES = (0, -8, 0, -16, 0)
FRAMES = 20


def power_txwi(dev, frame, seq, offset):
    # mt76 c5a3bd91 mt76_connac2_mac.h MT_TXD2_POWER_OFFSET bits29:24.
    # Signed six-bit interpretation and units are hypotheses under test.
    if not -32 <= offset <= 0:
        raise ValueError("only zero or candidate attenuation codes allowed")
    txwi = bytearray(fixed_rate_txwi(dev, frame, seq, "ofdm6", True))
    (word,) = struct.unpack_from("<I", txwi, 8)
    word = (word & ~(63 << 24)) | ((offset & 63) << 24)
    struct.pack_into("<I", txwi, 8, word)
    return bytes(txwi)


def stats(values):
    if not values:
        return None
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def signed8(value):
    return (value & 127) - (value & 128)


def capture(dev, seconds, barrier):
    decode = m.decoder_for(dev)
    counts = collections.Counter()
    records = collections.defaultdict(list)
    statuses = collections.defaultdict(list)
    barrier.wait(timeout=15)
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        try:
            raw = bytes(dev.rx_read(timeout=150))
        except usb.core.USBTimeoutError:
            continue
        except usb.core.USBError:
            counts["usb_errors"] += 1
            break
        d = decode(raw)
        if not d:
            continue
        counts[d["pkt_type_name"]] += 1
        if d["pkt_type"] == 0 and dev.CHIP == m.CHIP_MT7921:
            end = min(len(raw), int.from_bytes(raw[:2], "little"))
            for offset in range(8, end - 31, 32):
                # MT_TXS1_SEQNO and MT_TXS1_TX_POWER_DBM, connac2 header.
                (word,) = struct.unpack_from("<I", raw, offset + 4)
                seq = word >> 20
                if seq < FRAMES * len(PHASES):
                    statuses[seq // FRAMES].append(word & 255)
            continue
        frame = d.get("frame", b"")
        if len(frame) < 24 or frame[10:16] != SOURCE or d.get("fcs_err"):
            continue
        seq = struct.unpack_from("<H", frame, 22)[0] >> 4
        if seq >= FRAMES * len(PHASES):
            continue
        group = vectors(raw, dev.CHIP).get("g5")
        row = {"seq": seq, "rssi": d.get("rssi"), "mode": d.get("phy", {}).get("mode_name")}
        if group and len(group) == 24:
            # Neighboring mt7915 standalone RXV hypotheses, not established connac3 units.
            row["ib0_signed_candidate"] = signed8(group[7])
            row["ib1_signed_candidate"] = signed8(group[7] >> 8)
            row["wb0_signed_candidate"] = signed8(group[8] >> 5)
            row["snr_candidate"] = ((group[20] >> 13) & 63) - 16
            row["foe_raw_candidate"] = (group[20] >> 19) | ((group[21] & 127) << 13)
        records[seq // FRAMES].append(row)
    phases = []
    for phase, offset in enumerate(PHASES):
        rows = records[phase]
        keys = (
            "rssi",
            "ib0_signed_candidate",
            "ib1_signed_candidate",
            "wb0_signed_candidate",
            "snr_candidate",
            "foe_raw_candidate",
        )
        phases.append(
            {
                "phase": phase,
                "requested_signed_code": offset,
                "received": len(rows),
                "unique_sequences": len({r["seq"] for r in rows}),
                "phy_modes": dict(collections.Counter(r["mode"] for r in rows)),
                "tx_status_power_raw": stats(statuses[phase]),
                "receiver_metrics": {
                    key: stats([r[key] for r in rows if r.get(key) is not None]) for key in keys
                },
            }
        )
    return {"chip": dev.CHIP, "counts": dict(counts), "phases": phases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, choices=(36, 149), default=36)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit transmit acknowledgment required")
    result = {
        "tool": "tx_power_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": args.channel,
        "gap_s": 0.05,
        "frames_per_phase": FRAMES,
        "offset_codes": PHASES,
        "firmware_sha256": {},
    }
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        for dev in radios:
            patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
            result["firmware_sha256"][dev.CHIP] = {
                "patch": hashlib.sha256(patch).hexdigest(),
                "ram": hashlib.sha256(ram).hexdigest(),
            }
            dev.bringup(patch, ram, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", args.channel, args.channel, 20)
        barrier = threading.Barrier(3)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(capture, dev, 12, barrier) for dev in radios]
            barrier.wait(timeout=15)
            time.sleep(0.5)
            submitted = 0
            for phase, offset in enumerate(PHASES):
                for i in range(FRAMES):
                    seq = phase * FRAMES + i
                    frame = m.build_probe_request(SOURCE, SSID, seq)
                    frame = frame[:-6] + bytes((1, 1, 0x8C))
                    body = power_txwi(radios[0], frame, seq, offset) + frame
                    wire = struct.pack("<I", len(body)) + body
                    wire += b"\x00" * ((-len(wire)) % 4 + 4)
                    radios[0].bulk_out(radios[0].ep_out_ac_be, wire, 1000)
                    submitted += 1
                    time.sleep(0.05)
            result["submitted"] = submitted
            result["radios"] = [job.result(timeout=25) for job in jobs]
        result["register_alive_after"] = [dev.alive() for dev in radios]
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 1 if any(r["counts"].get("usb_errors") for r in result["radios"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
