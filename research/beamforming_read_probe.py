#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded MT7925 PFMU tag/profile reads, no writes or sounding transmissions.

Protocol facts: Motorola gen4m 8fddb9d7 nic_uni_cmd_event.h/c and wlan_oid.c.
Loaded MT7925 handlers 0x9169b0/0x91689c independently corroborate field offsets,
event ID 0x33 and fixed result sizes. SET/no-ACK envelope 0x06 is required by the
vendor bridge even for these read tags. Firmware clears request sequence before
building its event; accept sequence zero only with the expected EID/tag/size.
Fresh normal boot, one request, 1.5-second/64-transfer receive limit, full reload.
Only summary/hash metadata is emitted, never coefficient arrays or ambient frames.
"""

import argparse
import datetime
import hashlib
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m

EXPECTED_TLV_SIZE = {5: 64, 7: 276}
PFMU_GATE_OFFSETS = (0x68, 0x6C, 0x70, 0x74, 0x80, 0x84)


def gate_snapshot(dev):
    """Fixed controls read/written by firmware e0058500; no register writes here."""
    return {
        hex(base + offset): hex(dev.rr(base + offset))
        for base in (0x830A3000, 0x831A3000)
        for offset in PFMU_GATE_OFFSETS
    }


def candidate_tag_fields(payload):
    """Fields shared by vendor Connac3 rFieldv2/v3; not calibrated measurements."""
    if len(payload) != 56:
        raise ValueError("exactly two seven-word PFMU tags required")
    first = struct.unpack_from("<I", payload)[0]
    return {
        "profile_id_raw": first & 1023,
        "explicit_bf_raw": (first >> 10) & 1,
        "bandwidth_code_raw": (first >> 11) & 7,
        "mode_code_raw": (first >> 14) & 7,
        "mu_raw": (first >> 17) & 1,
        "nrow_raw": (first >> 18) & 7,
        "ncol_raw": (first >> 21) & 7,
        "invalid_profile_bit": bool(first & (1 << 28)),
        "snr_sts_bytes_raw": list(payload[16:24]),
    }


def read_request(tag, profile=0, bfer=0):
    if type(tag) is not int or tag not in (5, 7):
        raise ValueError("only PFMU read tags 5 and 7")
    if type(profile) is not int or profile not in (0, 1):
        raise ValueError("only profile 0 or 1")
    if type(bfer) is not int or bfer not in (0, 1):
        raise ValueError("BFer selector must be 0 or 1")
    if tag == 5:
        # 12-byte tag header plus two seven-word arrays; all output slots zero.
        return struct.pack("<4xHHBBB61x", 5, 68, profile, bfer, 0)
    # Subcarrier zero, band/TxBf zero. No arbitrary subcarrier/band sweeps.
    return struct.pack("<4xHHBBHB3x", 7, 12, profile, bfer, 0, 0)


def event_summary(raw, request_seq, expected_tag):
    if expected_tag not in EXPECTED_TLV_SIZE or len(raw) < 44:
        return None
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if size < 44 or size > len(raw) or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT:
        return None
    if (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU:
        return None
    eid, seq = raw[36], raw[37]
    if seq not in (0, request_seq):
        return None
    body = raw[44:size]
    out = {
        "eid": eid,
        "sequence": seq,
        "sequence_matches": seq == request_seq,
        "body_bytes": len(body),
    }
    if len(body) >= 8 and struct.unpack_from("<I", body)[0] == 0x33:
        out["command_result_status"] = struct.unpack_from("<I", body, 4)[0]
    if eid != 0x33 or len(body) < 8:
        return out
    tag, length = struct.unpack_from("<HH", body, 4)
    out.update(tlv_tag=tag, tlv_bytes=length)
    if tag != expected_tag or length != EXPECTED_TLV_SIZE[tag] or len(body) != length + 4:
        return out
    payload = body[12:]
    out.update(
        recognized_profile_reply=True,
        payload_bytes=len(payload),
        payload_nonzero_bytes=sum(value != 0 for value in payload),
        payload_distinct_bytes=len(set(payload)),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )
    if tag == 5:
        out["bfer_raw"] = body[8]
        out["candidate_profile_fields"] = candidate_tag_fields(payload)
    else:
        out["subcarrier_raw"] = struct.unpack_from("<H", body, 8)[0]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", type=int, choices=(5, 7), default=5)
    parser.add_argument("--profile", type=int, choices=(0, 1), default=0)
    parser.add_argument("--bfer", type=int, choices=(0, 1), default=0)
    parser.add_argument("--registers", action="store_true", help="snapshot fixed PFMU controls")
    args = parser.parse_args()
    payload = read_request(args.tag, args.profile, args.bfer)
    out = {
        "tool": "beamforming_read_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "tag": args.tag,
        "profile": args.profile,
        "bfer": args.bfer,
        "band": 0,
        "subcarrier": 0,
        "uni_option": 6,
        "request_bytes": len(payload),
        "registers": args.registers,
        "events": [],
        "transfers": 0,
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        original_option = dev.uni_option
        try:
            dev.bringup(*images, log=lambda *_: None)
            if args.registers:
                out["gate_before"] = gate_snapshot(dev)
            dev.uni_option = lambda cid, query=False: (
                6 if cid == 0x33 else original_option(cid, query)
            )
            dev.mcu_uni(0x33, payload, wait=False, timeout=1000)
            seq = dev.msg_seq
            out["request_sequence"] = seq
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and out["transfers"] < 64:
                try:
                    raw = bytes(dev.rx_read(timeout=100))
                except usb.core.USBTimeoutError:
                    continue
                out["transfers"] += 1
                event = event_summary(raw, seq, args.tag)
                if event is not None:
                    out["events"].append(event)
            if args.registers:
                out["gate_after_query"] = gate_snapshot(dev)
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            dev.uni_option = original_option
            dev.bringup(*images, log=lambda *_: None)
            out["cleanup_reload_alive"] = dev.alive()
            if args.registers:
                out["gate_after_cleanup"] = gate_snapshot(dev)
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out["cleanup_reload_alive"])


if __name__ == "__main__":
    raise SystemExit(main())
