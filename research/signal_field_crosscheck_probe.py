#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Five receive-only CEc8 signal-formula comparisons, normal/RF RX/stopped.

Only four identified scalar-source words, no raw vectors or ambient bytes.
RF band0/ch6/20MHz RX only; no TX, gain override or signal-register writes.
CEc8 may drain statistics; exclusive ownership required. Always STOP and reload.
"""

import datetime
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import legacy_ics_probe as legacy
from research import legacy_signal_fields as fields
from research.icap_status_probe import event_summary
from research.legacy_ics_rf_probe import frequency_request
from research.legacy_rx_stats_probe import request, summarize
from research.testmode_receiver_probe import rx_setting
from research.txpower_register_probe import m


def snapshot(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned old-chip signal sources only")
    return {
        "fagc": fields.fagc_band0(dev.rr(0x2040824), dev.rr(0x2040828)),
        "bank0": fields.instantaneous(legacy.valid_word(dev.rr(0x830003E0))),
        "bank1": fields.instantaneous(legacy.valid_word(dev.rr(0x830103E0))),
    }


def query(dev, sequence):
    dev.mcu_cmd_word(m.MCU_CE_CMD(0xC8) | m.MCU_CMD_FIELD_QUERY, request(sequence, 0), wait=False)
    expected_seq = dev.msg_seq
    deadline = time.monotonic() + 0.5
    for _ in range(128):
        if time.monotonic() >= deadline:
            break
        try:
            raw = dev.rx_read(timeout=10)
        except m.usb.core.USBError as exc:
            if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                continue
            raise
        if len(raw) < 36:
            continue
        size = struct.unpack_from("<H", raw)[0]
        if size > len(raw) or size < 36:
            continue
        event = event_summary(raw, expected_seq)
        if event is None or event["eid"] != 0x45 or not event["sequence_matches"]:
            continue
        result = summarize(raw[36:size], sequence)
        if (
            result.get("body_bytes") == 300
            and result.get("reported_band_u32") == 0
            and len(result.get("candidate_prefix_words_le", [])) == 66
        ):
            return result["candidate_prefix_words_le"]
    raise RuntimeError("no matched band0 statistics")


def compare(before, after, words):
    if len(words) != 66:
        raise ValueError("exact66-word measured prefix required")
    expected_before = fields.expected_statistics(**before)
    expected_after = fields.expected_statistics(**after)
    rows = []
    for index, value in expected_before.items():
        actual = fields.u32(words[index])
        actual = actual - (1 << 32) if actual & (1 << 31) else actual
        row = {
            "word_index": index,
            "before": value,
            "after": expected_after[index],
            "reported_s32": actual,
            "source_endpoints_equal": value == expected_after[index],
        }
        if row["source_endpoints_equal"]:
            row["exact_match"] = value == actual
        rows.append(row)
    return rows


def main():
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": 6,
        "transmissions": 0,
        "rows": [],
    }
    images = m.load_firmware(m.CHIP_MT7921, m.firmware_dir())
    if hashlib.sha256(images[1]).hexdigest() != legacy.OLD_RAM_SHA256:
        raise ValueError("pinned old firmware required")
    with m.open_device("0e8d:7961") as dev:

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        def observe(stage, sequence):
            before = snapshot(dev)
            words = query(dev, sequence)
            after = snapshot(dev)
            out["rows"].append(
                {
                    "stage": stage,
                    "before": before,
                    "after": after,
                    "comparison": compare(before, after, words),
                }
            )

        rf_attempted = False
        try:
            boot()
            observe("normal", 1)
            rf_attempted = True
            dev.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
            time.sleep(0.2)
            for req in (
                rx_setting(1, 0),
                rx_setting(104, 0),
                rx_setting(106, 3 << 16),
                frequency_request(6),
                rx_setting(15, 0),
                rx_setting(1, 2),
            ):
                dev.mcu_cmd_word(m.MCU_CE_CMD(1), req, wait=False)
                time.sleep(0.1)
            observe("rf_rx", 2)
            time.sleep(0.15)
            observe("rf_rx_repeat", 3)
            dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
            time.sleep(0.1)
            observe("stopped", 4)
            observe("stopped_repeat", 5)
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if rf_attempted:
                try:
                    dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
                except Exception as exc:
                    out["stop_error_type"] = type(exc).__name__
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(any(k.endswith("error_type") for k in out) or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
