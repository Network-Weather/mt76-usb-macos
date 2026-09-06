#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read MT7925 band0 EDCCA configuration with explicit UNI query framing.

UNI08 tags5/6 from pinned gen4m BAND_CONFIG. No threshold/enable SET, TX,
RF-test entry, direct register writes, or raw reply export. Normal reload on exit.
Returned signed bytes are configuration values, not calibrated RF measurements.
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

THRESHOLD_REGISTERS = (0x83088554, 0x83088608)


def hardware_thresholds(dev):
    """Exact band0 reads from e0057c52 QUERY branch; no cross-chip inference."""
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 threshold map required")
    words = [dev.rr(address) for address in THRESHOLD_REGISTERS]
    if any(type(word) is not int or not 0 <= word < 0xFFFFFFFF for word in words):
        raise ValueError("invalid threshold register read")
    fields = [(words[0] >> shift) & 255 for shift in (0, 8, 16)] + [words[1] & 255]
    return {
        "registers": {hex(a): hex(w) for a, w in zip(THRESHOLD_REGISTERS, words, strict=True)},
        "field_bytes": fields,
        "field_signed": [value - 256 if value >= 128 else value for value in fields],
        "fourth_field_not_in_uni_reply": True,
    }


def request(tag):
    if type(tag) is not int or tag not in (5, 6):
        raise ValueError("only EDCCA enable/threshold queries")
    return struct.pack("<4xHH4x", tag, 8)


def summarize(raw, seq, tag):
    request(tag)
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
    # Observed response tags are renumbered: request5->event0, request6->event1.
    if (
        raw[36] == 0x21
        and len(body) == 12
        and body[:4] == bytes(4)
        and struct.unpack_from("<HH", body, 4) == (tag - 5, 8)
    ):
        out["recognized_config"] = True
        out["event_tag"] = tag - 5
        if tag == 5:
            if body[9:12] != bytes(3) or body[8] not in (0, 1):
                raise ValueError("invalid EDCCA enable field")
            out["enable_raw"] = body[8]
            # e0057c4e returns zero without filling the getter's zeroed buffer.
            out["enable_hardware_verified"] = False
            out["enable_provenance"] = "pinned_firmware_stub_synthesizes_one"
        else:
            out["threshold_bytes"] = list(body[8:11])
            out["threshold_signed"] = list(struct.unpack_from("<3b", body, 8))
            out["auxiliary_byte"] = body[11]
    return out


def query(dev, tag):
    # Base MT7961 helper ignores query=True; do not reuse it silently.
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(8, True) != 3:
        raise ValueError("MT7925 with explicit QUERY_ACK option3 required")
    raw = dev.mcu_uni(8, request(tag), query=True, timeout=1000)
    return summarize(raw, dev.msg_seq, tag)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, choices=(1, 6, 11, 36, 149), default=36)
    parser.add_argument("--width", type=int, choices=(20, 80, 160), default=20)
    parser.add_argument(
        "--registers", action="store_true", help="cross-check two traced PHY registers"
    )
    args = parser.parse_args()
    band = "2.4GHz" if args.channel <= 11 else "5GHz"
    center = m.center_channel(band, args.channel, args.width)
    if center is None:
        parser.error("unsupported receive geometry")
    out = {
        "tool": "edcca_query_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": args.channel,
        "width_mhz": args.width,
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
            dev.tune(band, args.channel, center, args.width)

        try:
            boot()
            if args.registers:
                out["hardware_before"] = hardware_thresholds(dev)
            for tag in (5, 6, 5, 6):
                row = {"request_tag": tag}
                out["rows"].append(row)
                row.update(query(dev, tag))
            if args.registers:
                out["hardware_after"] = hardware_thresholds(dev)
                out["hardware_stable"] = out["hardware_before"] == out["hardware_after"]
                out["query_triplets_match_hardware"] = all(
                    row.get("threshold_bytes") == out["hardware_before"]["field_bytes"][:3]
                    for row in out["rows"]
                    if row["request_tag"] == 6
                )
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
