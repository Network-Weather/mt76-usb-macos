#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Compare firmware IPI init with its exact ROM-derived masked control write.

MT7961 only, channel 36/20 MHz, no TX, at most one second of dwell. --direct-init
explicitly enables one volatile read-modify-write to 0x830af04c (mask 0x1ef,
value 0x121), recovered from firmware 0x96bd20 and ROM field table 0x84cac4.
Restore the original word and fully reload firmware, including after failure.
No arbitrary addresses/values, no nonvolatile writes, no calibrated noise claim.
"""

import argparse
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m
from research.firmware_fields import IPI_CONTROL, ipi_snapshot
from research.ipi_compact_probe import initialization
from research.ipi_hist_cmd import ipi_request, parse_histogram
from research.testmode_receiver_probe import rx_setting


def initialized_control(original):
    if type(original) is not int or not 0 <= original <= 0xFFFFFFFF:
        raise ValueError("32-bit original register required")
    return (original & ~0x1EF) | 0x121


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-init", action="store_true")
    parser.add_argument("--rf-rx", action="store_true")
    args = parser.parse_args()
    out = {"tool": "ipi_register_probe", "direct_init": args.direct_init, "rf_rx": args.rf_rx}
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        original = None
        wrote = False

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        try:
            boot()
            if args.rf_rx:
                dev.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
                time.sleep(0.2)
                for selector, value in ((104, 0), (106, 3 << 16), (18, 5180000), (15, 0), (1, 2)):
                    dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(selector, value), wait=False)
                    time.sleep(0.1)
            original = dev.rr(IPI_CONTROL)
            out["before"] = ipi_snapshot(dev)
            raw = dev.mcu_cmd_word(m.MCU_EXT_CMD(0xA3), initialization(True), timeout=1000)
            body = dev.reply_body(raw)
            out["set_reply_words"] = list(struct.unpack(f"<{len(body) // 4}I", body))
            time.sleep(0.1)
            out["after_firmware_init"] = ipi_snapshot(dev)
            if args.direct_init:
                current = dev.rr(IPI_CONTROL)
                if current == 0xFFFFFFFF:
                    raise RuntimeError("all-ones control; refuse write")
                value = initialized_control(current)
                out["write"] = {"register": hex(IPI_CONTROL), "mask": "0x1ef", "value": hex(value)}
                wrote = True
                dev.wr(IPI_CONTROL, value)
                out["after_direct_init"] = ipi_snapshot(dev)
            time.sleep(0.5)
            out["after_dwell"] = ipi_snapshot(dev)
            raw = dev.mcu_cmd_word(
                m.MCU_EXT_CMD(0xA3) | m.MCU_CMD_FIELD_QUERY, ipi_request(12), timeout=1000
            )
            out["histogram"] = parse_histogram(dev.reply_body(raw))
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                if wrote:
                    dev.wr(IPI_CONTROL, original)
                    out["restored_control"] = hex(dev.rr(IPI_CONTROL))
            except Exception as exc:
                out["restore_error_type"] = type(exc).__name__
            finally:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out["cleanup_reload_alive"])


if __name__ == "__main__":
    raise SystemExit(main())
