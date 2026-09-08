#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded, redacted retained-state calibration diagnostic, not warm adoption.

Run only after this checkout's ordinary capture has released the device. No
firmware reset/download, RF transmission, efuse programming or raw capture output.
The ALFA action reissues the existing factory-calibration load; A9000 is a sham
reference. Closing USB leaves the tested configuration in place for diagnosis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import usb.core

import mt7921u as m

TARGETS = (("2.4GHz", 1), ("5GHz", 36), ("6GHz", 53))


def emit(event, **fields):
    print(
        json.dumps({"event": event, "utc": datetime.now(timezone.utc).isoformat(), **fields}),
        flush=True,
    )


def receive(dev, seconds):
    decode = m.decoder_for(dev)
    counts = Counter()
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        try:
            raw = dev.rx_read(timeout=100)
        except usb.core.USBTimeoutError:
            counts["timeouts"] += 1
            continue
        counts["transfers"] += 1
        decoded = decode(raw)
        frame = decoded.get("frame") if decoded else None
        if not frame:
            counts["undecoded"] += 1
            continue
        counts["frames"] += 1
        kind = (int.from_bytes(frame[:2], "little") >> 2) & 3
        counts[("management", "control", "data", "other")[kind]] += 1
        if kind == 0 and (frame[0] >> 4) == 8:
            counts["beacons"] += 1
    return {"elapsed_s": round(time.monotonic() - started, 3), "counts": dict(counts)}


def sweep(dev, phase, seconds):
    for band, channel in TARGETS:
        dev.tune(band, channel)
        # Drain a bounded transition interval; old buffered frames are not a
        # claim of reception on the newly requested channel.
        transition = receive(dev, 0.25)
        emit(
            "dwell",
            phase=phase,
            band=band,
            channel=channel,
            width_mhz=20,
            transition=transition,
            **receive(dev, seconds),
        )


def reapply(dev):
    # mt7921/mcu.c:mt7921_mcu_set_eeprom at upstream c5a3bd91. Identical fixed
    # request to dev.set_eeprom(); keep its matched reply for envelope diagnostics.
    request = struct.pack("<BBH", m.EE_MODE_EFUSE, m.EE_FORMAT_WHOLE, 0)
    started = time.monotonic()
    raw = dev.mcu_cmd_word(m.MCU_EXT_CMD(m.MCU_EXT_CMD_EFUSE_BUFFER_MODE), request)
    size = int.from_bytes(raw[:2], "little")
    if not dev.MCU_RXD_LEN <= size <= len(raw):
        raise RuntimeError("invalid calibration reply length")
    body = raw[dev.MCU_RXD_LEN : size]
    emit(
        "calibration_reply",
        elapsed_s=round(time.monotonic() - started, 6),
        request_hex=request.hex(),
        sequence=dev.msg_seq,
        declared_bytes=size,
        body_bytes=len(body),
        body_sha256=hashlib.sha256(body).hexdigest(),
        # Exact observed result bytes only; never dump arbitrary response words.
        # A matched zero result does not establish effective RF calibration.
        matches_zero_result=body == struct.pack("<II", m.MCU_EXT_CMD_EFUSE_BUFFER_MODE, 0),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb-id", required=True, choices=("0e8d:7961", "0846:9072"))
    parser.add_argument("--action", required=True, choices=("efuse", "sham", "monitor"))
    parser.add_argument("--acknowledge-retained-state", action="store_true")
    args = parser.parse_args(argv)
    if not args.acknowledge_retained_state:
        parser.error("requires explicit retained-state diagnostic acknowledgment")
    if args.action != "sham" and args.usb_id != "0e8d:7961":
        parser.error("only the ALFA accepts a non-sham action")
    try:
        with m.open_device(args.usb_id) as dev:
            misc = dev.rr(m.MT_CONN_ON_MISC)
            host = dev.rr(m.MT_WFDMA_HOST_CONFIG)
            mode = dev.rr(m.MT_SWDEF_MODE)
            if misc == 0xFFFFFFFF or (misc & m.MT_TOP_MISC_FW_STATE) != m.MT_TOP_MISC2_FW_N9_RDY:
                raise RuntimeError("requires already-running firmware; no implicit bring-up")
            if host == 0xFFFFFFFF or not host & m.MT_WFDMA_HOST_CONFIG_USB_RXEVT_EP4_EN:
                raise RuntimeError("requires observed EP4 event routing")
            dev.evt_ep4 = True
            emit(
                "ready",
                chip=dev.CHIP,
                action=args.action,
                firmware_state=misc,
                host_config=host,
                # SWDEF_MODE is a pre-download input, not a demonstrated stable
                # post-boot status register. Retain its readback without gating.
                swdef_mode_readback=mode,
                firmware_reloaded=False,
            )
            emit("inherited_rx", **receive(dev, 1))
            sweep(dev, "before", 3)
            if args.action == "efuse":
                reapply(dev)
            elif args.action == "monitor":
                dev.set_monitor_mode()
                dev.set_sniffer(True)
                emit("monitor_reapplied")
            else:
                time.sleep(0.05)
                emit("sham")
            emit(
                "dwell",
                phase="after_without_retune",
                band="6GHz",
                channel=53,
                width_mhz=20,
                **receive(dev, 3),
            )
            sweep(dev, "after", 3)
            emit(
                "finished",
                legacy_command_frame_discards=dev.mcu_wait_dropped_frames,
                stale_events=dev.mcu_wait_stale_events,
                alive=dev.alive(),
            )
        return 0  # Completion, NOT a claim that RF reception recovered.
    except Exception as exc:
        emit("failed", error_type=type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
