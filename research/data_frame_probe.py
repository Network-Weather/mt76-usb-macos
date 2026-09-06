#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Twenty synthetic no-ACK probe/data/QoS frames on channel6/20MHz.

No association, real BSSID, IP traffic, power changes or CSI assumption. Establish
exact independent frame delivery before treating data as a CSI stimulus. Both
radios receive normal firmware reloads on exit. No ambient identifiers exported.
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
from research.dual_radio_probe import SOURCE

PLAN = ("probe", "data", "probe", "qos-data", "probe")
BSSID = bytes.fromhex("02005e105add")


def frame(kind, sequence, nonce):
    if kind not in ("probe", "data", "qos-data"):
        raise ValueError("only synthetic probe/data/QoS data")
    if type(sequence) is not int or not 0 <= sequence < 20:
        raise ValueError("bounded sequence0..19 required")
    if not isinstance(nonce, bytes) or len(nonce) != 8:
        raise ValueError("fresh eight-byte nonce required")
    if kind == "probe":
        return p.c3.controlled_frame(sequence) + b"\xdd\x0c\x02NW\x03" + nonce
    qos = kind == "qos-data"
    header = struct.pack("<HH", 0x88 if qos else 0x08, 0)
    header += b"\xff" * 6 + SOURCE + BSSID + struct.pack("<H", sequence << 4)
    if qos:
        header += struct.pack("<H", 0x20)  # TID0, NoAck, no A-MSDU/mesh control
    # LLC/SNAP with IEEE local experimental EtherType, not IPv4/IPv6/EAPOL.
    return header + b"\xaa\xaa\x03\x00\x00\x00\x88\xb5NW-DATA" + nonce


def descriptor(dev, kind, sequence, nonce):
    payload = frame(kind, sequence, nonce)
    if dev.CHIP not in (m.CHIP_MT7921, m.CHIP_MT7925):
        raise ValueError("only the two pinned chip families")
    code = 0x488 if dev.CHIP == m.CHIP_MT7925 else 0
    template = p.descriptor(dev, frame("probe", sequence, nonce), sequence, code, fixed_bw=True)
    words = list(struct.unpack("<16I", template))
    words[0] = (words[0] & ~65535) | (len(payload) + 64)
    if kind != "probe":
        shift = 16 if dev.CHIP == m.CHIP_MT7925 else 11
        words[1] = (words[1] & ~(31 << shift)) | ((13 if kind == "qos-data" else 12) << shift)
        subtype = 8 if kind == "qos-data" else 0
        words[2] = (words[2] & ~63) | (2 << 4) | subtype
        if dev.CHIP == m.CHIP_MT7921:
            words[8] = (words[8] & ~63) | (2 << 4) | subtype
    return struct.pack("<16I", *words), payload


def old_tx_status(raw):
    """Add source-defined Connac2 TXS1 sequence bits31:20 to existing metadata."""
    rows = p.tx_status_records(raw)
    end = min(len(raw), int.from_bytes(raw[:2], "little"))
    for offset, row in zip(range(8, end - 31, 32), rows, strict=True):
        row["sequence"] = struct.unpack_from("<I", raw, offset + 4)[0] >> 20
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transmitter", choices=("mt7925", "mt7961"), required=True)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit TX acknowledgment required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transmitter": args.transmitter,
        "maximum_submissions": 20,
        "submitted": 0,
        "phases": [],
    }
    nonce = os.urandom(8)
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(d.CHIP, m.firmware_dir()) for d in radios]
        tx_index = int(args.transmitter == "mt7925")
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
            code = 0x488 if tx_index else 0
            p.program_rate(tx, code)
            decode = m.decoder_for(rx)
            for phase, kind in enumerate(PLAN):
                current = {"kind": kind, "rate_code": code, "windows": []}
                out["phases"].append(current)
                for i in range(4):
                    sequence = phase * 4 + i
                    txd, payload = descriptor(tx, kind, sequence, nonce)
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
                                    statuses = (
                                        p.c3.tx_status(raw) if tx_index else old_tx_status(raw)
                                    )
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
