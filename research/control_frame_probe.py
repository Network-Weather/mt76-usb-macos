#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Twenty bounded legacy-rate probe/RTS/CTS/ACK/probe frames on either dongle.

Synthetic per-packet destinations, software duration0, no ACK requested, no
association or automatic handshake. The other radio verifies exact payloads.
Only source-defined RTS/CTS/ACK receive-filter bits are opened and restored.
Both radios reload normally. No ambient identities or payloads are exported.
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
from research import data_frame_probe as d
from research import phy_tx_probe as p

PLAN = ("probe", "rts", "cts", "ack", "probe")
RATES = {"ofdm6": 0x4B, "cck1": 0}
FILTERS = {0x820E5000: (1 << 14) | (1 << 15), 0x820E5004: 1 << 4}


def frame(kind, sequence, nonce):
    if kind not in PLAN or type(sequence) is not int or not 0 <= sequence < 20:
        raise ValueError("only the bounded probe/RTS/CTS/ACK plan")
    if not isinstance(nonce, bytes) or len(nonce) != 8:
        raise ValueError("fresh eight-byte nonce required")
    if kind == "probe":
        return d.frame(kind, sequence, nonce)
    # Fresh locally administered unicast destination; never a captured peer.
    address = b"\x02" + nonce[:4] + bytes([sequence])
    payload = struct.pack("<HH", {"rts": 0xB4, "cts": 0xC4, "ack": 0xD4}[kind], 0) + address
    return payload + d.SOURCE if kind == "rts" else payload


def descriptor(dev, kind, sequence, nonce, rate):
    if dev.CHIP not in (m.CHIP_MT7921, m.CHIP_MT7925) or rate not in RATES:
        raise ValueError("pinned legacy-rate control experiment only")
    payload = frame(kind, sequence, nonce)
    words = list(
        struct.unpack(
            "<16I",
            p.descriptor(
                dev, frame("probe", sequence, nonce), sequence, RATES[rate], fixed_bw=True
            ),
        )
    )
    words[0] = (words[0] & ~65535) | (len(payload) + 64)
    words[2] |= 1 << 12  # Source SW_DURATION: retain the explicit zero Duration.
    words[5] = (words[5] & ~255) | (16 + sequence)  # Match status by PID, not nonexistent MAC SN.
    if kind != "probe":
        shift = 16 if dev.CHIP == m.CHIP_MT7925 else 11
        words[1] = (words[1] & ~(31 << shift)) | ((len(payload) // 2) << shift)
        words[2] = (words[2] & ~63) | (1 << 4) | {"rts": 11, "cts": 12, "ack": 13}[kind]
        # Control frames have no Sequence Control field; no manual SN insertion.
        words[3] &= ~((1 << 31) | (4095 << 16))
        if dev.CHIP == m.CHIP_MT7925:
            words[3] &= ~(1 << 4)  # Connac3 BCM
        else:
            words[2] &= ~(1 << 10)  # Connac2 multicast is in DW2, not DW3.
            words[8] = (words[8] & ~63) | (words[2] & 63)
    return struct.pack("<16I", *words), payload


def filter_value(address, current, bits):
    if (
        type(address) is not int
        or address not in FILTERS
        or type(current) is not int
        or not 0 <= current < 0xFFFFFFFF
        or type(bits) is not int
        or bits < 0
        or bits & ~FILTERS[address]
    ):
        raise ValueError("only the three source-defined control-filter bits")
    return current & ~FILTERS[address] | bits


def set_filter(dev, address, bits):
    if dev.CHIP not in (m.CHIP_MT7921, m.CHIP_MT7925):
        raise ValueError("pinned receiver filters only")
    dev.wr(address, filter_value(address, dev.rr(address), bits))
    value = dev.rr(address)
    filter_value(address, value, 0)
    if value & FILTERS[address] != bits:
        raise RuntimeError("control filter readback failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", choices=tuple(RATES), default="cck1")
    parser.add_argument("--transmitter", choices=("mt7925", "mt7961"), default="mt7925")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--open-control-filters", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit or not args.open_control_filters:
        parser.error("explicit TX and control-filter acknowledgments required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rate": args.rate,
        "transmitter": args.transmitter,
        "maximum_submissions": 20,
        "submitted": 0,
        "phases": [],
    }
    nonce = os.urandom(8)
    original = {}
    wrote = False
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        tx_index = int(args.transmitter == "mt7925")
        tx, rx = radios[tx_index], radios[1 - tx_index]
        out["firmware_sha256"] = {
            dev.CHIP: [hashlib.sha256(b).hexdigest() for b in image]
            for dev, image in zip(radios, images, strict=True)
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
            for address in FILTERS:
                value = rx.rr(address)
                filter_value(address, value, 0)
                original[address] = value & FILTERS[address]
            out["original_filter_bits"] = {hex(a): v for a, v in original.items()}
            for address in FILTERS:
                wrote = True
                set_filter(rx, address, 0)
            time.sleep(0.05)
            p.program_rate(tx, RATES[args.rate])
            decode = m.decoder_for(rx)
            for phase, kind in enumerate(PLAN):
                row = {"kind": kind, "windows": []}
                out["phases"].append(row)
                for i in range(4):
                    sequence = phase * 4 + i
                    txd, payload = descriptor(tx, kind, sequence, nonce, args.rate)
                    record = {
                        "sequence": sequence,
                        "bytes_without_fcs": len(payload),
                        "exact_good": False,
                        "good_phy": [],
                        "tx_status": [],
                    }
                    row["windows"].append(record)
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
                                    record["tx_status"].extend(
                                        s
                                        for s in (
                                            p.c3.tx_status(raw)
                                            if tx_index
                                            else d.old_tx_status(raw)
                                        )
                                        if s["pid"] == 16 + sequence
                                    )
                                continue
                            decoded = decode(raw)
                            if (
                                decoded
                                and decoded.get("frame") == payload
                                and not decoded.get("fcs_err")
                            ):
                                record["exact_good"] = True
                                record["good_phy"].append(
                                    {
                                        k: decoded.get("phy", {}).get(k)
                                        for k in ("mode_name", "mcs", "nss", "bw_mhz")
                                    }
                                )
                    record["transfer_limit_reached"] = transfers >= 256
                    time.sleep(0.05)
            out["alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if wrote:
                out["restored_filters"] = {}
                for address in FILTERS:
                    try:
                        set_filter(rx, address, original[address])
                        out["restored_filters"][hex(address)] = True
                    except Exception as exc:
                        out["restored_filters"][hex(address)] = type(exc).__name__
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
        or any(v is not True for v in out.get("restored_filters", {}).values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
