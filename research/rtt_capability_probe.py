#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read-only station RTT capabilities, two queries and full reload.

Pinned gen4m: CE44 QUERY with no payload, or UNI5d QUERY_ACK3/tag0 length4.
No range request, peer address, calibration, RF test mode, or host TX.
Only exact capability event scalar bytes and event metadata are exported.
"""

import argparse
import collections
import contextlib
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m


def request(chip):
    if chip == m.CHIP_MT7921:
        return b""
    if chip == m.CHIP_MT7925:
        return struct.pack("<4xHH", 0, 4)
    raise ValueError("only pinned MT7961/MT7925")


def location_capability(caps):
    """Only LOCATION tag0c's documented four bytes; never export other NIC tags."""
    value = caps.get(0x0C)
    out = {
        "location_tag_present": value is not None,
        "location_bytes": len(value) if value is not None else 0,
    }
    if value is not None and len(value) == 4:
        out["toa_engine_advertised_raw"] = value[0]
        out["reserved_all_zero"] = value[1:] == bytes(3)
    return out


def summarize(raw, chip, sequence):
    request(chip)
    header = 44 if chip == m.CHIP_MT7925 else 36
    if len(raw) < header:
        return None
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if (
        not header <= size <= len(raw)
        or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT
        or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
    ):
        return None
    eid, seq = raw[header - 8 : header - 6]
    candidate = eid == (0x5D if chip == m.CHIP_MT7925 else 0x2D)
    if seq != sequence and not (candidate and seq == 0):
        return None
    body = raw[header:size]
    out = {
        "eid": eid,
        "sequence_matches": seq == sequence,
        "sequence_zero": seq == 0,
        "body_bytes": len(body),
    }
    cid = 0x5D if chip == m.CHIP_MT7925 else 0x44
    if eid == 1 and seq == sequence and len(body) == 8 and struct.unpack_from("<I", body)[0] == cid:
        out["command_result_status"] = struct.unpack_from("<I", body, 4)[0]
    if eid == 0xFD:
        out["command_not_found_event"] = True
    if candidate:
        if chip == m.CHIP_MT7925:
            if len(body) != 16 or body[:8] != struct.pack("<4xHH", 0, 12):
                return out | {"unrecognized_capability_shape": True}
            body = body[8:]
        if len(body) != 8:
            return out | {"unrecognized_capability_shape": True}
        out["capability_bytes_raw"] = list(body)
    return out


def query(dev):
    payload = request(dev.CHIP)
    if dev.CHIP == m.CHIP_MT7925:
        if dev.uni_option(0x5D, True) != 3:
            raise ValueError("explicit QUERY_ACK3 required")
        dev.mcu_uni(0x5D, payload, query=True, wait=False, timeout=1000)
    else:
        dev.mcu_cmd_word(
            m.MCU_CE_CMD(0x44) | m.MCU_CMD_FIELD_QUERY, payload, wait=False, timeout=1000
        )
    sequence = dev.msg_seq
    started = time.monotonic()
    transfers = reads = 0
    frames = collections.Counter()
    endpoints = collections.Counter()
    events = []
    selected = (dev.ep_in_pkt_rx, dev.ep_in_cmd_resp)
    while time.monotonic() - started < 1 and transfers < 512:
        endpoint = selected[reads % 2]
        reads += 1
        try:
            raw = bytes(dev.bulk_in(endpoint, 4096, 1))
        except usb.core.USBTimeoutError:
            continue
        transfers += 1
        endpoints[f"{endpoint:02x}"] += 1
        decoded = m.decoder_for(dev)(raw)
        if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
            frames[str(decoded.get("phy", {}).get("mode"))] += 1
        event = summarize(raw, dev.CHIP, sequence)
        if event is not None:
            events.append(event)
    return {
        "events": events,
        "good_fcs_frames_by_phy_mode": dict(frames),
        "endpoint_transfers": dict(endpoints),
        "transfers": transfers,
        "transfer_limit_reached": transfers == 512,
        "elapsed_seconds": time.monotonic() - started,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chip", choices=("mt7961", "mt7925"), required=True)
    args = parser.parse_args()
    out = {
        "tool": "rtt_capability_probe",
        "chip": args.chip,
        "channel": 36,
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": [],
    }
    with m.open_device("0e8d:7961" if args.chip == "mt7961" else "0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        try:
            boot()
            out["location_capability"] = location_capability(dev.get_nic_capability())
            for _ in range(2):
                out["rows"].append(query(dev))
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
