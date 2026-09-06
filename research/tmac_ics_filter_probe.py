#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Traced TMAC ICS filter: default/selected/default, twelve own frames.

Only the first/highest filter or all five source-mapped filters; no arbitrary bitmask.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import data_frame_probe as data
from research import tmac_ics_probe as t

FILTER_MASK = 0x1F00
FILTER_CODE = (0xE0083BD4, 100, "6768866acff147d2351e9900037f388a98f698fabbd9c82d8aa98bcb1b9ff564")
FIELD_PAIRS = {0x84C814: 0x0A0A0909, 0x84C818: 0x0C0C0B0B}


def request(mask):
    if type(mask) is not int or mask not in (0, 1, 16, 31):
        raise ValueError("only default, first/highest or all five traced categories")
    raw = bytearray(t.request(True))
    raw[9], raw[14] = 2, 5  # Action2, TMAC filter operation5.
    struct.pack_into("<H", raw, 16, mask)
    return bytes(raw)


def send(dev, mask):
    if dev.CHIP != t.m.CHIP_MT7925 or dev.uni_option(0x49, False) != 7:
        raise ValueError("pinned TMAC ICS command required")
    dev.mcu_uni(0x49, request(mask), query=False, wait=False)
    return dev.msg_seq


def restore_filter(dev, bits):
    if dev.CHIP != t.m.CHIP_MT7925 or type(bits) is not int or bits < 0 or bits & ~FILTER_MASK:
        raise ValueError("only five traced TMAC filter bits")
    value = t.valid_word(dev.rr(0x820E4120))
    dev.wr(0x820E4120, value & ~FILTER_MASK | bits)
    return t.valid_word(dev.rr(0x820E4120)) & FILTER_MASK == bits


def mixed_packet(dev, sequence, nonce):
    kind = ("probe", "data", "probe", "qos-data")[sequence % 4]
    txd, payload = data.descriptor(dev, kind, sequence, nonce)
    words = list(struct.unpack("<16I", txd))
    words[2] |= 1 << 12  # Preserve zero Duration with SW_DURATION.
    body = struct.pack("<16I", *words) + payload
    wire = struct.pack("<I", len(body)) + body
    return payload, wire + bytes((-len(wire)) % 4 + 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-tmac-filter", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--filter-mask", type=int, choices=(1, 16, 31), default=1)
    parser.add_argument("--mixed-data", action="store_true")
    args = parser.parse_args()
    if not (args.activate_tmac_filter and args.acknowledge_experimental_transmit):
        parser.error("explicit filter and transmit acknowledgments required")
    if args.mixed_data and args.filter_mask != 16:
        parser.error("mixed-frame control is restricted to the highest traced filter")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "phases": [],
        "filter_request_hex": request(args.filter_mask).hex(),
        "max_submissions": 12,
        "mixed_data": args.mixed_data,
    }
    attempted, originals, original_filter = False, {}, None
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(t.m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        rx, tx = radios
        images = [t.m.load_firmware(dev.CHIP, t.m.firmware_dir()) for dev in radios]
        t.check_image(images[1][1])
        if hashlib.sha256(images[0][1]).hexdigest() != t.OLD_RAM_SHA256:
            raise ValueError("pinned receiver image required")

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            for i in (0, 1):
                boot(i)
            out["verified"] = t.trace.verify(tx)
            address, size, expected = FILTER_CODE
            digest = hashlib.sha256(t.read_words(tx, address, size)).hexdigest()
            if digest != expected:
                raise ValueError("filter code mismatch")
            out["filter_code_sha256"] = digest
            out["field_metadata"] = {}
            for address, expected in (t.TMAC_WORDS | FIELD_PAIRS).items():
                value = t.valid_word(tx.rr(address))
                if value != expected:
                    raise ValueError("filter metadata mismatch")
                out["field_metadata"][hex(address)] = hex(value)
            originals = {a: t.valid_word(tx.rr(a)) & mask for a, mask in t.MASKS.items()}
            original_filter = t.valid_word(tx.rr(0x820E4120)) & FILTER_MASK
            if any(originals.values()) or original_filter or tx.rr(0x820E50D0) & 1:
                raise ValueError("MAC ICS/filter not in default disabled state")
            out["original_filter"] = original_filter
            t.phy.program_rate(tx, 0)
            nonce = os.urandom(8)
            for phase, mask in enumerate((0, args.filter_mask, 0)):
                attempted = True
                sequence = t.send(tx, True) if phase == 0 else send(tx, mask)
                packets = {
                    i: (
                        mixed_packet(tx, i, nonce)
                        if args.mixed_data
                        else t.prepared_packet(tx, i, nonce)
                    )
                    for i in range(phase * 4, phase * 4 + 4)
                }
                row = t.acquire(tx, rx, packets, sequence)
                row["filter_request_mask"] = mask
                row["submitted_frame_types"] = {
                    i: struct.unpack_from("<H", payload)[0] for i, (payload, _) in packets.items()
                }
                row["control_word_after"] = hex(t.valid_word(tx.rr(0x820E4120)))
                row["masks_after"] = t.masks(tx)
                out["phases"].append(row)
            out["alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if attempted:
                try:
                    send(tx, 0)
                    t.send(tx, False)
                    out["filter_restored"] = restore_filter(tx, original_filter)
                    out["restored"] = t.restore(tx, originals)
                except Exception as exc:
                    out["restore_error_type"] = type(exc).__name__
            out["cleanup_reload_alive"] = []
            for i in (0, 1):
                try:
                    boot(i)
                    out["cleanup_reload_alive"].append(radios[i].alive())
                except Exception:
                    out["cleanup_reload_alive"].append(False)
    print(json.dumps(out, indent=2))
    return int(
        any(k.endswith("error_type") for k in out)
        or out.get("filter_restored") is not True
        or not all(out.get("restored", {}).values())
        or not all(out.get("cleanup_reload_alive", [False]))
    )


if __name__ == "__main__":
    raise SystemExit(main())
