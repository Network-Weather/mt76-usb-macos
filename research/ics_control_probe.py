#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""One short PHY ICS control experiment, no TX or raw sample export.

Fixed UNI49 start/stop, band0, no partition writes, timer5000 (or500 for a
bounded750ms observation). Explicit stop,
both trigger clears, fixed PHY-mask restoration and normal reload are required.
This qualifies controls only; it is not a sample acquisition utility.
"""

import argparse
import datetime
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import ics_trace_probe as trace
from research.mt7925_noise_event_probe import event_body
from research.txpower_register_probe import check_image, m

MASKS = {
    0x830A101C: 1 << 31,
    0x830A1004: 0xFF,
    0x830A3008: 0x600000,
    0x830AD448: 0xFFFFFFFF,
    0x830AD44C: 0xFFFFFFFF,
    0x83080004: 1 << 25,
    0x83080008: 1 << 25,
    0x83081800: (1 << 31) | 1,
    0x820E705C: 1 << 24,
    0x88009004: 0xFFFFFFFF,
    0x8800900C: 0xFFFFFFFF,
    0x88009024: 0xFFFFFFFF,
    0x88009028: 0xFFFFFFFF,
}
CONTROL_REGISTERS = tuple(range(0x82023090, 0x820230B8, 4)) + tuple(
    range(0x82024090, 0x820240B8, 4)
)


def request(start, timer_cycle=False):
    if type(start) is not bool:
        raise ValueError("start must be boolean")
    if type(timer_cycle) is not bool:
        raise ValueError("timer cycle must be boolean")
    # Four reserved bytes, tag0/length88, fixed84-byte command structure.
    return struct.pack(
        "<4xHHBBHBBBB7H62x",
        0,
        88,
        0,
        int(start),
        0,
        3,
        0,
        0,
        0,
        3,
        0,
        0,
        0,
        0,
        0,
        500 if timer_cycle else 5000,
    )


def valid_word(value):
    if type(value) is not int or not 0 <= value < 0xFFFFFFFF:
        raise ValueError("invalid hardware readback")
    return value


def snapshot(dev):
    return {hex(a): hex(valid_word(dev.rr(a))) for a in CONTROL_REGISTERS}


def masked_restore(dev, address, bits):
    if dev.CHIP != m.CHIP_MT7925 or address not in MASKS or bits & ~MASKS[address]:
        raise ValueError("only traced ICS masks")
    value = valid_word(dev.rr(address))
    dev.wr(address, value & ~MASKS[address] | bits)
    return valid_word(dev.rr(address)) & MASKS[address] == bits


def stop_triggers(dev):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 only")
    result = {}
    for address in (0x82023090, 0x82024090):
        value = valid_word(dev.rr(address))
        dev.wr(address, value & ~2)
        result[hex(address)] = not (valid_word(dev.rr(address)) & 2)
    return result


def send(dev, start, timer_cycle=False):
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(0x49, False) != 7:
        raise ValueError("pinned UNI49 option7 required")
    dev.mcu_uni(0x49, request(start, timer_cycle), query=False, wait=False)
    return dev.msg_seq


def collect(dev, sequence, timer_cycle=False):
    out = {"acknowledgments": [], "spectrum_event_body_lengths": [], "attempts": 0}
    deadline = time.monotonic() + (0.75 if timer_cycle else 0.1)
    cap = 1024 if timer_cycle else 128
    while time.monotonic() < deadline and out["attempts"] < cap:
        for ep in (dev.ep_in_pkt_rx, dev.ep_in_cmd_resp):
            out["attempts"] += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            parsed = event_body(raw)
            if parsed is None:
                continue
            eid, seq, body = parsed
            if eid == 1 and seq == sequence and len(body) == 8:
                cid, status = struct.unpack("<II", body)
                if cid == 0x49:
                    out["acknowledgments"].append({"cid": cid, "status": status})
            if eid == 0x30:
                out["spectrum_event_body_lengths"].append(len(body))
            # Never retain other event bodies, descriptors or frame payloads.
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-phy-ics", action="store_true")
    parser.add_argument("--poll-one-timer-cycle", action="store_true")
    args = parser.parse_args()
    if not args.activate_phy_ics:
        parser.error("explicit PHY ICS start/stop acknowledgment required")
    images = m.load_firmware(m.CHIP_MT7925, m.firmware_dir())
    check_image(images[1])
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "timer_cycle": args.poll_one_timer_cycle,
        "start_request_hex": request(True, args.poll_one_timer_cycle).hex(),
        "stop_request_hex": request(False, args.poll_one_timer_cycle).hex(),
    }
    attempted, originals = False, {}
    with m.open_device("0846:9072") as dev:
        try:
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)
            out["verified"] = trace.verify(dev)
            idle = trace.snapshot(dev)
            out["idle"] = idle
            if not idle["prerequisite_bit27"] or any(idle["capture_trigger_bits"]):
                raise ValueError("prerequisite closed or capture already active")
            if any(
                int(idle["words"][hex(a)], 16)
                for a in (0x2230180, 0x225F380, 0x225F384, 0x223044C, 0x2230450, 0x2230454)
            ):
                raise ValueError("ICS state not idle")
            originals = {a: valid_word(dev.rr(a)) & mask for a, mask in MASKS.items()}
            out["original_masked_bits"] = {hex(a): hex(v) for a, v in originals.items()}
            if originals[0x88009004]:
                raise ValueError("capture engine already active")
            out["before"] = snapshot(dev)
            attempted = True
            started = time.monotonic()
            sequence = send(dev, True, args.poll_one_timer_cycle)
            out["start_collection"] = collect(dev, sequence, args.poll_one_timer_cycle)
            out["during"] = snapshot(dev)
            out["during_masks"] = {
                hex(a): hex(valid_word(dev.rr(a)) & mask) for a, mask in MASKS.items()
            }
            out["start_to_stop_seconds"] = time.monotonic() - started
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if attempted:
                try:
                    sequence = send(dev, False, args.poll_one_timer_cycle)
                    out["stop_collection"] = collect(dev, sequence)
                    out["after_command_stop"] = snapshot(dev)
                except Exception as exc:
                    out["stop_error_type"] = type(exc).__name__
                try:
                    out["both_triggers_cleared"] = stop_triggers(dev)
                    # Engine enable first, then other traced masks; never re-enable.
                    order = (0x88009004, *(a for a in MASKS if a != 0x88009004))
                    out["restored"] = {hex(a): masked_restore(dev, a, originals[a]) for a in order}
                    out["after_cleanup"] = trace.snapshot(dev)
                except Exception as exc:
                    out["restore_error_type"] = type(exc).__name__
            try:
                out["alive_before_reload"] = dev.alive()
                dev.bringup(*images, log=lambda *_: None)
                out["cleanup_reload_alive"] = dev.alive()
                out["after_reload"] = trace.snapshot(dev)
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        any(k.endswith("error_type") for k in out)
        or not out.get("cleanup_reload_alive")
        or not all(out.get("restored", {}).values())
        or not all(out.get("both_triggers_cleared", {}).values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
