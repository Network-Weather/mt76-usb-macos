#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read-clear MAC FCS accumulation with18 bounded MT7925 probes.

No receiver PHY counter-enable or error-filter changes beyond normal boot.
Only the fixed MAC counter is read; samples can consume statistics.
Exclusive ownership and explicit TX opt-in; both radios reload on exit.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import usb.core

import mt7921u as m
from research import phy_tx_probe as p
from research.error_frame_probe import mac_fcs_sample, rfcr_word

PLAN = ((0x488, 4), (0x48F, 2), (0x488, 4), (0x48F, 4), (0x488, 4))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit transmit acknowledgment required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "MAC FCS batch accumulation without PHY counter enable or error-filter changes",
        "channel": 6,
        "submitted": 0,
        "phases": [],
    }
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        rx, tx = radios
        images = [m.load_firmware(d.CHIP, m.firmware_dir()) for d in radios]
        out["firmware_sha256"] = {
            d.CHIP: [hashlib.sha256(b).hexdigest() for b in image]
            for d, image in zip(radios, images, strict=True)
        }
        marker = b"\xdd\x0c\x02NW\x01" + os.urandom(8)

        def boot(i):
            d = radios[i]
            d.bringup(*images[i], log=lambda *_: None)
            d.set_monitor_mode()
            d.set_sniffer(True)
            d.tune("2.4GHz", 6, 6, 20)

        try:
            for i in (0, 1):
                boot(i)
            out["rfcr_before"] = hex(rfcr_word(rx))
            out["phy_counter_control_before"] = hex(rx.rr(0x83082004))
            decode = m.decoder_for(rx)
            sequence = 0
            for rate, count in PLAN:
                p.program_rate(tx, rate)
                row = {
                    "rate_code": rate,
                    "planned": count,
                    "before": mac_fcs_sample(rx),
                    "exact_good_frames": 0,
                    "window_limit_reached": False,
                }
                out["phases"].append(row)
                for _ in range(count):
                    frame = p.c3.controlled_frame(sequence) + marker
                    body = p.descriptor(tx, frame, sequence, rate) + frame
                    wire = struct.pack("<I", len(body)) + body
                    wire += bytes((-len(wire)) % 4 + 4)
                    tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                    out["submitted"] += 1
                    sequence += 1
                    deadline = time.monotonic() + 0.1
                    received, transfers = False, 0
                    while time.monotonic() < deadline and transfers < 128:
                        try:
                            raw = bytes(rx.rx_read(timeout=10))
                        except usb.core.USBTimeoutError:
                            continue
                        transfers += 1
                        decoded = decode(raw)
                        if decoded and not decoded.get("fcs_err") and decoded.get("frame") == frame:
                            received = True
                    row["exact_good_frames"] += int(received)
                    row["window_limit_reached"] |= transfers == 128
                    time.sleep(0.05)
                row["after"] = mac_fcs_sample(rx)
            out["rfcr_after"] = hex(rfcr_word(rx))
            out["phy_counter_control_after"] = hex(rx.rr(0x83082004))
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
