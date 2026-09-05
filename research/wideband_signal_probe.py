#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Twelve known HT8 frames and read-only GET50-source register observations.

Normal mode only, ch6/20MHz, TX offsets0/negative4-or8/0. The name comes from the pinned
station protocol; upper bytes have firmware-backed signed labels, but units and
per-frame freshness are NOT established. Lower bytes remain uninterpreted.
Reads after receipts are not atomic with those packets. No receiver writes,
RF entry, gain changes, positive power, NVM or ambient identifiers/bytes exported.
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

from research import legacy_ics_probe as legacy
from research import legacy_signal_fields as signal_fields
from research import phy_tx_probe as phy
from research.noise_self_tx_probe import packet
from research.txpower_register_probe import check_image, m

REGISTER = 0x830003E0


def fields(word):
    word = legacy.valid_word(word)
    octets = list(struct.pack("<I", word))
    return {
        "word": hex(word),
        "bytes_low_to_high": octets,
        "signed8_candidates": [x if x < 128 else x - 256 for x in octets],
        "firmware_instantaneous_fields": signal_fields.instantaneous(word),
    }


def sample(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned MT7961 GET50 source only")
    return fields(dev.rr(REGISTER))


def prepared(dev, sequence, nonce, offset):
    if type(offset) is not int or offset not in (0, -4, -8):
        raise ValueError("only zero or negative-four/eight TX offset")
    payload, wire = packet(dev, sequence, nonce, 0)
    raw = bytearray(wire)
    word = struct.unpack_from("<I", raw, 12)[0]
    struct.pack_into("<I", raw, 12, (word & ~(63 << 26)) | ((offset & 63) << 26))
    return payload, bytes(raw)


def acquire(tx, rx, packets):
    if len(packets) != 4:
        raise ValueError("exactly four packets per bounded phase")
    pending = list(packets.items())
    expected = {payload: i for i, (payload, _) in pending}
    submitted, receipts, statuses, polls = [], {}, [], []
    attempts = 0
    decode = m.decoder_for(rx)
    opened = time.monotonic()
    next_tx, next_poll = opened + 0.03, opened
    while time.monotonic() < opened + 0.6 and attempts < 1536:
        now = time.monotonic()
        if now >= next_poll and len(polls) < 12:
            polls.append({"elapsed_s": now - opened, "sample": sample(rx)})
            next_poll = time.monotonic() + 0.05
        if len(submitted) < 4 and now >= next_tx and now < opened + 0.4:
            i, (_, wire) = pending[len(submitted)]
            tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
            submitted.append(i)
            next_tx = time.monotonic() + 0.05
        for dev, ep in ((rx, rx.ep_in_pkt_rx), (tx, tx.ep_in_pkt_rx), (tx, tx.ep_in_cmd_resp)):
            attempts += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            if len(raw) < 4:
                continue
            if dev is tx:
                if struct.unpack_from("<I", raw)[0] >> 27 == 0:
                    statuses.extend(
                        s
                        for s in phy.c3.tx_status(raw)
                        if s["pid"] == 3 and s["sequence"] in submitted
                    )
                continue
            decoded = decode(raw)
            if decoded and not decoded.get("fcs_err"):
                i = expected.get(decoded.get("frame"))
                if i in submitted and i not in receipts:
                    receipts[i] = {
                        "phy": {
                            k: decoded.get("phy", {}).get(k)
                            for k in ("mode_name", "mcs", "nss", "bw_mhz", "gi")
                        },
                        "sample_after_receipt_not_atomic": sample(rx),
                    }
    return {
        "submitted": submitted,
        "good_receipts": receipts,
        "tx_status": statuses,
        "polls": polls,
        "attempts": attempts,
        "after": sample(rx),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--attenuation", type=int, choices=(4, 8), default=8)
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit bounded transmit acknowledgment required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "maximum_submissions": 12,
        "channel": 6,
        "register": hex(REGISTER),
        "phases": [],
    }
    with contextlib.ExitStack() as stack:
        rx, tx = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        radios = (rx, tx)
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        check_image(images[1][1])
        if hashlib.sha256(images[0][1]).hexdigest() != legacy.OLD_RAM_SHA256:
            raise ValueError("pinned receiver firmware required")

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            for i in (0, 1):
                boot(i)
            out["initial"] = sample(rx)
            phy.program_rate(tx, 0x488)
            nonce = os.urandom(8)
            for index, offset in enumerate((0, -args.attenuation, 0)):
                packets = {
                    i: prepared(tx, i, nonce, offset) for i in range(index * 4, index * 4 + 4)
                }
                phase = acquire(tx, rx, packets)
                phase["tx_offset"] = offset
                out["phases"].append(phase)
                if not index and len(phase["good_receipts"]) != 4:
                    raise ValueError("four good normal prerequisites required")
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            out["cleanup_reload_alive"] = []
            for i in (0, 1):
                try:
                    boot(i)
                    out["cleanup_reload_alive"].append(radios[i].alive())
                except Exception:
                    out["cleanup_reload_alive"].append(False)
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not all(out["cleanup_reload_alive"]))


if __name__ == "__main__":
    raise SystemExit(main())
