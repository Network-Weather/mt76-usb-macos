#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded negative per-packet MT7925 power offsets with independent signal RX.

Twenty HT8/2SS/20MHz synthetic no-ACK probes on channel6:0/-4/0/-8/0 raw
signed offsets. No positive offsets, power-table/calibration writes or calibrated
power claim. Only source-defined TXD2 bits31:26 change; both radios reload.
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
from research.data_frame_probe import frame
from research.rx_vector_probe import vectors

PLAN = (0, -4, 0, -8, 0)


def descriptor(dev, offset, sequence, nonce):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 power-offset layout only")
    if type(offset) is not int or offset not in (0, -4, -8):
        raise ValueError("only zero and bounded negative offsets")
    payload = frame("probe", sequence, nonce)
    txd = bytearray(p.descriptor(dev, payload, sequence, 0x488, fixed_bw=True))
    word = struct.unpack_from("<I", txd, 8)[0]
    struct.pack_into("<I", txd, 8, (word & ~(63 << 26)) | ((offset & 63) << 26))
    return bytes(txd), payload


def signal(raw, decoded):
    """Only call after exact synthetic payload/FCS matching; no ambient identifiers."""
    groups = vectors(raw, m.CHIP_MT7921)
    g3, g5 = groups.get("g3", ()), groups.get("g5", ())
    word = g5[6] if len(g5) == 18 else g3[1] if len(g3) == 2 else None
    return {
        "rcpi_raw": None if word is None else [(word >> (8 * i)) & 255 for i in range(4)],
        "rcpi_source": "g5_word6" if len(g5) == 18 else "g3_word1" if len(g3) == 2 else None,
        "chain_signal_driver_units": decoded.get("chain_signal"),
        "rssi_driver_units": decoded.get("rssi"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit TX acknowledgment required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transmitter": "mt7925",
        "maximum_submissions": 20,
        "submitted": 0,
        "phases": [],
    }
    nonce = os.urandom(8)
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(d.CHIP, m.firmware_dir()) for d in radios]
        tx_index = 1
        tx, rx = radios[tx_index], radios[1 - tx_index]
        out["firmware_sha256"] = {
            d.CHIP: [hashlib.sha256(b).hexdigest() for b in image]
            for d, image in zip(radios, images, strict=True)
        }

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            for i in (0, 1):
                boot(i)
            code = 0x488
            p.program_rate(tx, code)
            decode = m.decoder_for(rx)
            for phase, offset in enumerate(PLAN):
                current = {"power_offset_raw": offset, "rate_code": code, "windows": []}
                out["phases"].append(current)
                for i in range(4):
                    sequence = phase * 4 + i
                    txd, payload = descriptor(tx, offset, sequence, nonce)
                    row = {
                        "sequence": sequence,
                        "exact_good": False,
                        "good_phy": [],
                        "good_signal": [],
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
                                    statuses = p.c3.tx_status(raw)
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
                                row["good_signal"].append(signal(raw, decoded))
                                row["good_phy"].append(
                                    {
                                        k: decoded.get("phy", {}).get(k)
                                        for k in ("mode_name", "mcs", "nss", "bw_mhz")
                                    }
                                )
                    row["transfer_limit_reached"] = transfers >= 256
                    time.sleep(0.05)
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
