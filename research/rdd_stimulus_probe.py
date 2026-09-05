#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Twelve ordinary HT2SS probes around MT7961 RDD off/on/off, no radar emulation.

MT7925 transmits four synthetic no-ACK Probe Requests per phase,20MHz/ch1 or36.
Exact-frame/FCS receipt and fixed detector/producer reads are independent evidence.
No raw pulse-buffer reads, threshold/power changes or direct receiver writes.
Both radios reload in finally; this is not a detector sensitivity calibration.
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
from research import legacy_rdd_state_probe as r
from research import phy_tx_probe as p
from research.evm_cn_stimulus_probe import frame_for
from research.rdd_stop_probe import summarize

RATE_CODE = 0x488


def send_and_receive(tx, rx, sequence, marker):
    frame = frame_for(sequence, marker)
    if tx.CHIP != m.CHIP_MT7925 or rx.CHIP != m.CHIP_MT7921:
        raise ValueError("MT7925 transmitter and MT7961 receiver required")
    body = p.descriptor(tx, frame, sequence, RATE_CODE) + frame
    wire = struct.pack("<I", len(body)) + body
    wire += bytes((-len(wire)) % 4 + 4)
    tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
    deadline = time.monotonic() + 0.15
    transfers = 0
    matched = None
    counts = collections.Counter()
    events = []
    while time.monotonic() < deadline and transfers < 128:
        try:
            raw = bytes(rx.rx_read(timeout=20))
        except usb.core.USBTimeoutError:
            continue
        transfers += 1
        decoded = m.decoder_for(rx)(raw)
        if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
            counts[str(decoded.get("phy", {}).get("mode"))] += 1
            if decoded["frame"] == frame and matched is None:
                matched = {
                    key: decoded["phy"].get(key) for key in ("mode_name", "mcs", "nss", "bw_mhz")
                }
        event = summarize(raw, rx.CHIP, rx.msg_seq)
        if event and event.get("candidate_rdd_event"):
            events.append(event)
    hardware = r.rdd_snapshot(rx)
    time.sleep(0.05)
    return {
        "sequence": sequence,
        "exact_good_fcs_phy": matched,
        "normal_by_phy": dict(counts),
        "rdd_events": events,
        "transfer_limit_reached": transfers == 128,
        "hardware_after": hardware,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--channel", type=int, choices=(1, 36), default=36)
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit bounded TX and receiver-detector opt-in required")
    out = {
        "tool": "rdd_stimulus_probe",
        "channel": args.channel,
        "rate_code": RATE_CODE,
        "maximum_submissions": 12,
        "submitted": 0,
        "rows": [],
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with contextlib.ExitStack() as stack:
        rx = stack.enter_context(m.open_device("0e8d:7961"))
        tx = stack.enter_context(m.open_device("0846:9072"))
        radios = (rx, tx)
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        marker = b"\xdd\x0c\x02NW\x01" + os.urandom(8)

        def boot(index):
            dev = radios[index]
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images[index], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel == 1 else "5GHz", args.channel, args.channel, 20)

        try:
            for index in (0, 1):
                boot(index)
            p.program_rate(tx, RATE_CODE)
            for phase, enabled in enumerate((False, True, False)):
                row = {
                    "requested_enabled": enabled,
                    "control": r.control(rx, enabled, True),
                    "packets": [],
                }
                out["rows"].append(row)
                if row["control"]["hardware_after"]["detector_mode_bits8_6"] != (
                    5 if enabled else 0
                ):
                    raise RuntimeError("detector-mode readback failed")
                for sequence in range(phase * 4, phase * 4 + 4):
                    packet = send_and_receive(tx, rx, sequence, marker)
                    out["submitted"] += 1
                    row["packets"].append(packet)
            out["alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                out["cleanup_stop"] = r.control(rx, False, True)
            except Exception as exc:
                out["stop_error_type"] = type(exc).__name__
            out["cleanup_reload_alive"] = []
            for index in (0, 1):
                try:
                    boot(index)
                    out["cleanup_reload_alive"].append(radios[index].alive())
                except Exception as exc:
                    out["cleanup_reload_alive"].append(False)
                    out["cleanup_error_type"] = type(exc).__name__
            if out["cleanup_reload_alive"][0]:
                out["cleanup_rx_hardware"] = r.rdd_snapshot(rx)
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or not all(out.get("alive_after", [False]))
        or not all(out.get("cleanup_reload_alive", [False]))
        or out.get("cleanup_rx_hardware", {}).get("detector_mode_bits8_6") != 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
