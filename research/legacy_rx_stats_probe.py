#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded MT7961 CE 0xc8 statistics query in normal and live RX-test modes.

Protocol facts: Motorola gen4m 8fddb9d7 wsys_cmd_handler_fw.h,
nic_cmd_event.h, gl_qa_agent.c and nicCmdEventQueryRxStatistics.
Eight-byte request, 72 requested words. The reference expects an eight-byte
header and big-endian words; measured firmware instead fits a twelve-byte
header and little-endian words. Both hypotheses are retained, not conflated.
No TX, IQ, ambient frames, explicit counter reset, or nonvolatile writes.
Queries may themselves drain counters; cumulative semantics are not assumed.
"""

import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.icap_status_probe import event_summary
from research.testmode_receiver_probe import read_stats, rx_setting


def request(sequence):
    if not 1 <= sequence <= 5:
        raise ValueError("only five bounded observation sequences")
    return struct.pack("<II", sequence, 72)


def summarize(body, sequence):
    out = {"body_bytes": len(body)}
    if len(body) < 8:
        return out
    echoed, count = struct.unpack_from("<II", body)
    out.update(echoed_sequence=echoed, reported_count=count)
    # MT7961 hardware returns 300 bytes, four more than the documented array.
    # Retain only the source-defined prefix; do not interpret the extra word.
    if echoed == sequence and count == 72 and len(body) in (296, 300):
        out["uninterpreted_tail_bytes"] = len(body) - (8 + 66 * 4)
        out["prefix_words_be"] = list(struct.unpack_from(">66I", body, 8))
        if len(body) == 300:
            out["candidate_status_u32"] = struct.unpack_from("<I", body, 8)[0]
            out["candidate_prefix_words_le"] = list(struct.unpack_from("<66I", body, 12))
    return out


def query(dev, sequence):
    dev.mcu_cmd_word(m.MCU_CE_CMD(0xC8) | m.MCU_CMD_FIELD_QUERY, request(sequence), wait=False)
    seq = dev.msg_seq
    events = []
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        try:
            raw = bytes(dev.rx_read(timeout=100))
        except usb.core.USBTimeoutError:
            continue
        event = event_summary(raw, seq)
        if event is not None and len(events) < 32:
            if event["sequence_matches"] and event["eid"] == 0x45:
                size = struct.unpack_from("<I", raw)[0] & 65535
                event["statistics"] = summarize(raw[36:size], sequence)
            events.append(event)
    return events


def main():
    out = {
        "tool": "legacy_rx_stats_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": 36,
        "width_mhz": 20,
        "rows": [],
    }
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        for mode in ("normal", "rf_rx"):
            row = {"mode": mode, "observations": []}
            out["rows"].append(row)
            try:
                boot()
                if mode == "rf_rx":
                    dev.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
                    time.sleep(0.2)
                    for selector, value in (
                        (1, 0),
                        (104, 0),
                        (106, 3 << 16),
                        (18, 5180000),
                        (15, 0),
                        (1, 2),
                    ):
                        dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(selector, value), wait=False)
                        time.sleep(0.1)
                    row["scalar_before"] = read_stats(dev)
                for sequence in (1, 2, 3):
                    row["observations"].append(query(dev, sequence))
                if mode == "rf_rx":
                    row["scalar_after"] = read_stats(dev)
                    dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
                    time.sleep(0.2)
                    row["stopped_observations"] = [query(dev, sequence) for sequence in (4, 5)]
                    row["scalar_stopped"] = read_stats(dev)
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
