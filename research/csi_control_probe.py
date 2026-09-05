#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded station CSI stop/start/stop; metadata only, no TX or coefficient output.

Vendor gen4m 8fddb9d7: gl_csi.h, nic_uni_cmd_event.h/c, wlan_oid.c.
MT7961 CE 0x4c has a 48-byte control; MT7925 UNI 0x4a has 8-byte
stop/start TLVs. UNI SET/no-ACK follows wlanoidSetCSIControl. Normal monitor
channel36/20MHz, three (four with --chains) <=1-second/512-transfer windows,
finally STOP + reload. --ack requests diagnostic acknowledgments separately
from the vendor's no-ACK envelope.
This tests command/event availability, not validity or calibration of CSI.
"""

import argparse
import collections
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m


def request(chip, start, band=0):
    if type(start) is not bool:
        raise ValueError("only boolean stop/start controls")
    if type(band) is not int or band not in (0, 1):
        raise ValueError("band must be zero or one")
    if chip == m.CHIP_MT7925:
        return struct.pack("<B3xHH", band, int(start), 4)
    if chip == m.CHIP_MT7921:
        return struct.pack("<BB46x", band, int(start))
    raise ValueError("unsupported chip")


def event_shape(raw, chip, seq):
    header = 44 if chip == m.CHIP_MT7925 else 36
    eid_offset = 36 if chip == m.CHIP_MT7925 else 28
    if len(raw) < header:
        return None
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if not header <= size <= len(raw) or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT:
        return None
    if (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU:
        return None
    eid, rseq = raw[eid_offset : eid_offset + 2]
    csi_eid, cid = (0x4A, 0x4A) if chip == m.CHIP_MT7925 else (0x3C, 0x4C)
    if rseq not in (0, seq) or (eid != csi_eid and rseq != seq):
        return None
    body = raw[header:size]
    out = {"eid": eid, "sequence": rseq, "body_bytes": len(body)}
    if eid == 0xFD:
        # Vendor EVENT_ID_INIT_EVENT_CMD_RESULT: generic command-not-found event.
        out["command_not_found_event"] = True
    if len(body) >= 8 and struct.unpack_from("<I", body)[0] == cid:
        out["command_result_status"] = struct.unpack_from("<I", body, 4)[0]
    if eid == csi_eid:
        out["candidate_csi_event"] = True
        if chip == m.CHIP_MT7925 and len(body) >= 8:
            tag, length = struct.unpack_from("<HH", body, 4)
            out.update(tlv_tag=tag, tlv_bytes=length)
            out["valid_outer_tlv"] = tag == 0 and length == len(body) - 4
        # Never serialize coefficients, transmitter addresses or arbitrary body words.
    return out


def chain_request(band, chains):
    if type(band) is not int or band not in (0, 1):
        raise ValueError("band must be zero or one")
    if type(chains) is not int or chains not in (1, 2):
        raise ValueError("only one or two receive chains")
    # UNI_CMD_CSI_SET_CHAIN_NUMBER, tag3 length8 (vendor header).
    return struct.pack("<B3xHHB3x", band, 3, 8, chains)


def collect(dev, seq):
    started = time.monotonic()
    deadline = started + 1
    count = 0
    events = collections.Counter()
    while time.monotonic() < deadline and count < 512:
        try:
            raw = bytes(dev.rx_read(timeout=100))
        except usb.core.USBTimeoutError:
            continue
        count += 1
        shape = event_shape(raw, dev.CHIP, seq)
        if shape is not None:
            events[json.dumps(shape, sort_keys=True)] += 1
    return {
        "transfers": count,
        "elapsed_s": round(time.monotonic() - started, 3),
        "transfer_limit_reached": count == 512,
        "events": [{"shape": json.loads(key), "count": value} for key, value in events.items()],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chip", choices=("mt7961", "mt7925"), required=True)
    parser.add_argument("--ack", action="store_true", help="MT7925 diagnostic ACK envelope")
    parser.add_argument("--band", type=int, choices=(0, 1), default=0)
    parser.add_argument("--chains", type=int, choices=(1, 2))
    args = parser.parse_args()
    if args.ack and args.chip != "mt7925":
        parser.error("ACK variant applies to MT7925 UNI only")
    if args.chains is not None and args.chip != "mt7925":
        parser.error("chain variant applies to MT7925 UNI only")
    uid = "0846:9072" if args.chip == "mt7925" else "0e8d:7961"
    out = {
        "tool": "csi_control_probe",
        "chip": args.chip,
        "band": args.band,
        "chains": args.chains,
        "uni_option": (7 if args.ack else 6) if args.chip == "mt7925" else None,
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "phases": [],
    }
    with m.open_device(uid) as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        original_option = dev.uni_option
        dev.uni_option = lambda cid, query=False: (
            (7 if args.ack else 6) if cid == 0x4A else original_option(cid, query)
        )

        def send(start):
            payload = request(dev.CHIP, start, args.band)
            if dev.CHIP == m.CHIP_MT7925:
                dev.mcu_uni(0x4A, payload, wait=False, timeout=1000)
            else:
                dev.mcu_cmd_word(m.MCU_CE_CMD(0x4C), payload, wait=False, timeout=1000)
            return dev.msg_seq

        try:
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)
            for name, start in (("stop_before", False), ("start", True), ("stop_after", False)):
                if start and args.chains is not None:
                    dev.mcu_uni(
                        0x4A, chain_request(args.band, args.chains), wait=False, timeout=1000
                    )
                    seq = dev.msg_seq
                    out["phases"].append(
                        {"name": "chains", "request_sequence": seq, **collect(dev, seq)}
                    )
                seq = send(start)
                out["phases"].append({"name": name, "request_sequence": seq, **collect(dev, seq)})
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                send(False)
            except Exception as exc:
                out["cleanup_stop_error_type"] = type(exc).__name__
            dev.uni_option = original_option
            dev.bringup(*images, log=lambda *_: None)
            out["cleanup_reload_alive"] = dev.alive()
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
