#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Controlled 20 MHz OFDM visibility inside an 80 MHz receive configuration.

Seven phases, 12 no-ACK directed probes each, 50 ms spacing: 84 frames total.
Transmit is only on 5 GHz channels 36/44 at 20 MHz. Both radios receive throughout
each phase; their roles can be reversed. Requires explicit transmit acknowledgment.
No ambient frame bytes or identifiers are saved. MT7925 transmitter table state
is cleared by firmware reload in cleanup. Production drivers remain unchanged.
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
from research.dual_radio_probe import SOURCE, fixed_rate_txwi
from research.mt7925_tx_probe import build_txwi, set_ofdm_rate

SSID = b"mt76-channel-geometry"
FRAMES = 12
# TX primary, RX primary, RX center, RX width. Same 80 MHz center, swapped primary.
PHASES = (
    (36, 36, 36, 20),
    (36, 36, 42, 80),
    (44, 36, 42, 80),
    (44, 44, 44, 20),
    (44, 44, 42, 80),
    (36, 44, 42, 80),
    (36, 36, 36, 20),
)


def probe_frame(sequence):
    frame = m.build_probe_request(SOURCE, SSID, sequence)
    return frame[:-6] + bytes((1, 1, 0x8C))


def phase_sequence(sequence, phase):
    return phase * FRAMES <= sequence < (phase + 1) * FRAMES


def status_records(raw, chip):
    # mt7921/mt7925 rx_check and connac2/3 headers at mt76 c5a3bd91:
    # prefixes 2/4 DW, records 8/12 DW, shared TXS0/TXS1 field geometry.
    prefix, stride = (8, 32) if chip == m.CHIP_MT7921 else (16, 48)
    end = min(len(raw), int.from_bytes(raw[:2], "little"))
    rows = []
    for off in range(prefix, end - stride + 1, stride):
        word0, word1 = struct.unpack_from("<II", raw, off)
        rows.append(
            {
                "sequence": word1 >> 20,
                "rate_raw": word0 & 0x3FFF,
                "power_raw": word1 & 255,
                "error_bits": (word0 >> 16) & 127,
            }
        )
    return rows


def capture(dev, phase, barrier):
    decode = m.decoder_for(dev)
    counts, phys, channels, tx = (collections.Counter() for _ in range(4))
    sequences, signals = set(), []
    barrier.wait(timeout=10)
    started = time.monotonic()
    while time.monotonic() - started < 3:
        try:
            raw = bytes(dev.rx_read(timeout=100))
        except usb.core.USBTimeoutError:
            continue
        except usb.core.USBError:
            counts["usb_errors"] += 1
            break
        d = decode(raw)
        if not d:
            continue
        counts[d["pkt_type_name"]] += 1
        if d["pkt_type"] == 0:
            for row in status_records(raw, dev.CHIP):
                if phase_sequence(row.pop("sequence"), phase):
                    tx[json.dumps(row, sort_keys=True)] += 1
        frame = d.get("frame", b"")
        if len(frame) < 24 or frame[10:16] != SOURCE:
            continue
        seq = struct.unpack_from("<H", frame, 22)[0] >> 4
        if not phase_sequence(seq, phase) or frame != probe_frame(seq):
            continue
        if d.get("fcs_err"):
            counts["controlled_fcs_errors"] += 1
            continue
        sequences.add(seq)
        counts["controlled_byte_exact"] += 1
        p = d.get("phy", {})
        phys[f"{p.get('mode_name')}:{p.get('rate_mbps')}:{p.get('bw_mhz')}"] += 1
        channels[f"{d.get('band')}:{d.get('channel')}"] += 1
        if d.get("rssi") is not None:
            signals.append(d["rssi"])
    return {
        "chip": dev.CHIP,
        "counts": dict(counts),
        "unique_sequences": len(sequences),
        "controlled_phy": dict(phys),
        "descriptor_channels": dict(channels),
        "median_rssi": statistics.median(signals) if signals else None,
        "tx_status": [{"fields": json.loads(k), "count": n} for k, n in tx.items()],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transmitter", choices=("mt7921", "mt7925"), default="mt7921")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit transmit acknowledgment required")
    result = {
        "tool": "channel_geometry_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transmitter": args.transmitter,
        "frames_per_phase": FRAMES,
        "gap_s": 0.05,
        "firmware_sha256": {},
        "phases": [],
    }
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = {}
        for dev in radios:
            patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
            images[dev.CHIP] = (patch, ram)
            result["firmware_sha256"][dev.CHIP] = {
                "patch": hashlib.sha256(patch).hexdigest(),
                "ram": hashlib.sha256(ram).hexdigest(),
            }
            dev.bringup(patch, ram, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
        transmitter = next(d for d in radios if args.transmitter == d.CHIP)
        observer = next(d for d in radios if d is not transmitter)
        try:
            if transmitter.CHIP == m.CHIP_MT7925:
                result["rate_table"] = set_ofdm_rate(transmitter)
            for phase, (tc, rc, center, width) in enumerate(PHASES):
                transmitter.tune("5GHz", tc, tc, 20)
                observer.tune("5GHz", rc, center, width)
                barrier = threading.Barrier(3)
                row = {
                    "phase": phase,
                    "tx_channel": tc,
                    "rx_primary": rc,
                    "rx_center": center,
                    "rx_width_mhz": width,
                    "submitted": 0,
                }
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    jobs = [pool.submit(capture, dev, phase, barrier) for dev in radios]
                    barrier.wait(timeout=10)
                    time.sleep(0.3)
                    for i in range(FRAMES):
                        seq = phase * FRAMES + i
                        frame = probe_frame(seq)
                        txwi = (
                            fixed_rate_txwi(transmitter, frame, seq, "ofdm6", True)
                            if transmitter.CHIP == m.CHIP_MT7921
                            else build_txwi(frame, seq, disable_mat=True)
                        )
                        body = txwi + frame
                        wire = struct.pack("<I", len(body)) + body
                        wire += b"\x00" * ((-len(wire)) % 4 + 4)
                        transmitter.bulk_out(transmitter.ep_out_ac_be, wire, 1000)
                        row["submitted"] += 1
                        time.sleep(0.05)
                    row["radios"] = [job.result(timeout=10) for job in jobs]
                row["register_alive_after"] = [dev.alive() for dev in radios]
                result["phases"].append(row)
                print(
                    json.dumps(
                        {
                            "phase": phase,
                            "tx_channel": tc,
                            "rx_primary": rc,
                            "width": width,
                            "received": next(
                                r["unique_sequences"]
                                for r in row["radios"]
                                if r["chip"] == observer.CHIP
                            ),
                        }
                    ),
                    flush=True,
                )
                if not all(row["register_alive_after"]) or any(
                    r["counts"].get("usb_errors") for r in row["radios"]
                ):
                    raise RuntimeError("radio health check failed; stopping transmissions")
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
        finally:
            try:
                if transmitter.CHIP == m.CHIP_MT7925:
                    transmitter.bringup(*images[transmitter.CHIP], log=lambda *_: None)
                    transmitter.set_monitor_mode()
                    transmitter.set_sniffer(True)
                    result["transmitter_firmware_reloaded"] = True
                for dev in radios:
                    dev.tune("5GHz", 36, 36, 20)
                result["cleanup_alive"] = [dev.alive() for dev in radios]
            except Exception as exc:
                result["cleanup_error"] = type(exc).__name__ + ": " + str(exc)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return int(
        "error" in result
        or "cleanup_error" in result
        or not all(result.get("cleanup_alive", [False]))
    )


if __name__ == "__main__":
    raise SystemExit(main())
