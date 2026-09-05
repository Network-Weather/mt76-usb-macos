#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""One bounded MT7961 factory packet burst, independently observed by MT7925.

Explicit TX opt-in. Source-defined four 64-byte no-ACK OFDM6 packets, channel36,
20MHz, power code0, interval2000us. Host sends STOP after60ms regardless of the
firmware count. No continuous-tone/carrier, calibration bypass, or NVM commands.
Version-query barriers drain SET replies before the four-bit sequence wraps.
GET of setting selectors is not treated as working readback (observed zero).
Only aggregate receipt/PHY/counter evidence, never ambient identities/payloads.
Full normal firmware reload on both radios on every exit.
"""

import argparse
import collections
import concurrent.futures
import contextlib
import datetime
import json
import os
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.csi_control_probe import frame_shape
from research.station_testmode_probe import summarize


def settings(source):
    if not isinstance(source, bytes) or len(source) != 6 or source[:3] != b"\x02NW":
        raise ValueError("synthetic locally administered source required")
    return (
        (1, 0),
        (104, 0),
        (18, 5180000),
        (15, 0),
        (71, 0),
        (72, 0),
        (73, 0),
        (113, 3),
        (114, 1),
        (4, 0),
        (3, 4),
        (2, 0),
        (6, 64),
        (11, 1),
        (13, 0),
        (101, 0x0008),
        (102, 0x1230),
        (103, 0x100A5),
        (68, 0xFFFFFFFF),
        (68 | (1 << 18), 0xFFFF),
        (69, int.from_bytes(source[:4], "little")),
        (69 | (1 << 18), int.from_bytes(source[4:], "little")),
        (8, 2000),
        (7, 4),
    )


def collect(dev, source, stop, ready):
    out = collections.Counter()
    shapes = collections.Counter()
    ambient_classes = collections.Counter()
    sequences = set()
    decode = m.decoder_for(dev)
    ready.set()
    deadline = time.monotonic() + 2
    while not stop.is_set() and time.monotonic() < deadline and out["transfers"] < 2048:
        try:
            raw = bytes(dev.rx_read(timeout=50))
        except usb.core.USBTimeoutError:
            continue
        out["transfers"] += 1
        decoded = decode(raw)
        if not decoded:
            continue
        frame = decoded.get("frame", b"")
        shape = frame_shape(decoded)
        if shape is not None:
            ambient_classes[json.dumps(shape, sort_keys=True)] += 1
            if len(frame) >= 40 and frame[:2] == b"\x08\x00" and frame[24:40] == b"\xa5" * 16:
                out["candidate_fixed_payload_frames"] += 1
        if len(frame) < 24 or frame[10:16] != source:
            continue
        out["synthetic_source_frames"] += 1
        if decoded.get("fcs_err"):
            out["synthetic_source_bad_fcs"] += 1
            continue
        if frame[:2] != b"\x08\x00" or frame[4:10] != b"\xff" * 6:
            out["synthetic_source_unexpected_header"] += 1
            continue
        out["matching_good_fcs_frames"] += 1
        sequences.add(int.from_bytes(frame[22:24], "little"))
        shapes[json.dumps(frame_shape(decoded), sort_keys=True)] += 1
    return {
        "counts": dict(out),
        "unique_sequence_controls": len(sequences),
        "matching_phy_classes": [{"shape": json.loads(k), "count": n} for k, n in shapes.items()],
        "all_good_fcs_frame_classes": [
            {"shape": json.loads(k), "count": n} for k, n in ambient_classes.items()
        ],
        "transfer_limit_reached": out["transfers"] == 2048,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit TX acknowledgment required")
    source = b"\x02NW" + os.urandom(3)
    out = {
        "tool": "testmode_tx_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "requested_packet_count": 4,
        "requested_packet_length": 64,
        "power_code": 0,
        "channel": 36,
        "width_mhz": 20,
        "host_stop_target_s": 0.06,
        "setting_selectors": [],
        "cleanup": [],
    }
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(d.CHIP, m.firmware_dir()) for d in radios]
        tx, rx = radios

        def set_value(selector, value):
            tx.mcu_cmd_word(
                m.MCU_CE_CMD(1), struct.pack("<B3xII", 1, selector, value), wait=False, timeout=500
            )

        def query(selector):
            raw = tx.mcu_cmd_word(
                m.MCU_CE_CMD(1), struct.pack("<B3xII", 2, selector, 0), timeout=1000
            )
            result = summarize(tx.reply_body(raw), selector)
            if raw[28] != 9 or "value_u32" not in result:
                raise RuntimeError("missing matched RF-test scalar")
            return result["value_u32"]

        try:
            for dev, fw in zip(radios, images, strict=True):
                with contextlib.redirect_stdout(sys.stderr):
                    dev.bringup(*fw, log=lambda *_: None)
                dev.set_monitor_mode()
                dev.set_sniffer(True)
                dev.tune("5GHz", 36, 36, 20)
            tx.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
            time.sleep(0.2)
            out["version_before"] = query(0)
            for selector, value in settings(source):
                set_value(selector, value)
                time.sleep(0.05)
                if query(0) != out["version_before"]:
                    raise RuntimeError("RF-test version barrier changed")
                out["setting_selectors"].append(selector)
            out["counters_before"] = {str(s): query(s) for s in (32, 33)}
            stop, ready = threading.Event(), threading.Event()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                job = pool.submit(collect, rx, source, stop, ready)
                try:
                    if not ready.wait(2):
                        raise RuntimeError("observer not ready")
                    time.sleep(0.1)
                    start = time.monotonic()
                    try:
                        set_value(1, 1)
                        out["tx_start_submitted"] = True
                        time.sleep(0.06)
                    finally:
                        set_value(1, 0)
                        out["host_start_stop_elapsed_s"] = round(time.monotonic() - start, 4)
                    time.sleep(0.15)
                finally:
                    stop.set()
                    out["observer"] = job.result(timeout=3)
            out["counters_after_stop"] = {str(s): query(s) for s in (32, 33)}
            time.sleep(0.1)
            out["counters_after_stopped_dwell"] = {str(s): query(s) for s in (32, 33)}
            out["alive_after"] = [d.alive() for d in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                set_value(1, 0)
            except Exception as exc:
                out["cleanup_stop_error_type"] = type(exc).__name__
            for dev, fw in zip(radios, images, strict=True):
                with contextlib.redirect_stdout(sys.stderr):
                    dev.bringup(*fw, log=lambda *_: None)
                out["cleanup"].append({"normal_reload_alive": dev.alive()})
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not all(r["normal_reload_alive"] for r in out["cleanup"]))


if __name__ == "__main__":
    raise SystemExit(main())
