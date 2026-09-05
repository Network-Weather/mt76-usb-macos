#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Twelve known HT frames across RF-derived RMAC5604 bit0, in normal mode.

One-bit candidate, not an established P-RXV2 enable API. Optional previously
traced RXV START tests the two controls together. No RF entry, arbitrary masks,
raw/ambient vector export, power or nonvolatile changes.
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

from research import legacy_ics_own_probe as own
from research import legacy_ics_probe as legacy
from research import legacy_rxv_control_probe as rxv
from research.noise_self_tx_probe import packet
from research.txpower_register_probe import check_image, m

REGISTER, MASK = 0x820E5604, 1
WINDOWS = (
    (0x8270A8, 208, "2ba8a0f1c78ee4d7e9912b17e81c1b8f2a37994d9c9f2a64c95f334652a3316a"),
    (0x94387C, 32, "1dedab5a413c6278a59e73957d1f271e2638792e2a35908ddd4b46934d6fb6c1"),
)


def verify(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("MT7961 only")
    expected = {0x2014F4C: 0x20138DC, 0x20138DC: 0x8270AA, 0x84ACB4: 0x84B104}
    for address, value in expected.items():
        if legacy.valid_word(dev.rr(address)) != value:
            raise ValueError("pinned RMAC pointer mismatch")
    descriptor = legacy.valid_word(dev.rr(0x84ACB8))
    if descriptor & 0xFFFFFF != (13 << 16) | 0x604:
        raise ValueError("RMAC field descriptor mismatch")
    if legacy.valid_word(dev.rr(0x84B118)) & 65535:
        raise ValueError("key12038a must be bit0")
    hashes = []
    for address, size, expected in WINDOWS:
        raw = b"".join(
            struct.pack("<I", legacy.valid_word(dev.rr(a)))
            for a in range(address, address + size, 4)
        )
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected:
            raise ValueError("pinned RMAC code mismatch")
        hashes.append({"base": hex(address), "bytes": size, "sha256": digest})
    return {"key": "0x12038a", "register": hex(REGISTER), "mask": MASK, "windows": hashes}


def set_field(dev, value):
    if dev.CHIP != m.CHIP_MT7921 or type(value) is not int or value not in (0, 1):
        raise ValueError("only old RMAC bit0 values0/1")
    before = legacy.valid_word(dev.rr(REGISTER))
    dev.wr(REGISTER, (before & ~MASK) | value)
    after = legacy.valid_word(dev.rr(REGISTER))
    if after & MASK != value:
        raise RuntimeError("RMAC bit0 readback failed")
    return {"before": hex(before), "after": hex(after), "field": after & MASK}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-rmac-candidate", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--with-rxv-start", action="store_true")
    args = parser.parse_args()
    if not (args.activate_rmac_candidate and args.acknowledge_experimental_transmit):
        parser.error("explicit one-bit RMAC and transmit acknowledgments required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "max_submissions": 12,
        "channel": 6,
        "with_rxv_start": args.with_rxv_start,
        "phases": [],
    }
    originals, attempted, field_attempted, original_field = {}, False, False, None
    rxv_attempted = False
    with contextlib.ExitStack() as stack:
        rx, tx = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        radios = (rx, tx)
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        check_image(images[1][1])
        if hashlib.sha256(images[0][1]).hexdigest() != legacy.OLD_RAM_SHA256:
            raise ValueError("pinned MT7961 required")

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            for i in (0, 1):
                boot(i)
            out["verified_ics"] = legacy.verify(rx)
            out["verified_candidate"] = verify(rx)
            if args.with_rxv_start:
                out["verified_rxv"] = rxv.verify(rx)
                if rxv.snapshot(rx)["owned_mask"] != "0x1":
                    raise ValueError("exclusive stopped RXV prerequisite")
            original_field = legacy.valid_word(rx.rr(REGISTER)) & MASK
            if original_field != 1:
                raise ValueError("normal bit0=1 prerequisite")
            originals = {a: legacy.valid_word(rx.rr(a)) & mask for a, mask in legacy.MASKS.items()}
            if (
                originals[0x820E50D0]
                or originals[0x820E705C]
                or legacy.valid_word(rx.rr(0x820E4120)) & 1
            ):
                raise ValueError("ICS already enabled")
            own.phy.program_rate(tx, 0x488)
            nonce = os.urandom(8)
            attempted = True
            legacy.send(rx, True)
            time.sleep(0.05)
            for index, value in enumerate((1, 0, 1)):
                rxv_control = None
                if args.with_rxv_start and index:
                    if index == 1:
                        rxv_attempted = True
                        rxv.apply_control(rx, "rx_report_only")
                        rxv_control = rxv.apply_control(rx, "rxv_started")
                    else:
                        rxv.quiesce(rx)
                        rxv_control = rxv.apply_control(rx, "rx_resumed_report_off")
                field_attempted = True
                control = set_field(rx, value)
                time.sleep(0.05)
                packets = {i: packet(tx, i, nonce, 0) for i in range(index * 4, index * 4 + 4)}
                phase = own.acquire(tx, rx, packets)
                phase.update(
                    {
                        "bit0_requested": value,
                        "rxv_control": rxv_control,
                        "control": control,
                        "register_after": hex(legacy.valid_word(rx.rr(REGISTER))),
                        "ics_masks": legacy.masks(rx),
                    }
                )
                out["phases"].append(phase)
                if not index and len(phase["exact_good_phy"]) != 4:
                    raise ValueError("four exact normal prerequisites required")
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if rxv_attempted:
                try:
                    rxv.quiesce(rx)
                    out["rxv_restored"] = (
                        rxv.apply_control(rx, "rx_resumed_report_off")["owned_mask"] == "0x1"
                    )
                except Exception as exc:
                    out["rxv_restore_error_type"] = type(exc).__name__
            if field_attempted:
                try:
                    out["field_restored"] = set_field(rx, original_field)["field"] == original_field
                except Exception as exc:
                    out["field_restore_error_type"] = type(exc).__name__
            if attempted:
                try:
                    legacy.send(rx, False)
                    out["restored"] = legacy.restore(rx, originals)
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
        or not all(out.get("cleanup_reload_alive", [False]))
        or not all(out.get("restored", {}).values())
        or (field_attempted and not out.get("field_restored"))
        or (rxv_attempted and not out.get("rxv_restored"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
