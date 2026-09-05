#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Bounded station testmode queries; no TX-start or nonvolatile writes.

Transport: mt76 c5a3bd91 mt7921/mt7925 testmode.c and mcu.h.
Protocol reference (not copied implementation): Motorola's MediaTek gen4m
8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec include/rftest.h and
include/nic_uni_cmd_event.h, nic/nic_uni_cmd_event.c (BSD-2-Clause).
Only allowlisted RX/temperature/version queries. Optional volatile RF-test mode
entry, with a full firmware reset after every query. No carrier/tone/packet start.
Unknown responses are shape-only; recognized scalar replies are safe metadata.
"""

import argparse
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m

QUERIES = {
    0: "version",
    34: "rx_ok",
    35: "rx_error",
    41: "rx_phy_stats",
    43: "temperature",
    46: "rx_rssi",
    50: "wideband_inband_rssi",
}


def at_query(selector):
    if selector not in QUERIES:
        raise ValueError("query selector not allowlisted")
    return struct.pack("<B3xII", 2, selector, 0)


def rx_query(tag):
    if tag not in (8, 9):
        raise ValueError("receive-stat tag not allowlisted")
    return struct.pack("<4xHH4x", tag, 8)


def summarize(body, selector=None):
    out = {"reply_bytes": len(body), "nonzero_bytes": sum(b != 0 for b in body)}
    if selector is not None and 8 <= len(body) <= 16:
        echoed, value = struct.unpack_from("<II", body)
        if echoed == selector:
            out.update(echoed_selector=echoed, value_u32=value)
    elif selector is None and len(body) >= 8:
        cid, status = struct.unpack_from("<II", body)
        if cid == 0x32:
            out.update(command_result_cid=cid, status_u32=status)
            return out
        tag, size = struct.unpack_from("<HH", body, 4)
        out.update(tag=tag, tlv_bytes=size)
        if tag == 7 and size == 524 and len(body) >= 528:
            # Independently decoded prefix of fixed 8-antenna/16-user V2 layout.
            fcs_err, mismatch, fcs_ok = struct.unpack_from("<HHH", body, 8)
            out["band"] = {
                "fcs_error": fcs_err,
                "length_mismatch": mismatch,
                "fcs_ok": fcs_ok,
                "mdrdy": struct.unpack_from("<I", body, 16)[0],
            }
            out["recognized_v2"] = True
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chip", choices=("mt7961", "mt7925"), required=True)
    p.add_argument(
        "--selector", type=int, action="append", help="subset of the chip's query allowlist"
    )
    p.add_argument("--test-mode", action="store_true", help="volatile idle RF-test mode, no TX")
    args = p.parse_args()
    allowed = list(QUERIES) if args.chip == "mt7961" else [8, 9]
    selectors = args.selector if args.selector is not None else allowed
    if not selectors or len(selectors) > len(allowed) or any(s not in allowed for s in selectors):
        p.error("selectors must be a bounded subset of the chip's query allowlist")
    uid = "0e8d:7961" if args.chip == "mt7961" else "0846:9072"
    out = {
        "tool": "station_testmode_probe",
        "chip": args.chip,
        "test_mode": args.test_mode,
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": [],
    }
    with m.open_device(uid) as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        original_option = dev.uni_option
        # Upstream mt7925_mcu_fill_message requires no ACK bit for these queries.
        dev.uni_option = lambda cid, query=False: (
            (2 if query else 6) if cid in (0x32, 0x46) else original_option(cid, query)
        )

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        for selector in selectors:
            row = {"selector": selector}
            out["rows"].append(row)
            boot()
            try:
                if args.test_mode:
                    if args.chip == "mt7961":
                        dev.mcu_cmd_word(
                            m.MCU_CE_CMD(1),
                            struct.pack("<B3xII", 0, 1, 0),
                            wait=False,
                            timeout=1500,
                        )
                    else:
                        payload = struct.pack("<4xHHB3xI80x", 0, 92, 0, 1)
                        dev.mcu_uni(0x46, payload, wait=False, timeout=1500)
                    time.sleep(0.2)
                if args.chip == "mt7961":
                    reply = dev.mcu_cmd_word(m.MCU_CE_CMD(1), at_query(selector), timeout=1500)
                else:
                    reply = dev.mcu_uni(0x32, rx_query(selector), query=True, timeout=1500)
                row.update(
                    state="matched_reply",
                    **summarize(dev.reply_body(reply), selector if args.chip == "mt7961" else None),
                )
            except (m.McuError, RuntimeError) as exc:
                row.update(state="no_matching_reply", error_type=type(exc).__name__)
            finally:
                boot()
                row["cleanup_reload_alive"] = dev.alive()
        dev.uni_option = original_option
    print(json.dumps(out, indent=2))
    return int(not all(row["cleanup_reload_alive"] for row in out["rows"]))


if __name__ == "__main__":
    raise SystemExit(main())
