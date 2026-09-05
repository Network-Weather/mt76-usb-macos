#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Verify pinned ICS code/ROM metadata and read idle controls; never start ICS."""

import datetime
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.txpower_register_probe import check_image, m, read_words

WINDOWS = (
    ("uni49", 0xE00353CC, 368, "ced1a52cf18d311433439a323a0275b5a29d3b972d1a1ad3e38fce4f6be88a2c"),
    (
        "state_machine",
        0xE0073F60,
        584,
        "afa0e98e90fa49f45e2fdd98f6121e4f545890a9bfd1039918b90a657cc58a57",
    ),
    (
        "rom_controls",
        0x836DF4,
        320,
        "08762c5fdac8a909f95a69572ed7f6cbfddeb4f6bf1d362b55d32be73d16c24b",
    ),
    (
        "prerequisite_mapper",
        0x82F880,
        256,
        "6bc71096f1f5bc0342c5bff05f8babf575f55fa7f8feebe71c552e6da9165463",
    ),
    (
        "capture_mapper",
        0x836CDC,
        256,
        "e39a812426dcb3b99e4f39bc554bfb028bb23f865e90248bd37914d71e7542e3",
    ),
    (
        "instruction_table",
        0x9171E8,
        4096,
        "d24962d144ffa01a10c0a19b5192e4afa1fccdccc179dfbe126274b2a68cb153",
    ),
)
METADATA = {
    0x221C07C: 0x49,
    0x221C080: 0xE00353CC,
    0x22113C4: 0x2210504,
    0x2210504: 0x82F882,
    0x84CE80: 0x84D1F4,
    0x84CE84: 0x50000,
    0x84D1F8: 0x1B1B1C1C,
    0x22114F8: 0x22105EC,
    0x22114FC: 0x22105EC,
    0x22105EC: 0x836CDC,
    0x84F0F8: 0x84F178,
    0x84F0FC: 0xD0090,
    0x84F188: 0x08080A0A,
    0x84F18C: 0x01010302,
    0x829670: 0x836DF4,
    0x82969C: 0x836ECE,
    0x8296A0: 0x836EE0,
}
STATE_ADDRESSES = (
    0x81031000,
    0x82023090,
    0x82024090,
    0x820230B4,
    0x2230180,
    0x225F380,
    0x225F384,
    0x223044C,
    0x2230450,
    0x2230454,
)


def verify(dev):
    code = []
    for name, address, size, expected in WINDOWS:
        digest = hashlib.sha256(read_words(dev, address, size)).hexdigest()
        code.append(
            {
                "name": name,
                "address": hex(address),
                "bytes": size,
                "sha256": digest,
                "matches": digest == expected,
            }
        )
    if not all(row["matches"] for row in code):
        raise ValueError("ICS code mismatch")
    metadata = {}
    for address, expected in METADATA.items():
        value = int.from_bytes(read_words(dev, address, 4), "little")
        # Dispatch record key is a u16, with unrelated high padding.
        if address == 0x221C07C:
            value &= 0xFFFF
        if value != expected:
            raise ValueError(f"ICS metadata mismatch at {address:#x}")
        metadata[hex(address)] = hex(value)
    return {"code": code, "metadata": metadata}


def snapshot(dev):
    words = {hex(a): int.from_bytes(read_words(dev, a, 4), "little") for a in STATE_ADDRESSES}
    return {
        "words": {a: hex(v) for a, v in words.items()},
        "prerequisite_bit27": (words["0x81031000"] >> 27) & 1,
        "capture_trigger_bits": [(words[hex(a)] >> 1) & 1 for a in (0x82023090, 0x82024090)],
    }


def main():
    images = m.load_firmware(m.CHIP_MT7925, m.firmware_dir())
    check_image(images[1])
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "firmware_sha256": [hashlib.sha256(b).hexdigest() for b in images],
        "ics_command_sent": False,
    }
    with m.open_device("0846:9072") as dev:
        try:
            dev.bringup(*images, log=lambda *_: None)
            out["verified"] = verify(dev)
            out["normal"] = snapshot(dev)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)
            out["monitor"] = snapshot(dev)
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                dev.bringup(*images, log=lambda *_: None)
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out or not out.get("alive_after") or not out.get("cleanup_reload_alive")
    )


if __name__ == "__main__":
    raise SystemExit(main())
