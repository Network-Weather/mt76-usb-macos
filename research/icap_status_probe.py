#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""MT7961 ICAP status only after station mode entry; no capture or TX start.

Transport/layout: mt76 c5a3bd91 mt7921/mcu.h and mt7915/testmode.h.
Status protocol: Motorola gen4m 8fddb9d7 include/wlan_oid.h FUNC_IDX and
common/wlan_oid.c wlanoidExtRfTestICapStatus. EXT 0x04 QUERY, action 1,
function 0x0c, zeroed 80-byte union. RF-test=1, ICAP=2, spectrum=4.
Watch sequence-matched and unsolicited firmware events for 1.5 seconds.
Never request IQ data, start capture, set ADC/gain, send tones or transmit.
Reset firmware after each mode attempt; only redacted event metadata is output.
"""

import argparse
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from scripts.mcu_stats import is_refusal


def status_request():
    return struct.pack("<B3xI80x", 1, 12)


def event_summary(raw, seq):
    if len(raw) < 36:
        return None
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if size < 36 or size > len(raw) or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT:
        return None
    if (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU:
        return None
    body = raw[36:size]
    out = {
        "eid": raw[28],
        "ext_eid": raw[32],
        "sequence_matches": raw[29] == seq,
        "unsolicited_sequence": raw[29] == 0,
        "body_bytes": len(body),
    }
    if is_refusal(body, 4):
        out["refused"] = True
    # Measured MT7961 event family: EID 0xed, EXT EID 4, 68-byte body.
    # The scalar remains raw: done=1 without a capture is not valid IQ evidence.
    if (
        raw[28] == 0xED
        and raw[32] == 4
        and len(body) == 68
        and struct.unpack_from("<I", body)[0] == 12
    ):
        out["candidate_capture_done_raw"] = struct.unpack_from("<I", body, 4)[0]
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", type=int, choices=(1, 2, 4), action="append")
    args = p.parse_args()
    modes = args.mode or [1, 2, 4]
    if len(modes) > 3:
        p.error("at most three mode attempts")
    out = {
        "tool": "icap_status_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": [],
    }
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        for mode in modes:
            row = {"mode_requested": mode, "events": []}
            out["rows"].append(row)
            boot()
            try:
                dev.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, mode, 0), wait=False)
                time.sleep(0.2)
                dev.mcu_cmd_word(
                    m.MCU_EXT_CMD(4) | m.MCU_CMD_FIELD_QUERY, status_request(), wait=False
                )
                seq = dev.msg_seq
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    try:
                        raw = bytes(dev.rx_read(timeout=100))
                    except usb.core.USBTimeoutError:
                        continue
                    event = event_summary(raw, seq)
                    if event is not None and len(row["events"]) < 32:
                        row["events"].append(event)
                row["alive_after"] = dev.alive()
            except (m.McuError, RuntimeError, usb.core.USBError) as exc:
                row["error_type"] = type(exc).__name__
            finally:
                boot()
                row["cleanup_reload_alive"] = dev.alive()
    print(json.dumps(out, indent=2))
    return int(any("error_type" in row or not row["cleanup_reload_alive"] for row in out["rows"]))


if __name__ == "__main__":
    raise SystemExit(main())
