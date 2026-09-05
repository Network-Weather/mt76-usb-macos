#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Twelve CCK/HT2SS/CCK probes with independent RX and latched CN/EVM reads.

Channel1/20MHz only; no receiver writes or power changes. Reads after matching
frames are not atomic per-frame metadata. Both radios reload in finally.
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

import usb.core

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m
from research import evm_cn_probe as e
from research import phy_tx_probe as p

PHASES = (("cck_before", 0), ("ht8_2ss", 0x488), ("cck_after", 0))


def frame_for(sequence, marker):
    if (
        type(sequence) is not int
        or not 0 <= sequence < 12
        or len(marker) != 14
        or marker[:6] != b"\xdd\x0c\x02NW\x01"
    ):
        raise ValueError("bounded twelve-frame sequence and private nonce IE required")
    return p.c3.controlled_frame(sequence) + marker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit transmit acknowledgment required")
    out = {
        "tool": "evm_cn_stimulus",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": 1,
        "submitted": 0,
        "maximum_submissions": 12,
        "rows": [],
    }
    with contextlib.ExitStack() as stack:
        rx = stack.enter_context(m.open_device("0e8d:7961"))
        tx = stack.enter_context(m.open_device("0846:9072"))
        radios = (rx, tx)
        images = [m.load_firmware(d.CHIP, m.firmware_dir()) for d in radios]
        marker = b"\xdd\x0c\x02NW\x01" + os.urandom(8)

        def boot(i):
            dev = radios[i]
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 1, 1, 20)

        try:
            for i in (0, 1):
                boot(i)
            out["initial"] = e.read(rx)
            for phase, (name, code) in enumerate(PHASES):
                p.program_rate(tx, code)
                row = {
                    "name": name,
                    "rate_code": code,
                    "before": e.read(rx),
                    "receipts": [],
                    "normal_by_phy": {},
                }
                out["rows"].append(row)
                counts = collections.Counter()
                for sequence in range(phase * 4, phase * 4 + 4):
                    frame = frame_for(sequence, marker)
                    body = p.descriptor(tx, frame, sequence, code) + frame
                    wire = struct.pack("<I", len(body)) + body
                    wire += bytes((-len(wire)) % 4 + 4)
                    tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                    out["submitted"] += 1
                    deadline = time.monotonic() + 0.1
                    transfers = 0
                    matched = False
                    while time.monotonic() < deadline and transfers < 128:
                        try:
                            raw = bytes(rx.rx_read(timeout=20))
                        except usb.core.USBTimeoutError:
                            continue
                        transfers += 1
                        decoded = m.decoder_for(rx)(raw)
                        if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
                            counts[str(decoded.get("phy", {}).get("mode"))] += 1
                            if decoded["frame"] == frame and not matched:
                                matched = True
                                row["receipts"].append(
                                    {
                                        "sequence": sequence,
                                        "phy": {
                                            k: decoded["phy"].get(k)
                                            for k in ("mode_name", "mcs", "nss", "bw_mhz")
                                        },
                                        "register_after_receipt": e.read(rx),
                                    }
                                )
                    if transfers == 128:
                        row["transfer_limit_reached"] = True
                    time.sleep(0.05)
                row["normal_by_phy"] = dict(counts)
                row["after"] = e.read(rx)
            out["alive_after"] = [d.alive() for d in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            out["cleanup_reload_alive"] = []
            for i in (0, 1):
                try:
                    boot(i)
                    out["cleanup_reload_alive"].append(radios[i].alive())
                except Exception as exc:
                    out["cleanup_reload_alive"].append(False)
                    out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))

    return int(
        "error_type" in out
        or not all(out.get("alive_after", [False]))
        or not all(out.get("cleanup_reload_alive", [False]))
    )


if __name__ == "__main__":
    raise SystemExit(main())
