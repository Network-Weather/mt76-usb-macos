#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Bounded EXT 0xa4 receive-stat query experiment, not an arbitrary command sweep.

Reference-only protocol lead: MediaTek mt_wifi mt_cmd.h, documented in
RELATED_WORK.md. Independently constructed four-byte requests: category, selector,
two reserved bytes. Only receive-stat query categories are allowed. No RF mode
switches, TX commands, calibration writes, or efuse reads. Replies are recorded as
shape/zero counts only, except the already calibrated dispatch refusal signature.
Firmware is reloaded after every request, including timeouts.
"""

import argparse
import datetime
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m
from scripts.mcu_stats import is_refusal


def request(category, selector=0):
    if category not in (0, 3, 4, 5, 6) or selector not in (0, 1):
        raise ValueError("only bounded receive-stat categories/selectors allowed")
    if category in (5, 6) and selector:
        raise ValueError("user/common query uses reserved zero selector")
    return struct.pack("<BB2x", category, selector)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--usb-id", choices=("0e8d:7961", "0846:9072"), required=True)
    args = p.parse_args()
    out = {
        "tool": "rx_stat_query",
        "date": datetime.datetime.now(datetime.UTC).isoformat(),
        "usb_id": args.usb_id,
        "channel": 36,
        "rows": [],
    }
    failed = False
    with m.open_device(args.usb_id) as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        boot()
        for category in (0, 3, 4, 5, 6):
            row = {"category": category, "selector": 0}
            out["rows"].append(row)
            try:
                reply = dev.mcu_cmd_word(
                    m.MCU_EXT_CMD(0xA4) | m.MCU_CMD_FIELD_QUERY, request(category), timeout=1500
                )
                body = dev.reply_body(reply)
                row.update(
                    state="refused" if is_refusal(body, 0xA4) else "answered",
                    reply_bytes=len(body),
                    nonzero_bytes=sum(b != 0 for b in body),
                )
            except (m.McuError, RuntimeError) as exc:
                row.update(state="no_matching_reply", error_type=type(exc).__name__)
            finally:
                boot()
                row["cleanup_alive"] = dev.alive()
            failed |= not row["cleanup_alive"]
    print(json.dumps(out, indent=2))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
