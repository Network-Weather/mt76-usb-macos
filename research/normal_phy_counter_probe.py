#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""MT7961 normal-mode PHY counter off/on/restore control, at most12 no-ACK frames.

No RF-test entry. Firmware 0x968b1e and mt7915_mac_cca_stats_reset agree on
0x83082004 mask0xe00, clear then0xa00. Explicit counter-write and TX opt-ins.
Only those volatile bits change; original masked bits restored before full
normal reload of both radios. This can reset statistics; use exclusive access.
No arbitrary values, power/ADC/calibration changes, NVM, or raw-frame export.
"""

import argparse
import collections
import concurrent.futures
import contextlib
import datetime
import json
import os
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.mt7925_tx_probe import controlled_frame
from research.phy_stats_probe import hardware_snapshot
from research.phy_tx_probe import descriptor, program_rate

CONTROL = 0x83082004
MASK = 0xE00


def control_value(current, enabled):
    if type(current) is not int or not 0 <= current < 0xFFFFFFFF or type(enabled) is not bool:
        raise ValueError("valid mapped control and boolean enable required")
    return (current & ~MASK) | (0xA00 if enabled else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--enable-counters", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit or not args.enable_counters:
        parser.error("explicit TX and volatile counter-write acknowledgments required")
    out = {
        "tool": "normal_phy_counter_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "maximum_submissions": 12,
        "submitted": 0,
        "rows": [],
    }
    marker = b"\xdd\x0c\x02NW\x01" + os.urandom(8)
    frames = {i: controlled_frame(i) + marker for i in range(12)}
    rate = (1 << 10) | (2 << 6) | 8
    original = None
    wrote = False
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(d.CHIP, m.firmware_dir()) for d in radios]
        rx, tx = radios

        def boot(i):
            dev = radios[i]
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        def collect(start, ready):
            decode = m.decoder_for(rx)
            seen = set()
            phy = collections.Counter()
            transfers = 0
            deadline = time.monotonic() + 1
            ready.set()
            while time.monotonic() < deadline and transfers < 512:
                try:
                    raw = bytes(rx.rx_read(timeout=50))
                except usb.core.USBTimeoutError:
                    continue
                transfers += 1
                packet = decode(raw)
                if not packet or packet.get("fcs_err"):
                    continue
                for seq in range(start, start + 4):
                    if packet.get("frame") == frames[seq]:
                        seen.add(seq)
                        p = packet.get("phy", {})
                        phy[tuple(p.get(k) for k in ("mode_name", "mcs", "nss", "bw_mhz"))] += 1
            return {
                "exact_frames": len(seen),
                "transfers": transfers,
                "limit_reached": transfers == 512,
                "phy": [
                    {"mode": k[0], "mcs": k[1], "nss": k[2], "width_mhz": k[3], "count": n}
                    for k, n in phy.items()
                ],
            }

        def burst(start):
            ready = threading.Event()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                job = pool.submit(collect, start, ready)
                if not ready.wait(2):
                    raise RuntimeError("observer not ready")
                for seq in range(start, start + 4):
                    body = descriptor(tx, frames[seq], seq, rate) + frames[seq]
                    wire = struct.pack("<I", len(body)) + body
                    wire += bytes((-len(wire)) % 4 + 4)
                    tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                    out["submitted"] += 1
                    time.sleep(0.05)
                return job.result(timeout=2)

        def restore():
            current = rx.rr(CONTROL)
            control_value(current, False)  # Refuse all-ones/unmapped state.
            rx.wr(CONTROL, (current & ~MASK) | (original & MASK))
            return (rx.rr(CONTROL) & MASK) == (original & MASK)

        try:
            for i in range(2):
                boot(i)
            program_rate(tx, rate)
            original = rx.rr(CONTROL)
            control_value(original, False)
            out["original_counter_bits"] = original & MASK
            for phase, start in (("baseline", 0), ("enabled", 4), ("restored", 8)):
                if phase == "enabled":
                    wrote = True
                    rx.wr(CONTROL, control_value(rx.rr(CONTROL), False))
                    rx.wr(CONTROL, control_value(rx.rr(CONTROL), True))
                    if rx.rr(CONTROL) & MASK != 0xA00:
                        raise RuntimeError("counter enable readback failed")
                elif phase == "restored":
                    if not restore():
                        raise RuntimeError("counter restore failed")
                row = {
                    "phase": phase,
                    "control_bits": rx.rr(CONTROL) & MASK,
                    "before": hardware_snapshot(rx),
                }
                out["rows"].append(row)
                row["receipt"] = burst(start)
                row["after"] = hardware_snapshot(rx)
                if not row["receipt"]["exact_frames"]:
                    raise RuntimeError("no independent frame receipt")
            out["alive_after"] = [d.alive() for d in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if wrote:
                try:
                    out["counter_bits_restored"] = restore()
                except Exception as exc:
                    out["restore_error_type"] = type(exc).__name__
            out["cleanup"] = []
            for i in range(2):
                try:
                    boot(i)
                    out["cleanup"].append({"alive": radios[i].alive()})
                except Exception as exc:
                    out["cleanup"].append({"error_type": type(exc).__name__})
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or (wrote and not out.get("counter_bits_restored"))
        or not all(r.get("alive") for r in out["cleanup"])
    )


if __name__ == "__main__":
    raise SystemExit(main())
