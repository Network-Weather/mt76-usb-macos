#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read the pinned UNI dispatcher count/table; never invoke discovered handlers.

Fixed code/ITB hashes and at most61 eight-byte records, no TX or experimental
register writes. Exports only identifiers, pointers and hashes; normal reload.
"""

import datetime
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.txpower_register_probe import check_image, m, read_words

COUNT_ADDRESS = 0x0222DE20  # dispatcher GP+112160
TABLE_ADDRESS = 0x0221BF3C  # dispatcher GP+38716
MAX_RECORDS = 61  # hard cap before the next independently referenced RAM object
WINDOWS = (
    (
        "dispatcher",
        0xE002EF70,
        304,
        "d9da311547531deb7a5bbe345bc02f65969f98bd7c65b6c9d365283c434b935a",
    ),
    (
        "instruction_table",
        0x9171E8,
        4096,
        "d24962d144ffa01a10c0a19b5192e4afa1fccdccc179dfbe126274b2a68cb153",
    ),
)


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
    return rows


def table(dev):
    count = struct.unpack("<I", read_words(dev, COUNT_ADDRESS, 4))[0]
    if not 1 <= count <= MAX_RECORDS:
        raise ValueError("dispatcher count outside fixed read bound")
    records = []
    for index in range(count):
        address = TABLE_ADDRESS + 8 * index
        raw = read_words(dev, address, 8)
        records.append(
            {
                "address": hex(address),
                "cid": struct.unpack_from("<H", raw)[0],
                "handler": hex(struct.unpack_from("<I", raw, 4)[0]),
            }
        )
    after = struct.unpack("<I", read_words(dev, COUNT_ADDRESS, 4))[0]
    if after != count:
        raise ValueError("dispatcher count changed during read")
    return {
        "count_address": hex(COUNT_ADDRESS),
        "count": count,
        "records": records,
        "count_stable": True,
    }


def main():
    images = m.load_firmware(m.CHIP_MT7925, m.firmware_dir())
    check_image(images[1])
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "firmware_sha256": [hashlib.sha256(b).hexdigest() for b in images],
    }
    with m.open_device("0846:9072") as dev:

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            boot()
            out["code"] = verify(dev)
            if not all(row["matches"] for row in out["code"]):
                raise ValueError("live dispatcher code mismatch")
            out["table"] = table(dev)
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
        "error_type" in out or not out.get("alive_after") or not out.get("cleanup_reload_alive")
    )


if __name__ == "__main__":
    raise SystemExit(main())
