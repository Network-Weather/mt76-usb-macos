#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Quiet/TX/quiet histogram events with20 bounded own CCK1 transmissions.

Channel6/20MHz only, synthetic no-ACK frames, independent MT7961 good-FCS
receipt. Firmware-timed histogram resets both indices. MCU-only MIB ownership.
No positive power changes, gain overrides, ambient export or calibration claim.
Both radios reload; four histogram control masks are restored on every exit.
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
from research import data_frame_probe as data
from research import mt7925_mib_characterize as mib
from research import mt7925_noise_event_probe as noise
from research import phy_tx_probe as phy
from research.mt7961_sniffer_trace import RAM_SHA256 as OLD_RAM_SHA256

OFFSETS = (11, 12, 13, 17, 31)
MAX_SUBMISSIONS = 20


def packet(dev, sequence, nonce, padding):
    if dev.CHIP != m.CHIP_MT7925 or type(padding) is not int or padding not in (0, 128):
        raise ValueError("only fixed MT7925 CCK1 short/long packets")
    payload = data.frame("probe", sequence, nonce) + phy.timing_padding(padding)
    words = list(struct.unpack("<16I", phy.descriptor(dev, payload, sequence, 0, fixed_bw=True)))
    words[2] |= 1 << 12  # SW_DURATION preserves explicit Duration0.
    body = struct.pack("<16I", *words) + payload
    wire = struct.pack("<I", len(body)) + body
    wire += bytes((-len(wire)) % 4 + 4)
    return payload, wire


def sample(dev):
    opened = time.monotonic()
    values, midpoint = mib.sample(dev, OFFSETS, 0)
    if any(values.get(offset) is None for offset in OFFSETS):
        raise ValueError("missing source-defined MIB counters")
    return {
        "opened_s": opened,
        "midpoint_s": midpoint,
        "closed_s": time.monotonic(),
        "values": values,
    }


def acquire(tx, rx, packets, transmit):
    if len(packets) != MAX_SUBMISSIONS or type(transmit) is not bool:
        raise ValueError("exactly20 prepared packets and explicit phase required")
    row = {
        "transmit": transmit,
        "submitted": 0,
        "exact_good_sequences": [],
        "tx_status": [],
        "attempted_transfers": 0,
    }
    decoder = m.decoder_for(rx)
    payload_indices = {payload: i for i, (payload, _) in enumerate(packets)}
    good = set()
    started = time.monotonic()
    next_submission = started + 0.03
    sequence = noise.activate(tx)
    row["request_sequence"] = sequence
    while time.monotonic() < started + 3 and row["attempted_transfers"] < 3072:
        now = time.monotonic()
        sent = row["submitted"]
        # Never catch up by bursting late packets; submissions end before400ms.
        if transmit and sent < MAX_SUBMISSIONS and now < started + 0.4 and now >= next_submission:
            tx.bulk_out(tx.ep_out_ac_be, packets[sent][1], 1000)
            row["submitted"] += 1
            next_submission = time.monotonic() + 0.015
        for dev, ep in ((rx, rx.ep_in_pkt_rx), (tx, tx.ep_in_pkt_rx), (tx, tx.ep_in_cmd_resp)):
            row["attempted_transfers"] += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            if dev is rx:
                decoded = decoder(raw)
                if decoded and not decoded.get("fcs_err"):
                    index = payload_indices.get(decoded.get("frame"))
                    if transmit and index is not None and index < row["submitted"]:
                        good.add(index)
                continue
            parsed = noise.event_body(raw)
            if parsed is not None and parsed[:2] == (0x36, 0):
                row["event"] = noise.summarize(raw)
                row["host_event_seconds"] = time.monotonic() - started
                row["exact_good_sequences"] = sorted(good)
                return row
            if parsed is not None and parsed[:2] == (1, sequence) and len(parsed[2]) == 8:
                cid, status = struct.unpack("<II", parsed[2])
                if cid == 0x36:
                    row["command_status"] = status
            if transmit and len(raw) >= 4 and (struct.unpack_from("<I", raw)[0] >> 27) & 31 == 0:
                row["tx_status"].extend(
                    s
                    for s in phy.c3.tx_status(raw)
                    if s["pid"] == 3 and 0 <= s["sequence"] < row["submitted"]
                )
    row["exact_good_sequences"] = sorted(good)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--padding", type=int, choices=(0, 128), default=128)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--activate-noise-histogram", action="store_true")
    parser.add_argument("--acknowledge-consuming-counters", action="store_true")
    args = parser.parse_args()
    if not (
        args.acknowledge_experimental_transmit
        and args.activate_noise_histogram
        and args.acknowledge_consuming_counters
    ):
        parser.error("explicit TX, histogram reset and exclusive MIB acknowledgments required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": 6,
        "width_mhz": 20,
        "rate": "CCK1",
        "frame_bytes_without_fcs": 65 + args.padding,
        "maximum_submissions": MAX_SUBMISSIONS,
        "phases": [],
    }
    original, activated = {}, False
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        noise.check_image(images[1][1])
        if hashlib.sha256(images[0][1]).hexdigest() != OLD_RAM_SHA256:
            raise ValueError("pinned receiver firmware required")
        rx, tx = radios
        out["firmware_sha256"] = [
            [hashlib.sha256(b).hexdigest() for b in image] for image in images
        ]

        def boot(index):
            dev = radios[index]
            dev.bringup(*images[index], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            for index in (0, 1):
                boot(index)
            out["code"] = noise.hist.verify(tx) + noise.dispatch.verify(tx)
            if not all(r["matches"] for r in out["code"]):
                raise ValueError("histogram code mismatch")
            record = noise.read_words(tx, 0x0221C04C, 8)
            if (
                struct.unpack_from("<H", record)[0] != 0x36
                or struct.unpack_from("<I", record, 4)[0] != 0xE0053786
            ):
                raise ValueError("histogram dispatch mismatch")
            for address, mask in noise.MASKS.items():
                word = tx.rr(address)
                noise.masked(address, word, 0)
                original[address] = word & mask
            out["original_masked_bits"] = {hex(a): b for a, b in original.items()}
            if any(original.values()):
                raise ValueError("histogram already active")
            phy.program_rate(tx, 0)
            nonce = os.urandom(8)
            packets = [packet(tx, i, nonce, args.padding) for i in range(MAX_SUBMISSIONS)]
            for transmit in (False, True, False):
                before = sample(tx)
                activated = True
                row = acquire(tx, rx, packets, transmit)
                out["phases"].append(row)
                row["mib_before"] = before
                row["after_controls"] = noise.hist.controls(tx)
                row["after_banks"] = noise.hist.banks(tx, True)
                row["mib_after"] = sample(tx)
                row["mib_delta"] = {
                    key: (row["mib_after"]["values"][key] - before["values"][key])
                    & 0xFFFFFFFFFFFFFFFF
                    for key in OFFSETS
                }
                if "event" not in row or any(row["after_controls"].values()):
                    raise RuntimeError("missing histogram event or controls not stopped")
            out["alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if activated:
                out["restored"] = {}
                for address, bits in original.items():
                    try:
                        noise.restore(tx, address, bits)
                        out["restored"][hex(address)] = True
                    except Exception as exc:
                        out["restored"][hex(address)] = type(exc).__name__
            out["cleanup_reload_alive"] = []
            for index in (0, 1):
                try:
                    boot(index)
                    out["cleanup_reload_alive"].append(radios[index].alive())
                except Exception:
                    out["cleanup_reload_alive"].append(False)
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or not all(out.get("alive_after", [False]))
        or not all(out.get("cleanup_reload_alive", [False]))
        or any(v is not True for v in out.get("restored", {}).values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
