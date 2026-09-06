#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded MT7925 TX MIB count/duration controls with independent MT7961 RX.

Twenty no-ACK synthetic frames at channel6/20 or40MHz. Source/ROM-mapped UNI
queries only; no direct counter reads or enable writes. Short/long payloads or
20/40MHz width reversals. Normal reload of both radios on every exit. Units and
endpoints remain qualified separately; software counters are not RF success.
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
from research import mt7925_mib_characterize as mib
from research import phy_tx_probe as p
from research.data_frame_probe import frame as synthetic_frame

OFFSETS = (22, 23, 24, 25, 28, 31, 85, 86, 87)

PADDING_PLAN = (0, 128, 0, 128, 0)
WIDTH_PLAN = (20, 40, 20, 40, 20)


def frame(sequence, nonce, suite):
    if suite not in ("length", "width"):
        raise ValueError("only bounded length/width suites")
    payload = synthetic_frame("probe", sequence, nonce)
    return payload + p.timing_padding(PADDING_PLAN[sequence // 4] if suite == "length" else 0)


def payload_symbols_us(length):
    """HT8/2SS/20MHz/BCC/GI0 data symbols, excluding all preamble/extension time."""
    if type(length) is not int or length not in (65, 193):
        raise ValueError("only the two controlled payload sizes")
    return 4 * ((16 + 8 * (length + 4) + 6 + 51) // 52)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("length", "width"), default="length")
    parser.add_argument("--acknowledge-consuming-counters", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit or not args.acknowledge_consuming_counters:
        parser.error("explicit TX and exclusive consuming-counter acknowledgments required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transmitter": "mt7925",
        "suite": args.suite,
        "maximum_submissions": 20,
        "submitted": 0,
        "phases": [],
    }
    nonce = os.urandom(8)
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(d.CHIP, m.firmware_dir()) for d in radios]
        tx, rx = radios[1], radios[0]
        out["firmware_sha256"] = {
            d.CHIP: [hashlib.sha256(b).hexdigest() for b in image]
            for d, image in zip(radios, images, strict=True)
        }

        def sample():
            values, at = mib.sample(tx, OFFSETS, 0)
            if any(v is None for v in values.values()):
                raise ValueError("missing source-named TX counter")
            return {"values": values, "host_monotonic_s": at}

        def boot(i, wide=False):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 8 if wide else 6, 40 if wide else 20)

        try:
            for i in (0, 1):
                boot(i, args.suite == "width")
            code = 0x488
            p.program_rate(tx, code)
            decode = m.decoder_for(rx)
            for phase in range(5):
                width = WIDTH_PLAN[phase] if args.suite == "width" else 20
                padding = PADDING_PLAN[phase] if args.suite == "length" else 0
                current = {
                    "rate_code": code,
                    "tx_width_mhz": width,
                    "frame_bytes_without_fcs": 65 + padding,
                    "padding_bytes": padding,
                    "before": sample(),
                    "windows": [],
                }
                out["phases"].append(current)
                for i in range(4):
                    sequence = phase * 4 + i
                    payload = frame(sequence, nonce, args.suite)
                    txd = p.descriptor(tx, payload, sequence, code, fixed_bw=True, width_mhz=width)
                    row = {
                        "sequence": sequence,
                        "exact_good": False,
                        "good_phy": [],
                        "tx_status": [],
                    }
                    current["windows"].append(row)
                    body = txd + payload
                    wire = struct.pack("<I", len(body)) + body
                    wire += bytes((-len(wire)) % 4 + 4)
                    tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                    out["submitted"] += 1
                    deadline, transfers = time.monotonic() + 0.1, 0
                    while time.monotonic() < deadline and transfers < 256:
                        for dev in (rx, tx):
                            try:
                                raw = bytes(dev.rx_read(timeout=1))
                            except usb.core.USBTimeoutError:
                                continue
                            transfers += 1
                            if dev is tx:
                                if (
                                    len(raw) >= 4
                                    and (struct.unpack_from("<I", raw)[0] >> 27) & 31 == 0
                                ):
                                    statuses = p.c3.tx_status(raw, include_timing=True)
                                    row["tx_status"].extend(
                                        s
                                        for s in statuses
                                        if s["sequence"] == sequence and s["pid"] == 3
                                    )
                                continue
                            decoded = decode(raw)
                            if (
                                decoded
                                and decoded.get("frame") == payload
                                and not decoded.get("fcs_err")
                            ):
                                row["exact_good"] = True
                                row["good_phy"].append(
                                    {
                                        k: decoded.get("phy", {}).get(k)
                                        for k in ("mode_name", "mcs", "nss", "bw_mhz")
                                    }
                                )
                    row["transfer_limit_reached"] = transfers >= 256
                    time.sleep(0.05)
                current["after"] = sample()
                current["delta"] = {
                    k: (current["after"]["values"][k] - current["before"]["values"][k])
                    & ((1 << 64) - 1)
                    for k in OFFSETS
                }
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
