#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Test MT7961 histogram initialization's firmware-derived two-byte layout.

rdmSetIpiHist at 0x00961618 consumes payload byte 0 (type) and byte 1
(value), with PHY/band forced to zero. The earlier AP-shaped request placed
value in byte 2. Compare both after fresh boots. Only type-0 initialization,
value 1, followed by three bounded histogram reads; no TX or direct register writes.
Full firmware reload cleanup. Histograms remain raw and uncalibrated.
"""

import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m
from research.firmware_fields import ipi_snapshot
from research.ipi_hist_cmd import ipi_request, parse_histogram
from research.station_testmode_probe import summarize
from research.testmode_receiver_probe import rx_setting
from scripts.mcu_stats import is_refusal


def initialization(compact):
    if type(compact) is not bool:
        raise ValueError("boolean layout choice required")
    # Keep the same 20-byte envelope; isolate just the value's byte position.
    return (b"\x00\x01\x00" if compact else b"\x00\x00\x01") + bytes(17)


def main():
    import struct

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rf-rx", action="store_true")
    p.add_argument("--registers", action="store_true", help="separate ROM-derived register check")
    args = p.parse_args()
    out = {
        "tool": "ipi_compact_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rf_rx": args.rf_rx,
        "register_checks": args.registers,
        "rows": [],
    }
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        for compact in (False, True):
            row = {"compact": compact, "histograms": []}
            out["rows"].append(row)
            try:
                boot()
                if args.rf_rx:
                    dev.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
                    time.sleep(0.2)
                    for selector, value in (
                        (104, 0),
                        (106, 3 << 16),
                        (18, 5180000),
                        (15, 0),
                        (1, 2),
                    ):
                        dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(selector, value), wait=False)
                        time.sleep(0.1)
                if args.registers:
                    row["registers_before"] = ipi_snapshot(dev)
                raw = dev.mcu_cmd_word(m.MCU_EXT_CMD(0xA3), initialization(compact), timeout=1000)
                row["set_reply"] = summarize(dev.reply_body(raw))
                row["set_reply"]["dispatch_refused"] = is_refusal(dev.reply_body(raw), 0xA3)
                if len(dev.reply_body(raw)) == 16:
                    row["set_reply"]["words_u32"] = list(struct.unpack("<4I", dev.reply_body(raw)))
                if args.registers:
                    row["registers_after_set"] = ipi_snapshot(dev)
                for _ in range(3):
                    time.sleep(0.5)
                    raw = dev.mcu_cmd_word(
                        m.MCU_EXT_CMD(0xA3) | m.MCU_CMD_FIELD_QUERY, ipi_request(12), timeout=1000
                    )
                    body = dev.reply_body(raw)
                    row["histograms"].append(
                        {"body_bytes": len(body), "histogram": parse_histogram(body)}
                    )
                    if args.registers:
                        row["histograms"][-1]["registers_after_query"] = ipi_snapshot(dev)
                row["alive_after"] = dev.alive()
            except Exception as exc:
                row["error_type"] = type(exc).__name__
            finally:
                boot()
                row["cleanup_reload_alive"] = dev.alive()
    print(json.dumps(out, indent=2))
    return int(any("error_type" in row or not row["cleanup_reload_alive"] for row in out["rows"]))


if __name__ == "__main__":
    raise SystemExit(main())
