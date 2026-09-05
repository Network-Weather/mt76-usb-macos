#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded receive-only UNI23 queries; repeated diagnostics can stall the MCU.

Pinned MT7925 normal monitor mode, channel6 ->11 ->6. No TX, association,
hardware MIB reads, guessed tags, PHY enable or counter reset. Command ownership
must be exclusive. Only whitelisted scalar counters/configuration are exported;
no peer records, buffer pointers, firmware bytes or ambient identifiers.
Default is three diagnostics then an unrelated thermal control. Four or more
diagnostics require explicit --allow-command-stall; normal reload is mandatory.
"""

import argparse
import datetime
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import mt7925_thermal_probe as thermal
from research import rmac_ics_probe as mac
from research.txpower_register_probe import check_image, m

TAG_HANDLERS = {
    0: 0xE00535F0,
    1: 0xE0053538,
    8: 0xE0053578,
    2: 0xE0053C6E,
    3: 0xE00535F4,
    6: 0xE0054090,
}
# TLV-relative destinations and exact RAM-cache offsets from e003bb84..bbb0.
CACHE_FIELDS = {
    "rx_mdrdy": (0x8C, 0x34),
    "rx_fcs_error": (0x90, 0x08),
    "rx_fifo_full": (0x94, 0x0C),
    "rx_mpdu": (0x98, 0x10),
    "rx_length_mismatch": (0x9C, 0x48),
    "rx_cca_primary": (0xA0, 0x4C),
    "rx_ed": (0xA4, 0x58),
    "tx_channel_idle": (0xC0, 0x24),
    "tx_cca_nav": (0xC4, 0x54),
}
CHANNEL_FIELDS = {
    "primary": 0x30,
    "center1": 0x34,
    "center2": 0x38,
    "width_raw": 0x3C,
    "secondary_offset_raw": 0x40,
}
# e0028a70/ace/ae6 list heads; release increments head+8 at e0028aae..ab2.
# Read only counts, never list pointers, command buffers or peer content.
POOL_COUNTS = (0x222EFC0, 0x222ED84, 0x222E238)


def pool_counts(dev):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 object pool counts only")
    values = {hex(address): dev.rr(address) for address in POOL_COUNTS}
    if any(type(v) is not int or not 0 <= v < 0xFFFFFFFF for v in values.values()):
        raise ValueError("invalid pool count")
    return values


def plan(suite):
    if suite == "channel":
        return ((6, 0), (6, 3), (11, 3), (6, 3), (6, 3), (6, 0))
    if suite in ("basic-repeat", "diagnostic-repeat"):
        return ((6, 0 if suite == "basic-repeat" else 3),) * 6
    if suite in ("diagnostic-three", "diagnostic-four"):
        return ((6, 3),) * (3 if suite == "diagnostic-three" else 4)
    raise ValueError("bounded statistics suite required")


def request(tag):
    if type(tag) is not int or tag not in (0, 3):
        raise ValueError("only basic0 or diagnostic3")
    return struct.pack("<4xHH", tag, 4)


def parse(body, tag):
    request(tag)
    if len(body) < 8:
        raise ValueError("statistics header")
    actual, size = struct.unpack_from("<HH", body, 4)
    if actual != tag or size != len(body) - 4:
        raise ValueError("statistics tag/length")
    if tag == 0:
        if size != 4:
            raise ValueError("unexpected pinned basic reply")
        return {"tag": 0, "tlv_bytes": 4, "counters_available": False}
    if size != 200 or struct.unpack_from("<I", body, 8)[0] != 1:
        raise ValueError("pinned diagnostic size/version")
    tlv = body[4:]

    def word(offset):
        return struct.unpack_from("<I", tlv, offset)[0]

    return {
        "tag": 3,
        "tlv_bytes": size,
        "version": 1,
        "channel_state": {name: word(at) for name, at in CHANNEL_FIELDS.items()},
        "cached_mac_counters": {name: word(at) for name, (at, _) in CACHE_FIELDS.items()},
        "phy_section_zero_filled": not any(tlv[0x5C:0x8C]),
        "phy_counters_available": False,
        "note": "RAM-cache/configuration readout; not atomic, calibrated airtime or PHY health",
    }


def verify_table(dev):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 only")
    actual = {}
    for i in range(6):
        at = 0x2215504 + 8 * i
        actual[dev.rr(at)] = dev.rr(at + 4)
    if actual != TAG_HANDLERS:
        raise ValueError("pinned UNI23 tag table mismatch")
    return True


def snapshot(dev):
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925 cache only")
    values = {name: dev.rr(0x224C408 + offset) for name, (_, offset) in CACHE_FIELDS.items()}
    if any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in values.values()):
        raise ValueError("invalid RAM-cache word")
    return values


def query(dev, tag):
    dev.mcu_uni(0x23, request(tag), query=True, wait=False)
    sequence = dev.msg_seq
    start, attempts, received = time.monotonic(), 0, 0
    event_shapes = []
    while time.monotonic() - start < 0.7 and attempts < 1024:
        for ep in (dev.ep_in_pkt_rx, dev.ep_in_cmd_resp):
            attempts += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            decoded = m.decoder_for(dev)(raw)
            if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
                received += 1
            event = mac.event_body(raw)
            if event and len(event_shapes) < 16:
                event_shapes.append(
                    {"eid": event[0], "sequence": event[1], "body_bytes": len(event[2])}
                )
            if event and event[:2] == (0x23, sequence):
                try:
                    parsed = parse(event[2], tag)
                except ValueError:
                    return {
                        "error": "unexpected_statistics_shape",
                        "sequence": sequence,
                        "body_bytes": len(event[2]),
                        "event_shapes": event_shapes,
                    }
                return {
                    "event": parsed,
                    "sequence": sequence,
                    "ordinary_good_during_query": received,
                    "attempts": attempts,
                }
    return {
        "error": "no_matched_statistics_event",
        "sequence": sequence,
        "attempts": attempts,
        "ordinary_good_during_query": received,
        "event_shapes": event_shapes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=(
            "channel",
            "basic-repeat",
            "diagnostic-repeat",
            "diagnostic-three",
            "diagnostic-four",
        ),
        default="diagnostic-three",
    )
    parser.add_argument("--allow-command-stall", action="store_true")
    args = parser.parse_args()
    if sum(tag == 3 for _, tag in plan(args.suite)) >= 4 and not args.allow_command_stall:
        parser.error("four diagnostics can stall commands; explicit --allow-command-stall required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transmissions": 0,
        "queries": [],
        "suite": args.suite,
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        check_image(images[1])

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            boot()
            out["tag_table_matches"] = verify_table(dev)
            out["pool_counts_initial"] = pool_counts(dev)
            current_channel = 6
            for channel, tag in plan(args.suite):
                out["current_step"] = {"channel": channel, "tag": tag, "operation": "tune"}
                if channel != current_channel:
                    dev.tune("2.4GHz", channel, channel, 20)
                    current_channel = channel
                time.sleep(0.2)
                out["current_step"]["operation"] = "query"
                before = snapshot(dev) if tag == 3 else None
                pools_before = pool_counts(dev)
                row = query(dev, tag)
                row["pool_counts_before"] = pools_before
                row["pool_counts_after"] = pool_counts(dev)
                row["configured_channel"] = channel
                row["requested_tag"] = tag
                if "error" in row:
                    out["queries"].append(row)
                    raise RuntimeError("statistics query failed; sanitized context retained")
                if tag == 3:
                    after = snapshot(dev)
                    row["cache_before"], row["cache_after"] = before, after
                    row["cache_checks"] = {
                        name: {
                            "endpoints_equal": before[name] == after[name],
                            "reply_matches_both": before[name] == value == after[name],
                        }
                        for name, value in row["event"]["cached_mac_counters"].items()
                    }
                out["queries"].append(row)
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                out["thermal_command_after_statistics"] = thermal.query(dev, 0)
            except Exception as exc:
                out["thermal_command_error_type"] = type(exc).__name__
            try:
                out["pool_counts_after_thermal"] = pool_counts(dev)
            except Exception:
                out["pool_count_read_failed"] = True
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
                out["pool_counts_after_reload"] = pool_counts(dev)
            except Exception:
                out["cleanup_reload_alive"] = False
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out
        or "thermal_command_error_type" in out
        or not out["cleanup_reload_alive"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
