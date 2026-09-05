#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (C) 2023 MediaTek Inc.
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Try bounded HT/VHT/HE fixed-rate TX, with independent receiver evidence.

At most 60 synthetic no-ACK probes, 50 ms spacing, channel 36/149 at 20 MHz.
Known OFDM controls bracket the candidate rates. No association or ambient frame
output. Full firmware reload in finally removes all experimental transmitter state.
Requires explicit TX acknowledgment. This is research, not a production API.
"""

import argparse
import collections
import concurrent.futures
import contextlib
import datetime
import hashlib
import json
import os
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research import mt7925_tx_probe as c3
from research.dual_radio_probe import fixed_rate_txwi, tx_status_records

# mt76 c5a3bd91: mt76.h enum mt76_phy_type; connac2/3_mac.h
# MT_TX_RATE_MODE bits 9:6, IDX bits 5:0, NSS bits starting at 10.
# One stream, MCS 0/7, bandwidth 20; no short GI, STBC or power changes.
RATES = (
    ("ofdm_before", 0x4B),
    ("ht0", 2 << 6),
    ("ht7", (2 << 6) | 7),
    ("vht0", 4 << 6),
    ("he0", 8 << 6),
    ("ofdm_after", 0x4B),
)


def descriptor(dev, frame, seq, code, fixed_bw=False):
    if code not in {rate for _, rate in RATES}:
        raise ValueError("rate outside bounded experiment")
    if dev.CHIP == m.CHIP_MT7925:
        data = bytearray(c3.build_txwi(frame, seq, disable_mat=True))
        if fixed_bw:
            # connac3_mac.h MT_TXD6_FIXED_BW bit 25; BW bits 24:22 = 0 (20 MHz).
            word = struct.unpack_from("<I", data, 24)[0]
            struct.pack_into("<I", data, 24, word | (1 << 25))
        return bytes(data)
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("unsupported chip")
    data = bytearray(fixed_rate_txwi(dev, frame, seq, "ofdm6", True))
    struct.pack_into("<I", data, 24, m.MT_TXD6_FIXED_BW | (code << 16))
    return bytes(data)


def program_rate(dev, code):
    if code not in {rate for _, rate in RATES}:
        raise ValueError("rate outside bounded experiment")
    if dev.CHIP != m.CHIP_MT7925:
        return
    # mt7925/mac.c mt7925_mac_set_fixed_rate_table at c5a3bd91.
    dev.wr(c3.ITDR0, code)
    dev.wr(c3.ITDR1, 1 << 6)
    dev.wr(c3.ITCR, (1 << 31) | (1 << 16) | c3.RATE_TABLE_INDEX)
    for _ in range(100):
        if not dev.rr(c3.ITCR) & (1 << 31):
            return
        time.sleep(0.001)
    raise RuntimeError("rate table busy")


def capture(dev, expected, per_phase, ready, stop):
    decode = m.decoder_for(dev)
    seen = [set() for _ in RATES]
    phys = [collections.Counter() for _ in RATES]
    status = collections.Counter()
    counts = collections.Counter()
    ready.set()
    while not stop.is_set():
        try:
            raw = bytes(dev.rx_read(timeout=100))
        except usb.core.USBTimeoutError:
            continue
        d = decode(raw)
        if not d:
            continue
        if d["pkt_type"] == 0:
            rows = c3.tx_status(raw) if dev.CHIP == m.CHIP_MT7925 else tx_status_records(raw)
            for row in rows:
                status[json.dumps(row, sort_keys=True)] += 1
        frame = d.get("frame", b"")
        if len(frame) < 24:
            continue
        seq = struct.unpack_from("<H", frame, 22)[0] >> 4
        if expected.get(seq) != frame:
            continue
        if d.get("fcs_err"):
            counts["controlled_fcs_errors"] += 1
            continue
        phase = seq // per_phase
        seen[phase].add(seq)
        phy = d.get("phy", {})
        fields = {
            k: phy.get(k) for k in ("mode_name", "mcs", "nss", "bw_mhz", "gi", "ldpc", "rate_mbps")
        }
        phys[phase][json.dumps(fields, sort_keys=True)] += 1
    return {
        "chip": dev.CHIP,
        "counts": dict(counts),
        "phases": [
            {
                "name": name,
                "rate_code": code,
                "unique_exact_frames": len(seen[i]),
                "phy": [{"fields": json.loads(k), "count": v} for k, v in phys[i].items()],
            }
            for i, (name, code) in enumerate(RATES)
        ],
        "tx_status": [{"fields": json.loads(k), "count": v} for k, v in status.items()],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--transmitter", choices=("mt7961", "mt7925"), required=True)
    p.add_argument("--channel", type=int, choices=(36, 149), default=36)
    p.add_argument("--per-phase", type=int, choices=range(1, 11), default=5)
    p.add_argument("--acknowledge-experimental-transmit", action="store_true")
    p.add_argument("--fixed-bw", action="store_true", help="connac3 explicit 20 MHz TXD flag")
    args = p.parse_args()
    if not args.acknowledge_experimental_transmit:
        p.error("explicit transmit acknowledgment required")
    if args.fixed_bw and args.transmitter != "mt7925":
        p.error("fixed-bw variant applies only to mt7925")
    out = {
        "tool": "phy_tx_probe",
        "date_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "transmitter": args.transmitter,
        "channel": args.channel,
        "per_phase": args.per_phase,
        "gap_s": 0.05,
        "fixed_bw": args.fixed_bw,
        "submitted": 0,
        "firmware_sha256": {},
    }
    tx_index = int(args.transmitter == "mt7925")
    expected = {seq: c3.controlled_frame(seq) for seq in range(6 * args.per_phase)}
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", args.channel, args.channel, 20)

        for i, dev in enumerate(radios):
            boot(i)
            out["firmware_sha256"][dev.CHIP] = [hashlib.sha256(b).hexdigest() for b in images[i]]
        tx = radios[tx_index]
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                stop = threading.Event()
                ready = [threading.Event(), threading.Event()]
                jobs = [
                    pool.submit(capture, dev, expected, args.per_phase, ready[i], stop)
                    for i, dev in enumerate(radios)
                ]
                try:
                    if not all(event.wait(5) for event in ready):
                        raise RuntimeError("capture not ready")
                    time.sleep(0.3)
                    for phase, (_, code) in enumerate(RATES):
                        program_rate(tx, code)
                        for seq in range(phase * args.per_phase, (phase + 1) * args.per_phase):
                            if any(job.done() for job in jobs):
                                raise RuntimeError("capture stopped before transmit completed")
                            frame = expected[seq]
                            body = descriptor(tx, frame, seq, code, args.fixed_bw) + frame
                            wire = struct.pack("<I", len(body)) + body
                            wire += bytes((-len(wire)) % 4 + 4)
                            tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                            out["submitted"] += 1
                            time.sleep(0.05)
                        time.sleep(0.15)
                    time.sleep(0.5)
                finally:
                    stop.set()
                out["radios"] = [job.result(timeout=3) for job in jobs]
            out["alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                boot(tx_index)
                out["cleanup_reload_alive"] = tx.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2, sort_keys=True))
    return int(
        "error_type" in out
        or not out.get("cleanup_reload_alive")
        or not all(out.get("alive_after", [False]))
    )


if __name__ == "__main__":
    raise SystemExit(main())
