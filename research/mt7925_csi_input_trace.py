#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Verify pinned MT7925 CSI packet-type provenance using fixed code hashes.

1176 aligned reads: nine instruction windows plus the known instruction table.
No receive-buffer inspection, TX, CSI activation or experimental register writes.
Only addresses/hashes/booleans are exported; normal firmware reload on exit.
"""

import datetime
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m

RAM_SHA256 = "23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120"
# Baselines from locally retained loaded code; no vendor instruction bytes embedded.
WINDOWS = (
    (
        "input_metadata",
        0xE0060D00,
        96,
        "2e09895b3f90ecf125750055f1d9b0759dc3058183165051e5642012fbe84e9d",
    ),
    (
        "eligibility",
        0xE0060C8C,
        128,
        "9cc36b006cf15b8c5198be1d8c45bfc1607f6515d23230da6118728111492b4f",
    ),
    (
        "csi_entry",
        0xE0061390,
        64,
        "961bb5be6343fd7ad509645cf76acf65ed92bc3d321c7fba71ac069b38134532",
    ),
    (
        "csi_wrapper",
        0xE0086154,
        44,
        "7fb218f2e4f7374a5a2952f494438df5ad914374b67dc63216850af754bc0d6a",
    ),
    (
        "rfb_classifier",
        0xE0086284,
        48,
        "fe48b2015c71a8a6d40183ae59f8de9e06adb6e9e1b53d638cfb10780e315c19",
    ),
    (
        "kind_wrapper",
        0xE0079F48,
        60,
        "78174ce65de5fe0986d7eb573176192c74bae29b9a8cc446d43f551ae8735ace",
    ),
    (
        "kind_extract",
        0xE008187C,
        84,
        "b338a592e4d59d33d2159424e2b4019ae5ebeb4056b8c795d158a0e954223e3c",
    ),
    (
        "rx_dispatch_entry",
        0xE0098AC4,
        40,
        "0d24b302b94ac33ac56e0d1e5b56581a8dc43eb1b139d3f600b7a29e93815943",
    ),
    (
        "rx_dispatch_tmr",
        0xE0098C4C,
        44,
        "a169aeff9b5e0c4956af2b39c1d0b75eaba92c209b28bf24a3c0922d29d8e19a",
    ),
    (
        "instruction_table",
        0x9171E8,
        4096,
        "d24962d144ffa01a10c0a19b5192e4afa1fccdccc179dfbe126274b2a68cb153",
    ),
)


def check_image(ram):
    if hashlib.sha256(ram).hexdigest() != RAM_SHA256:
        raise ValueError("only the pinned MT7925 firmware is supported")


def verify(dev):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 CSI code layout only")
    rows = []
    for name, address, size, expected in WINDOWS:
        raw = bytearray()
        for at in range(address, address + size, 4):
            word = dev.rr(at)
            if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
                raise ValueError("invalid instruction read")
            raw.extend(struct.pack("<I", word))
        digest = hashlib.sha256(raw).hexdigest()
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


def main():
    images = m.load_firmware(m.CHIP_MT7925, m.firmware_dir())
    check_image(images[1])
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "firmware_sha256": [hashlib.sha256(b).hexdigest() for b in images],
        "maximum_word_reads": sum(w[2] // 4 for w in WINDOWS),
        "trace": [],
    }
    with m.open_device("0846:9072") as dev:

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            boot()
            out["trace"] = verify(dev)
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
        or len(out["trace"]) != len(WINDOWS)
        or not all(row["matches"] for row in out["trace"])
        or not out.get("alive_after")
        or not out.get("cleanup_reload_alive")
    )


if __name__ == "__main__":
    raise SystemExit(main())
