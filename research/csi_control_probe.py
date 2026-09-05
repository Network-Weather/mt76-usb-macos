#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded station CSI stop/start/stop; metadata only, no TX or coefficient output.

Vendor gen4m 8fddb9d7: gl_csi.h, nic_uni_cmd_event.h/c, wlan_oid.c.
MT7961 CE 0x4c has a 48-byte control; MT7925 UNI 0x4a has 8-byte
stop/start TLVs. UNI SET/no-ACK follows wlanoidSetCSIControl. Normal monitor
channel36/149 at bounded receive widths, three to five <=1-second/512-transfer windows,
finally STOP + reload. --ack requests diagnostic acknowledgments separately
from the vendor's no-ACK envelope.
This tests command/event availability, not validity or calibration of CSI.
--beacon-selector tests index0/value0x20; validated CSI emits aggregate statistics
only. No transmitter addresses, coefficient arrays or payload hashes are exported.
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
from research.csi_correlation import CsiCorrelation
from research.csi_event_summary import CsiSummary


def hardware_snapshot(dev):
    """ROM 0x0084581e: band-specific enable bit; never write MMIO here."""
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("hardware snapshot is MT7925 only")
    rows = []
    for band in (0, 1):
        address = 0x820E5060 + (band << 16)
        value = dev.rr(address)
        rows.append(
            {
                "band": band,
                "address": hex(address),
                "value": hex(value),
                "enable_bit29": bool(value & (1 << 29)),
            }
        )
    return rows


def control_snapshot(dev):
    """Pinned loaded handler e003d404: two 14-byte configuration records.

    Read only this fixed configuration array, not CSI samples or nearby MAC data.
    Field labels remain candidate meanings until independently corroborated.
    """
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("control snapshot is MT7925 only")
    base = 0x02239760
    data = b"".join(struct.pack("<I", dev.rr(address)) for address in range(base, base + 28, 4))
    return [
        {
            "address": hex(base + i * 14),
            "mode_raw": record[0],
            "band_raw": record[1],
            "max_chain_raw": record[2],
            "chain_config_flag_raw": record[3],
            "enable_raw": record[4],
            "frame_config_mask_raw": record[5],
            "frame_selection_raw": list(record[6:10]),
            "auxiliary_raw": list(record[10:14]),
        }
        for i in range(2)
        for record in (data[i * 14 : (i + 1) * 14],)
    ]


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


def beacon_selector_request(band):
    """Test index0/value0x20: beacon FC bits[7:2], validated on MT7925.

    Public packed tag2 is 11 bytes. The loaded handler consumes its low value
    byte, and the ROM field table limits the hardware selector to six bits.
    """
    return frame_selector_request(band, 0x20)


def frame_selector_request(band, selector):
    """Named FC[7:2] candidates only, no arbitrary filter mask."""
    if type(band) is not int or band not in (0, 1):
        raise ValueError("band must be zero or one")
    if type(selector) is not int or selector not in (0x02, 0x20, 0x22, 0x25, 0x2D):
        raise ValueError("only named frame selector candidates")
    return struct.pack("<B3xHHBI2x", band, 2, 11, 0, selector)


def receive_center(width, primary=36):
    """Two previously tested passive primaries; no arbitrary geometry or TX."""
    if type(width) is not int or width not in (20, 80, 160):
        raise ValueError("only 20/80/160 MHz receive widths")
    if type(primary) is not int or primary not in (36, 149):
        raise ValueError("only primary36/149")
    if primary == 149:
        if width == 160:
            raise ValueError("primary149 only supports 20/80 in this probe")
        return 149 if width == 20 else 155
    return {20: 36, 80: 42, 160: 50}[width]


def frame_shape(decoded):
    """Good-FCS frame class/PHY only, no addresses or packet contents."""
    if not decoded or decoded.get("fcs_err"):
        return None
    frame = decoded.get("frame", b"")
    if len(frame) < 2:
        return None
    phy = decoded.get("phy", {})
    return {
        "fc_type_subtype": frame[0] & 0xFC,
        "phy_mode_raw": phy.get("mode"),
        "bw_mhz": phy.get("bw_mhz"),
        "nss": phy.get("nss"),
    }


def collect(dev, seq, correlate=False):
    started = time.monotonic()
    deadline = started + 1
    count = 0
    events = collections.Counter()
    frames = collections.Counter()
    csi = CsiSummary()
    correlation = CsiCorrelation() if correlate else None
    decode = m.decoder_for(dev)
    while time.monotonic() < deadline and count < 512:
        try:
            raw = bytes(dev.rx_read(timeout=100))
        except usb.core.USBTimeoutError:
            continue
        count += 1
        decoded = decode(raw)
        frame = frame_shape(decoded)
        if frame is not None:
            frames[json.dumps(frame, sort_keys=True)] += 1
        if correlation is not None:
            correlation.add_frame(decoded)
        shape = event_shape(raw, dev.CHIP, seq)
        if shape is not None:
            events[json.dumps(shape, sort_keys=True)] += 1
            if dev.CHIP == m.CHIP_MT7925 and shape.get("candidate_csi_event"):
                csi.add(raw[44 : 44 + shape["body_bytes"]])
                if correlation is not None:
                    correlation.add_csi(raw[44 : 44 + shape["body_bytes"]])
    return {
        "transfers": count,
        "elapsed_s": round(time.monotonic() - started, 3),
        "transfer_limit_reached": count == 512,
        "events": [{"shape": json.loads(key), "count": value} for key, value in events.items()],
        "good_fcs_frame_classes": [
            {"shape": json.loads(key), "count": value} for key, value in frames.items()
        ],
        "csi_summary": csi.export(),
        "correlation": correlation.export() if correlation is not None else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chip", choices=("mt7961", "mt7925"), required=True)
    parser.add_argument("--ack", action="store_true", help="MT7925 diagnostic ACK envelope")
    parser.add_argument("--band", type=int, choices=(0, 1), default=0)
    parser.add_argument("--chains", type=int, choices=(1, 2))
    parser.add_argument("--width", type=int, choices=(20, 80, 160), default=20)
    parser.add_argument("--primary", type=int, choices=(36, 149), default=36)
    parser.add_argument(
        "--state", action="store_true", help="read fixed firmware CSI configuration"
    )
    parser.add_argument("--hardware", action="store_true", help="read ROM-derived CSI MMIO")
    selectors = parser.add_mutually_exclusive_group()
    selectors.add_argument(
        "--beacon-selector", action="store_true", help="test frame selector 0x20"
    )
    selectors.add_argument(
        "--qos-data-selector", action="store_true", help="test frame selector 0x22"
    )
    selectors.add_argument(
        "--data-selector", action="store_true", help="test non-QoS data selector 0x02"
    )
    selectors.add_argument(
        "--blockack-selector", action="store_true", help="test BlockAck selector 0x25"
    )
    selectors.add_argument("--rts-selector", action="store_true", help="test RTS selector 0x2d")
    parser.add_argument(
        "--correlate", action="store_true", help="aggregate CSI/beacon coincidences"
    )
    args = parser.parse_args()
    selection = next(
        (
            (name, value)
            for name, value in (
                ("beacon", 0x20),
                ("qos_data", 0x22),
                ("data", 0x02),
                ("blockack", 0x25),
                ("rts", 0x2D),
            )
            if getattr(args, f"{name}_selector")
        ),
        None,
    )
    if args.ack and args.chip != "mt7925":
        parser.error("ACK variant applies to MT7925 UNI only")
    if args.chains is not None and args.chip != "mt7925":
        parser.error("chain variant applies to MT7925 UNI only")
    if args.state and args.chip != "mt7925":
        parser.error("state snapshots apply to MT7925 only")
    if args.hardware and args.chip != "mt7925":
        parser.error("hardware snapshots apply to MT7925 only")
    if selection is not None and args.chip != "mt7925":
        parser.error("frame selector applies to MT7925 only")
    if selection is not None and selection[0] != "beacon" and args.correlate:
        parser.error("current source correlation is beacon-only")
    if args.correlate and args.chip != "mt7925":
        parser.error("correlation applies to MT7925 only")
    if args.width != 20 and args.chip != "mt7925":
        parser.error("wider CSI receive tests apply to MT7925 only")
    try:
        center = receive_center(args.width, args.primary)
    except ValueError as exc:
        parser.error(str(exc))
    uid = "0846:9072" if args.chip == "mt7925" else "0e8d:7961"
    out = {
        "tool": "csi_control_probe",
        "chip": args.chip,
        "band": args.band,
        "receive_width_mhz": args.width,
        "primary_channel": args.primary,
        "center_channel": center,
        "chains": args.chains,
        "state_snapshots": args.state,
        "hardware_snapshots": args.hardware,
        "candidate_beacon_selector": args.beacon_selector,
        "candidate_qos_data_selector": args.qos_data_selector,
        "candidate_data_selector": args.data_selector,
        "candidate_blockack_selector": args.blockack_selector,
        "candidate_rts_selector": args.rts_selector,
        "correlation_enabled": args.correlate,
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
            dev.tune("5GHz", args.primary, center, args.width)
            if args.state:
                out["control_before"] = control_snapshot(dev)
            if args.hardware:
                out["hardware_before"] = hardware_snapshot(dev)
            for name, start in (("stop_before", False), ("start", True), ("stop_after", False)):
                if start and selection is not None:
                    selector_name, selector = selection
                    dev.mcu_uni(
                        0x4A, frame_selector_request(args.band, selector), wait=False, timeout=1000
                    )
                    seq = dev.msg_seq
                    out["phases"].append(
                        {
                            "name": f"candidate_{selector_name}_selector",
                            "request_sequence": seq,
                            **collect(dev, seq, args.correlate),
                        }
                    )
                    if args.hardware:
                        out["phases"][-1]["hardware_after"] = hardware_snapshot(dev)
                    if args.state:
                        out["phases"][-1]["control_after"] = control_snapshot(dev)
                if start and args.chains is not None:
                    dev.mcu_uni(
                        0x4A, chain_request(args.band, args.chains), wait=False, timeout=1000
                    )
                    seq = dev.msg_seq
                    out["phases"].append(
                        {
                            "name": "chains",
                            "request_sequence": seq,
                            **collect(dev, seq, args.correlate),
                        }
                    )
                    if args.state:
                        out["phases"][-1]["control_after"] = control_snapshot(dev)
                    if args.hardware:
                        out["phases"][-1]["hardware_after"] = hardware_snapshot(dev)
                seq = send(start)
                out["phases"].append(
                    {"name": name, "request_sequence": seq, **collect(dev, seq, args.correlate)}
                )
                if args.state:
                    out["phases"][-1]["control_after"] = control_snapshot(dev)
                if args.hardware:
                    out["phases"][-1]["hardware_after"] = hardware_snapshot(dev)
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
            if args.state:
                out["control_after_cleanup"] = control_snapshot(dev)
            if args.hardware:
                out["hardware_after_cleanup"] = hardware_snapshot(dev)
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
