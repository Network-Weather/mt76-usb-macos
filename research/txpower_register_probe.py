#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Compare the pinned MT7925 power report with its traced hardware table.

Three normal tune/report controls; no TX, explicit power or register writes.
Reads only fixed code hashes, two known dispatch records, one flag byte and
the 420-byte hardware table used by the firmware report. No calibration dump.
"""

import datetime
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m
from research.mt7925_csi_input_trace import check_image
from research.txpower_info_probe import EHT_GROUPS, LEGACY_GROUPS, groups, query

WINDOWS = (
    (
        "dispatcher",
        0xE00A1564,
        520,
        "4becaa1d491949848cc52ec673a195246175999621678b1afe9b0550659d9d22",
    ),
    (
        "formatter",
        0xE008F468,
        216,
        "9c8953ac11631832fcffa910d1459cb7a02d3959d9eab0f891451bcc908c7f4a",
    ),
    (
        "hardware_reader",
        0xE00ACEA0,
        136,
        "ca0a38fbb971a56be3857aea3831a586bbbb325b6768d2345703c8c6d04b0a94",
    ),
    (
        "instruction_table",
        0x9171E8,
        4096,
        "d24962d144ffa01a10c0a19b5192e4afa1fccdccc179dfbe126274b2a68cb153",
    ),
)
PLAN = ((6, 6, 20), (6, 8, 40), (36, 36, 20))
TABLE_BASE = 0x820E4140
TABLE_BYTES = 420  # Firmware copies424; final word does not enter this report.
FLAG_ADDRESS = 0x02221C9F  # GP+62623, conditional secondary report-buffer fill.


def read_words(dev, address, size):
    if dev.CHIP != m.CHIP_MT7925 or address % 4 or size % 4:
        raise ValueError("aligned MT7925 reads required")
    raw = bytearray()
    for at in range(address, address + size, 4):
        word = dev.rr(at)
        if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
            raise ValueError("invalid read")
        raw.extend(struct.pack("<I", word))
    return bytes(raw)


def verify(dev):
    rows = []
    for name, address, size, expected in WINDOWS:
        digest = hashlib.sha256(read_words(dev, address, size)).hexdigest()
        rows.append(
            {
                "name": name,
                "address": hex(address),
                "bytes": size,
                "sha256": digest,
                "expected_sha256": expected,
                "matches": digest == expected,
            }
        )
    records = []
    for address, key, target in ((0x0221C024, 0x2B, 0xE00A1564), (0x02219CC4, 7, 0xE00A1760)):
        raw = read_words(dev, address, 8)
        pointer = struct.unpack_from("<I", raw, 4)[0]
        records.append(
            {
                "address": hex(address),
                "key_low_byte": raw[0],
                "handler": hex(pointer),
                "matches": raw[0] == key and pointer == target,
            }
        )
    return rows, records


def unpack_table(raw):
    if len(raw) != TABLE_BYTES:
        raise ValueError("expected420-byte packed power table")
    # Formatter e008f468:28 bytes, one low byte, skip three padding bytes,
    # then97 packed words. Output interleaves the selected firmware-band column.
    selected = raw[:29] + raw[32:420]
    return groups(struct.unpack("<417b", selected), LEGACY_GROUPS + EHT_GROUPS)


def sample(dev, primary, center, width):
    if (primary, center, width) not in PLAN:
        raise ValueError("only the three bounded tune controls")
    dev.tune("2.4GHz" if primary == 6 else "5GHz", primary, center, width)
    time.sleep(0.05)
    flag = read_words(dev, FLAG_ADDRESS & ~3, 4)[FLAG_ADDRESS & 3]
    before = unpack_table(read_words(dev, TABLE_BASE, TABLE_BYTES))
    report = query(dev)
    after = unpack_table(read_words(dev, TABLE_BASE, TABLE_BYTES))
    values = report["selected_band_power_raw"]
    return {
        "primary": primary,
        "center": center,
        "width_mhz": width,
        "conditional_buffer_flag": flag,
        "report": report,
        "hardware_before_matches_report": before == values,
        "hardware_after_matches_report": after == values,
        "hardware_selected_rows_unchanged": before == after,
    }


def main():
    images = m.load_firmware(m.CHIP_MT7925, m.firmware_dir())
    check_image(images[1])
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "firmware_sha256": [hashlib.sha256(b).hexdigest() for b in images],
        "table_address": hex(TABLE_BASE),
        "table_bytes": TABLE_BYTES,
        "maximum_word_reads": 1246 + 3 * 211,
        "samples": [],
    }
    with m.open_device("0846:9072") as dev:

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            boot()
            out["code"], out["dispatch_records"] = verify(dev)
            if not all(r["matches"] for r in out["code"] + out["dispatch_records"]):
                raise ValueError("live firmware trace mismatch")
            for state in PLAN:
                out["samples"].append(sample(dev, *state))
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or not out.get("alive_after")
        or not out.get("cleanup_reload_alive")
        or len(out["samples"]) != 3
        or not all(
            s["hardware_before_matches_report"] and s["hardware_after_matches_report"]
            for s in out["samples"]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
