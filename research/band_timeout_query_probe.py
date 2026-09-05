#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read three MT7925 UNI08/tag7 timeout selectors and cross-check exact registers.

Pinned firmware getter e0030f60 -> e0083b72; no SET, TX or MMIO writes.
Selectors0/1 map to TMAC PLCP timeout fields; selector2 meaning remains unnamed.
No timing units, active-ranging capability or calibrated RF claims.
"""

import argparse
import contextlib
import datetime
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m

REGISTERS = (0x820E40C8, 0x820E40CC, 0x820E40D0)


def request(selector):
    if type(selector) is not int or selector not in (0, 1, 2):
        raise ValueError("only three traced timeout selectors")
    return struct.pack("<4xHHB7x", 7, 12, selector)


def summarize(raw, seq, selector):
    request(selector)
    if len(raw) < 44:
        raise ValueError("short Connac3 event")
    size = struct.unpack_from("<H", raw)[0]
    word = struct.unpack_from("<I", raw)[0]
    if (
        not 44 <= size <= len(raw)
        or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT
        or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
        or raw[37] != seq
    ):
        raise ValueError("not a matching bounded MCU event")
    body = raw[44:size]
    out = {"eid": raw[36], "body_bytes": len(body), "sequence_matches": True}
    if len(body) >= 8 and struct.unpack_from("<I", body)[0] == 8:
        return out | {"command_result_status": struct.unpack_from("<I", body, 4)[0]}
    if raw[36] != 0x21 or len(body) != 16:
        return out
    if (
        body[:4] != bytes(4)
        or struct.unpack_from("<HH", body, 4) != (7, 12)
        or body[8:12] != bytes((selector, 0, 0, 0))
    ):
        raise ValueError("unexpected timeout TLV")
    value = struct.unpack_from("<I", body, 12)[0]
    if value > 0xFFFF:
        raise ValueError("timeout getter exceeds traced sixteen-bit field")
    return out | {"recognized_config": True, "selector": selector, "value_u16": value}


def query(dev, selector):
    payload = request(selector)
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(8, True) != 3:
        raise ValueError("MT7925 QUERY_ACK option3 required")
    address = REGISTERS[selector]
    before = dev.rr(address)
    if type(before) is not int or not 0 <= before < 0xFFFFFFFF:
        raise ValueError("invalid timeout register")
    raw = dev.mcu_uni(8, payload, query=True, timeout=1000)
    out = summarize(raw, dev.msg_seq, selector)
    after = dev.rr(address)
    if type(after) is not int or not 0 <= after < 0xFFFFFFFF:
        raise ValueError("invalid timeout register")
    return out | {
        "register": hex(address),
        "before": hex(before),
        "after": hex(after),
        "register_stable": before == after,
        "query_matches_register": out.get("value_u16") == before & 0xFFFF,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, choices=(1, 36), default=36)
    args = parser.parse_args()
    out = {
        "tool": "band_timeout_query_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": args.channel,
        "uni_option": 3,
        "rows": [],
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel == 1 else "5GHz", args.channel, args.channel, 20)

        try:
            boot()
            for selector in (0, 1, 2, 0, 1, 2):
                row = {"requested_selector": selector}
                out["rows"].append(row)
                row.update(query(dev, selector))
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
    return int("error_type" in out or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
