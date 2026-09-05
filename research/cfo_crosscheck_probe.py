#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Receive-only MT7961 firmware frequency-offset provenance cross-check.

Read three fixed, firmware-identified cached vector words; compare with five CE
0xc8 queries in normal, RF RX and stopped modes. No TX or arbitrary memory reads.
Queries can drain counters. Cached words are not fresh or packet-attributed.
Only identified bitfields are exported, never whole vectors or frame contents.
Pinned RAM b94217a9, routine 0x931212, calculation 0x93141c..0x931488.
"""

import contextlib
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m
from research.legacy_rx_stats_probe import query
from research.testmode_receiver_probe import rx_setting

VECTOR_ADDRESSES = (0x02040808, 0x02040858, 0x0204085C)


def decode_cached_fields(word0, word20, word21):
    """Reproduce integer instructions, not an idealized/calibrated Hz conversion."""
    if any(type(w) is not int or not 0 <= w <= 0xFFFFFFFF for w in (word0, word20, word21)):
        raise ValueError("three unsigned 32-bit words required")
    bandwidth = (word0 >> 8) & 7
    raw = (word20 >> 19) | ((word21 & 127) << 13)
    signed = raw - (1 << 20) if raw & (1 << 19) else raw
    factor = ((10_000_000 << (bandwidth + 1)) & 0xFFFFFFFF) >> 20
    result = ((signed * factor) & 0xFFFFFFFF) >> 4
    if signed < 0:
        result |= 0xFFF00000
    return {
        "bandwidth_code": bandwidth,
        "raw_signed20": signed,
        "firmware_integer_factor": factor,
        "firmware_frequency_offset_u32": result,
        "firmware_frequency_offset_s32": result - (1 << 32) if result & (1 << 31) else result,
        # This firmware exports the six bits directly, unlike mt7915's -16.
        "firmware_snr_field": (word20 >> 13) & 63,
    }


def snapshot(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned MT7961 only")
    return decode_cached_fields(*(dev.rr(address) for address in VECTOR_ADDRESSES))


def compare(before, after, stats):
    """Nonzero status or changing cache is not a valid exact-match experiment."""
    words = stats.get("candidate_prefix_words_le", [])
    out = {
        "body_bytes": stats.get("body_bytes"),
        "candidate_status_u32": stats.get("candidate_status_u32"),
        "cached_fields_stable": before == after,
        "cached_measurement_nonzero": bool(before["raw_signed20"] or before["firmware_snr_field"]),
    }
    if len(words) != 66 or stats.get("body_bytes") != 300:
        raise ValueError("expected measured 300-byte statistics layout")
    out["frequency_offset_word19_u32"] = words[19]
    out["snr_word49_u32"] = words[49]
    if out["candidate_status_u32"] == 0 and out["cached_fields_stable"]:
        out["frequency_offset_exact_match"] = words[19] == before["firmware_frequency_offset_u32"]
        out["snr_exact_match"] = words[49] == before["firmware_snr_field"]
    return out


def main():
    out = {
        "tool": "cfo_crosscheck_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": 36,
        "width_mhz": 20,
        "cache_addresses": [hex(a) for a in VECTOR_ADDRESSES],
        "rows": [],
    }
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        def observe(phase, sequence):
            before = snapshot(dev)
            events = query(dev, sequence)
            after = snapshot(dev)
            stats = [e["statistics"] for e in events if "statistics" in e]
            if len(stats) != 1:
                raise RuntimeError("expected one matched statistics reply")
            out["rows"].append(
                {
                    "phase": phase,
                    "before": before,
                    "after": after,
                    "comparison": compare(before, after, stats[0]),
                }
            )

        try:
            boot()
            observe("normal", 1)
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
            observe("rf_rx", 2)
            observe("rf_rx_second", 3)
            dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
            time.sleep(0.2)
            observe("stopped", 4)
            observe("stopped_second", 5)
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
            except Exception as exc:
                out["stop_error_type"] = type(exc).__name__
            finally:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out["cleanup_reload_alive"])


if __name__ == "__main__":
    raise SystemExit(main())
