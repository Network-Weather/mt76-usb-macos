#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read MT7925 analog-die temperature and raw ADC, without thermal controls.

Pinned UNI35 tag0, band0, actions0/1 only. No protection overrides, TX, direct
register access or undocumented sensor indices. Normal firmware reload on exit.
"""

import argparse
import datetime
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m


def request(action):
    if type(action) is not int or action not in (0, 1):
        raise ValueError("only temperature0 and raw ADC1 queries allowed")
    return struct.pack("<4xHH4B", 0, 8, 0, action, 0, 0)


def summarize(raw, seq, action):
    request(action)
    if len(raw) < 44:
        raise ValueError("short thermal MCU event")
    word = struct.unpack_from("<I", raw)[0]
    size = word & 0xFFFF
    if (
        not 44 <= size <= len(raw)
        or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT
        or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
        or raw[36] != 0x35
        or raw[37] != seq
    ):
        raise ValueError("not a matching thermal MCU event")
    body = raw[44:size]
    if (
        len(body) != 16
        or body[:4] != bytes(4)
        or struct.unpack_from("<HH", body, 4) != (0, 12)
        or body[8:12] != bytes(4)
    ):
        raise ValueError("unexpected thermal sensor response shape")
    value = struct.unpack_from("<I", body, 12)[0]
    result = {"action": action, "band": 0, "event_tag": 0, "sensor_result_raw_u32": value}
    if action == 0:
        result["reported_temperature_c"] = struct.unpack_from("<i", body, 12)[0]
    else:
        result["units"] = "raw ADC code; conversion not calibrated"
    return result


def query(dev, action):
    payload = request(action)
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(0x35, True) != 3:
        raise ValueError("MT7925 with explicit QUERY_ACK option3 required")
    raw = dev.mcu_uni(0x35, payload, query=True, timeout=1000)
    return summarize(raw, dev.msg_seq, action)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "MT7925 analog-die temperature/ADC queries only, no thermal controls or TX",
        "samples": [],
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        out["firmware_sha256"] = [hashlib.sha256(image).hexdigest() for image in images]
        try:
            dev.bringup(*images, log=lambda *_: None)
            for action in (0, 1, 0):
                out["samples"].append(query(dev, action))
                time.sleep(0.1)
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


if __name__ == "__main__":
    main()
