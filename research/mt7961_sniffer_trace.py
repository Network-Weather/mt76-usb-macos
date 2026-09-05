#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Verify pinned sniffer-dispatch pointers and code hashes, without exporting code.

MT7961 only; 70 aligned instruction/data reads after normal boot. No TX, new
commands, direct register writes or ambient capture. Normal reload on exit.
"""

import datetime
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m

RAM_SHA256 = "b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9"
TABLE_ADDRESS = 0x02026478  # file-layout 0x0202602c + startup relocation 0x44c
CODE_ADDRESS = 0x00923C8C
CODE_LENGTH = 272


def expected_code(ram):
    if hashlib.sha256(ram).hexdigest() != RAM_SHA256:
        raise ValueError("only the pinned MT7961 RAM image is supported")
    region = m.parse_ram(ram)["regions"][0]
    if region["addr"] != 0x00915000 or region["feature_set"] & 1:
        raise ValueError("expected plain region0")
    offset = CODE_ADDRESS - region["addr"]
    if offset < 0 or offset + CODE_LENGTH > region["len"]:
        raise ValueError("instruction window outside region0")
    return ram[offset : offset + CODE_LENGTH]


def verify(dev, expected):
    if dev.CHIP != m.CHIP_MT7921 or len(expected) != CODE_LENGTH:
        raise ValueError("MT7961 and exact bounded code window required")
    pair = (dev.rr(TABLE_ADDRESS), dev.rr(TABLE_ADDRESS + 4))
    if pair != (0x24, 0x00923D54):
        raise ValueError("sniffer dispatcher slot differs from pinned trace")
    code = b"".join(
        struct.pack("<I", dev.rr(address))
        for address in range(CODE_ADDRESS, CODE_ADDRESS + CODE_LENGTH, 4)
    )
    return {
        "table_address": hex(TABLE_ADDRESS),
        "cid": pair[0],
        "handler": hex(pair[1]),
        "code_address": hex(CODE_ADDRESS),
        "code_length": CODE_LENGTH,
        "code_sha256": hashlib.sha256(code).hexdigest(),
        "expected_sha256": hashlib.sha256(expected).hexdigest(),
        "code_matches_pinned_image": code == expected,
    }


def main():
    out = {"date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    images = m.load_firmware(m.CHIP_MT7921, m.firmware_dir())
    expected = expected_code(images[1])
    out["firmware_sha256"] = [hashlib.sha256(b).hexdigest() for b in images]
    with m.open_device("0e8d:7961") as dev:

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            boot()
            out["trace"] = verify(dev, expected)
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
        or not out.get("trace", {}).get("code_matches_pinned_image")
        or not out.get("alive_after")
        or not out.get("cleanup_reload_alive")
    )


if __name__ == "__main__":
    raise SystemExit(main())
