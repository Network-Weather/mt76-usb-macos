#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Twenty known HT frames across firmware-derived MT7961 RXV controls.

Normal mode only. One fixed register, RX-only reporting, source quiesce/resume
sequence and full reload. No RF-mode entry, TX reporting or raw vector export.
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
from research.noise_self_tx_probe import packet
from research.txpower_register_probe import check_image, m

REGISTER = 0x820E3014
MASK = 0x195  # Source fields: TX8/RX7/RXV_START4/QUIESCE2/RX_START0.
ROM_BASE, ROM_BYTES = 0x82A320, 480
ROM_SHA256 = "1e4fb6f19419b2281f039ee6e8fdfed49feadbff1bbe1ea3341258b582706bb4"
STAGES = ("normal_ics", "rx_report_only", "rxv_started", "quiesced", "rx_resumed_report_off")


def verify(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("MT7961 only")
    expected = {0x8226A8: 0x82A3F4, 0x2014F04: 0x20138D4, 0x20138D4: 0x82A322, 0x84B944: 0x84BB0C}
    expected[0x822A58] = 0x82A452
    for address, value in expected.items():
        if legacy.valid_word(dev.rr(address)) != value:
            raise ValueError("pinned RXV pointer mismatch")
    offset, count, _ = struct.unpack("<HBB", struct.pack("<I", legacy.valid_word(dev.rr(0x84B948))))
    if (offset, count) != (0x14, 5):
        raise ValueError("RXV descriptor mismatch")
    pairs = b"".join(
        struct.pack("<I", legacy.valid_word(dev.rr(a))) for a in (0x84BB0C, 0x84BB10, 0x84BB14)
    )
    if pairs[:10] != bytes((8, 8, 7, 7, 4, 4, 2, 2, 0, 0)):
        raise ValueError("RXV bit definitions mismatch")
    raw = b"".join(
        struct.pack("<I", legacy.valid_word(dev.rr(a)))
        for a in range(ROM_BASE, ROM_BASE + ROM_BYTES, 4)
    )
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ROM_SHA256:
        raise ValueError("pinned RXV ROM mismatch")
    return {
        "base": hex(ROM_BASE),
        "bytes": ROM_BYTES,
        "sha256": digest,
        "field_bits": [8, 7, 4, 2, 0],
    }


def snapshot(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("MT7961 only")
    word = legacy.valid_word(dev.rr(REGISTER))
    return {"raw": hex(word), "owned_mask": hex(word & MASK)}


def quiesce(dev):
    """ROM82a452: clear RX/RXV start, request bit2, bounded wait for bit2 clear."""
    word = int(snapshot(dev)["raw"], 16)
    if word & 0x100:
        raise ValueError("TX reporting must remain disabled")
    for clear, set_bits in ((1, 0), (0x10, 0), (0, 4)):
        word = int(snapshot(dev)["raw"], 16)
        dev.wr(REGISTER, (word & ~clear) | set_bits)
    for _ in range(1000):
        state = snapshot(dev)
        if not int(state["raw"], 16) & 4:
            return state
        time.sleep(0.001)
    raise RuntimeError("source quiesce did not complete")


def apply_control(dev, stage):
    if dev.CHIP != m.CHIP_MT7921 or stage not in STAGES:
        raise ValueError("fixed old-chip RXV stages only")
    word = int(snapshot(dev)["raw"], 16)
    if word & 0x100:
        raise ValueError("TX reporting must remain disabled")
    if stage == "rx_report_only":
        dev.wr(REGISTER, word | 0x80)
    elif stage in ("rxv_started", "rx_resumed_report_off"):
        # ROM82a3f4 clears key683, then writes1 to682 (RXV start)
        # or684 (ordinary RX start). Argument0 is NOT a disable boolean.
        dev.wr(REGISTER, word & ~4)
        word = int(snapshot(dev)["raw"], 16)
        dev.wr(REGISTER, word | (0x10 if stage == "rxv_started" else 1))
        if stage == "rx_resumed_report_off":
            dev.wr(REGISTER, int(snapshot(dev)["raw"], 16) & ~0x80)
    elif stage == "quiesced":
        return quiesce(dev)
    return snapshot(dev)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-normal-rxv", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    if not (args.activate_normal_rxv and args.acknowledge_experimental_transmit):
        parser.error("explicit normal RXV and transmit acknowledgments required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "max_submissions": 20,
        "channel": 6,
        "phases": [],
    }
    originals, attempted, rxv_attempted = {}, False, False
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
            out["verified_rxv"] = verify(rx)
            out["original_rxv"] = snapshot(rx)
            if int(out["original_rxv"]["owned_mask"], 16) != 1:
                raise ValueError("exclusive stopped RXV state required")
            originals = {a: legacy.valid_word(rx.rr(a)) & mask for a, mask in legacy.MASKS.items()}
            if (
                originals[0x820E50D0]
                or originals[0x820E705C]
                or legacy.valid_word(rx.rr(0x820E4120)) & 1
            ):
                raise ValueError("ICS already active")
            own.phy.program_rate(tx, 0x488)
            nonce = os.urandom(8)
            attempted = True
            legacy.send(rx, True)
            time.sleep(0.05)
            for index, stage in enumerate(STAGES):
                if index:
                    rxv_attempted = True
                control = apply_control(rx, stage)
                time.sleep(0.05)
                packets = {i: packet(tx, i, nonce, 0) for i in range(index * 4, index * 4 + 4)}
                phase = own.acquire(tx, rx, packets)
                phase.update(
                    {
                        "stage": stage,
                        "rxv_after_control": control,
                        "rxv_after_capture": snapshot(rx),
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
                    out["rxv_quiesce"] = quiesce(rx)
                    out["rxv_report_off"] = apply_control(rx, "rx_resumed_report_off")
                    out["rxv_mask_restored"] = (
                        out["rxv_report_off"]["owned_mask"] == out["original_rxv"]["owned_mask"]
                    )
                except Exception as exc:
                    out["rxv_restore_error_type"] = type(exc).__name__
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
                    if not i:
                        out["rxv_after_reload"] = snapshot(rx)
                except Exception:
                    out["cleanup_reload_alive"].append(False)
    print(json.dumps(out, indent=2))
    return int(
        any(k.endswith("error_type") for k in out)
        or not all(out.get("cleanup_reload_alive", [False]))
        or not all(out.get("restored", {}).values())
        or (rxv_attempted and not out.get("rxv_mask_restored"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
