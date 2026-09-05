#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""MT7961 error-delivery gates with28 bounded MT7925 HT probes.

Source-defined sniffer drop_err and MAC RFCR FCS-drop bit are varied separately.
Only anonymous failed-frame PHY metadata is retained; failed payloads, addresses
and nonces are never exported. Failed frames are NOT authenticated own receipts.
Counter bits and FCS-drop bit are restored, then both radios normally reloaded.
No RF-test entry, power changes, calibration or nonvolatile writes.
"""

import argparse
import collections
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
from research.evm_cn_probe import read as read_evm
from research.normal_phy_counter_probe import CONTROL, MASK, control_value
from research.phy_stats_probe import hardware_snapshot

RFCR = 0x820E5000
PHASES = (
    ("ht8_control_before", 0x488, 1, 1),
    ("ht15_default", 0x48F, 1, 1),
    ("ht15_sniffer_only", 0x48F, 0, 1),
    ("ht15_mac_only", 0x48F, 1, 0),
    ("ht15_both", 0x48F, 0, 0),
    ("ht15_restored", 0x48F, 1, 1),
    ("ht8_control_after", 0x488, 1, 1),
)


def rfcr_word(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("error-delivery control is qualified only on MT7961")
    word = dev.rr(RFCR)
    if type(word) is not int or not 0 <= word < 0xFFFFFFFF:
        raise ValueError("invalid RFCR word")
    return word


def configure(dev, sniffer_drop, mac_drop):
    if any(type(v) is not int or v not in (0, 1) for v in (sniffer_drop, mac_drop)):
        raise ValueError("boolean-valued drop controls required")
    before = rfcr_word(dev)
    dev.config_sniffer(6, 6, "2.4GHz", drop_err=sniffer_drop)
    after_sniffer = rfcr_word(dev)
    dev.set_rxfilter(0, m.MT7921_FIF_BIT_SET if mac_drop else m.MT7921_FIF_BIT_CLR, 2)
    time.sleep(0.05)
    after_mac = rfcr_word(dev)
    if bool(after_mac & 2) != bool(mac_drop):
        raise RuntimeError("FCS-drop readback mismatch")
    return {
        "sniffer_drop": sniffer_drop,
        "mac_drop": mac_drop,
        "rfcr_before": hex(before),
        "rfcr_after_sniffer": hex(after_sniffer),
        "rfcr_after_mac": hex(after_mac),
    }


def failed_metadata(decoded):
    """Only an anonymous PHY observation, never an identity or matched payload."""
    if not decoded or not decoded.get("fcs_err") or not decoded.get("frame"):
        return None
    return {
        "phy": {
            k: decoded.get("phy", {}).get(k)
            for k in ("mode_name", "mcs", "nss", "nsts", "bw_mhz", "gi", "ldpc", "rate_mbps")
        },
        "frame_bytes_without_fcs": len(decoded["frame"]),
        "rssi_raw": decoded.get("rssi"),
        "own_frame_identity_verified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--enable-error-capture", action="store_true")
    parser.add_argument("--enable-counters", action="store_true")
    args = parser.parse_args()
    if not all(
        (args.acknowledge_experimental_transmit, args.enable_error_capture, args.enable_counters)
    ):
        parser.error("explicit TX, error-capture and counter-write opt-ins required")
    out = {
        "tool": "error_frame_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": 6,
        "maximum_submissions": 28,
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
        original_counter = original_rfcr = None
        wrote_counter = False

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        def metrics():
            return {"counters": hardware_snapshot(rx), "latched_cn_evm": read_evm(rx)}

        try:
            for i in (0, 1):
                boot(i)
            original_rfcr = rfcr_word(rx)
            original_counter = rx.rr(CONTROL)
            disabled = control_value(original_counter, False)
            out["original_counter_bits"] = original_counter & MASK
            wrote_counter = True
            rx.wr(CONTROL, disabled)
            rx.wr(CONTROL, control_value(rx.rr(CONTROL), True))
            out["enabled_counter_bits"] = rx.rr(CONTROL) & MASK
            if out["enabled_counter_bits"] != 0xA00:
                raise RuntimeError("counter enable readback failed")
            decode = m.decoder_for(rx)
            for phase, (name, code, sniffer_drop, mac_drop) in enumerate(PHASES):
                current = {
                    "name": name,
                    "rate_code": code,
                    "filters": configure(rx, sniffer_drop, mac_drop),
                    "windows": [],
                }
                out["phases"].append(current)
                p.program_rate(tx, code)
                for i in range(4):
                    sequence = phase * 4 + i
                    frame = p.c3.controlled_frame(sequence) + marker
                    row = {"sequence": sequence, "before": metrics()}
                    current["windows"].append(row)
                    body = p.descriptor(tx, frame, sequence, code) + frame
                    wire = struct.pack("<I", len(body)) + body
                    wire += bytes((-len(wire)) % 4 + 4)
                    tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                    out["submitted"] += 1
                    deadline = time.monotonic() + 0.1
                    seen, transfers = False, 0
                    bad, counts = [], collections.Counter()
                    while time.monotonic() < deadline and transfers < 128:
                        try:
                            raw = bytes(rx.rx_read(timeout=10))
                        except usb.core.USBTimeoutError:
                            continue
                        transfers += 1
                        decoded = decode(raw)
                        if decoded and decoded.get("frame"):
                            mode = str(decoded.get("phy", {}).get("mode_name"))
                            counts[(mode, bool(decoded.get("fcs_err")))] += 1
                            meta = failed_metadata(decoded)
                            if meta:
                                bad.append(meta)
                            if decoded["frame"] == frame and not decoded.get("fcs_err"):
                                seen = True
                    row.update(
                        exact_frame_received=seen,
                        after=metrics(),
                        transfer_limit_reached=transfers == 128,
                        anonymous_bad_fcs_metadata=bad,
                        frame_type_counts=[
                            {"mode": k[0], "fcs_error": k[1], "count": v} for k, v in counts.items()
                        ],
                    )
                    time.sleep(0.05)
            out["alive_after"] = [d.alive() for d in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if original_rfcr is not None:
                try:
                    configure(rx, 1, int(bool(original_rfcr & 2)))
                    out["rfcr_fcs_bit_restored"] = (rfcr_word(rx) & 2) == (original_rfcr & 2)
                except Exception as exc:
                    out["rfcr_restore_error_type"] = type(exc).__name__
            if wrote_counter:
                try:
                    current = rx.rr(CONTROL)
                    control_value(current, False)
                    rx.wr(CONTROL, (current & ~MASK) | (original_counter & MASK))
                    out["counter_bits_restored"] = (rx.rr(CONTROL) & MASK) == (
                        original_counter & MASK
                    )
                except Exception as exc:
                    out["counter_restore_error_type"] = type(exc).__name__
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
        or not out.get("rfcr_fcs_bit_restored")
        or not out.get("counter_bits_restored")
        or not all(out.get("alive_after", [False]))
        or not all(out.get("cleanup_reload_alive", [False]))
    )


if __name__ == "__main__":
    raise SystemExit(main())
