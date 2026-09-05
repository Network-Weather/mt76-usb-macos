#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded MT7961 receive-vector log readout under eight synthetic no-ACK probes.

Send four MT7925 HT MCS8/20MHz controls and require independent receipt of at
least one before four RF RX stimuli. STOP precedes reading four PHY words from at most
three records. No full vectors, frame identities, payloads or hashes are emitted.
Pinned firmware writer stride176 and getter bound exclude the newest record.
Both radios are normally reloaded on exit. Explicit transmit opt-in required.
--rearm-he adds four independently observed HE controls, then resets volatile
TX/RX counters and the stopped log before four HE stimuli (16 packets total).
--match-ta instead tests matching/mismatching/matching synthetic transmitter
filters with three reset-separated RF batches (16 packets including controls).
--rf-clean-prepare isolates known normal-RX prerequisites after a receiver reload.
"""

import argparse
import collections
import concurrent.futures
import contextlib
import datetime
import json
import os
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.cfo_crosscheck_probe import decode_cached_fields, snapshot
from research.mt7925_tx_probe import controlled_frame
from research.phy_tx_probe import descriptor, program_rate
from research.testmode_receiver_probe import rx_setting


def log_offsets(count):
    """Only four known PHY words in at most three complete older records."""
    if type(count) is not int or not 0 <= count <= 5:
        raise ValueError("pinned log count must be zero through five")
    return tuple(
        tuple(record * 176 + word * 4 for word in (0, 6, 20, 21))
        for record in range(min(max(count - 1, 0), 3))
    )


def log_fields(word0, word6, word20, word21):
    fields = decode_cached_fields(word0, word20, word21)
    if type(word6) is not int or not 0 <= word6 <= 0xFFFFFFFF:
        raise ValueError("unsigned 32-bit RCPI word required")
    return {
        "phy_mode": (word0 >> 4) & 15,
        "rcpi_bytes": [word6 & 255, (word6 >> 8) & 255],
        "fields": fields,
    }


def reset_log_request():
    """SET91=0: traced volatile TX/RX counters plus log count/offset, not NVM."""
    return struct.pack("<B3xII", 1, 91, 0)


def match_ta_requests(source):
    """SET68/69 address fragments then SET70 rule0; synthetic local TA only."""
    if not isinstance(source, bytes) or len(source) != 6 or source[0] != 2:
        raise ValueError("synthetic locally administered transmitter required")
    return tuple(
        struct.pack("<B3xII", 1, selector, value)
        for selector, value in (
            (68, 0),
            (68 | (1 << 18), 0),
            (69, int.from_bytes(source[:4], "little")),
            (69 | (1 << 18), int.from_bytes(source[4:], "little")),
            (70, 0),
        )
    )


def match_ta_state(dev, source):
    """Only rule/enable flags and equality to our synthetic TA; never addresses."""
    match_ta_requests(source)  # Validate before device access.
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned MT7961 match state only")
    # SET helper 0x9302f0 uses GP+0x1417c band0 config pointer.
    pointer = dev.rr(0x0201717C)
    if not 0x02000000 <= pointer <= 0x0207FFC0 or pointer & 3:
        raise ValueError("unexpected configuration pointer")
    rule = dev.rr(pointer + 0x38)
    flags = dev.rr(pointer + 0x3C) & 0xFFFF
    # ROM callback 0x82776a writes slot0 low32/high16 plus enable bit16.
    low, high = dev.rr(0x820E5208), dev.rr(0x820E520C)
    return {
        "rule": rule,
        "transmitter_filter_flag": bool(flags & 255),
        "receiver_filter_flag": bool(flags >> 8),
        "hardware_enable_bit": bool(high & (1 << 16)),
        "hardware_matches_synthetic_target": struct.pack("<IH", low, high & 65535) == source,
    }


def prepare_after_reload(dev, preparation):
    """Isolate the two existing tune() commands from filter/sniffer enable."""
    if preparation not in ("bare", "tune", "channel", "config", "full"):
        raise ValueError("unknown clean RF preparation")
    if preparation == "full":
        dev.set_monitor_mode()
        dev.set_sniffer(True)
    if preparation in ("tune", "full", "channel"):
        dev.set_chan_info(control_ch=36, center_ch=36, bw=m.CMD_CBW_20MHZ, band=m.CHAN_BAND["5GHz"])
    if preparation in ("tune", "full", "config"):
        dev.config_sniffer(control_ch=36, center_ch=36, band_name="5GHz", bw=m.SNIFFER_BW_20)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    experiment = parser.add_mutually_exclusive_group()
    experiment.add_argument("--rearm-he", action="store_true")
    experiment.add_argument("--match-ta", action="store_true")
    parser.add_argument("--rf-clean-start", action="store_true")
    parser.add_argument("--rf-clean-prepare", choices=("bare", "tune", "channel", "config", "full"))
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit transmit acknowledgment required")
    if args.rf_clean_start and not args.match_ta:
        parser.error("clean-start control requires --match-ta")
    if args.rf_clean_start and args.rf_clean_prepare:
        parser.error("choose one clean preparation control")
    out = {
        "tool": "rxv_log_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "maximum_submissions": 16 if args.rearm_he or args.match_ta else 8,
        "rate": "HT MCS8 two-stream",
        "channel": 36,
        "width_mhz": 20,
        "submitted": 0,
        "rearm_he": args.rearm_he,
        "match_ta": args.match_ta,
        "rf_clean_start": args.rf_clean_start,
        "rf_clean_prepare": args.rf_clean_prepare,
    }
    marker = b"\xdd\x0c\x02NW\x01" + os.urandom(8)
    frames = {i: controlled_frame(i) + marker for i in range(out["maximum_submissions"])}
    code = (1 << 10) | (2 << 6) | 8
    he_code = (1 << 10) | (8 << 6)
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(d.CHIP, m.firmware_dir()) for d in radios]
        rx, tx = radios

        def boot(i, monitor=True):
            d = radios[i]
            with contextlib.redirect_stdout(sys.stderr):
                d.bringup(*images[i], log=lambda *_: None)
            if monitor:
                d.set_monitor_mode()
                d.set_sniffer(True)
                d.tune("5GHz", 36, 36, 20)

        def read_log_count():
            raw = rx.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 2, 36, 40), timeout=1000)
            body = rx.reply_body(raw)
            if len(body) < 8 or struct.unpack_from("<I", body)[0] != 36:
                raise RuntimeError("missing matched count")
            return struct.unpack_from("<I", body, 4)[0]

        def packet_counts():
            values = {}
            for selector, name in ((34, "rx_ok"), (35, "rx_error")):
                raw = rx.mcu_cmd_word(
                    m.MCU_CE_CMD(1), struct.pack("<B3xII", 2, selector, 0), timeout=1000
                )
                body = rx.reply_body(raw)
                if len(body) < 8 or struct.unpack_from("<I", body)[0] != selector:
                    raise RuntimeError("missing matched packet counter")
                values[name] = struct.unpack_from("<I", body, 4)[0]
            return values

        def set_match(source):
            for request in match_ta_requests(source):
                rx.mcu_cmd_word(m.MCU_CE_CMD(1), request, wait=False)
                time.sleep(0.1)

        def read_log_fields(count):
            if not 2 <= count <= 5:
                return {"skipped": "need two to five logged records"}
            rows = []
            # Writer stride176; getter excludes newest record via last-start-offset-4.
            for record, offsets in enumerate(log_offsets(count)):
                words = {}
                for index, offset in zip((0, 6, 20, 21), offsets, strict=True):
                    raw = rx.mcu_cmd_word(
                        m.MCU_CE_CMD(1), struct.pack("<B3xII", 2, 40, offset), timeout=1000
                    )
                    body = rx.reply_body(raw)
                    if len(body) < 8 or struct.unpack_from("<I", body)[0] != 40:
                        raise RuntimeError("missing matched vector word")
                    words[index] = struct.unpack_from("<I", body, 4)[0]
                rows.append(
                    {
                        "record": record,
                        **log_fields(words[0], words[6], words[20], words[21]),
                    }
                )
            return {"records": rows}

        def collect(ready, start):
            decode = m.decoder_for(rx)
            counts = collections.Counter()
            seen = set()
            matched_phy = collections.Counter()
            deadline = time.monotonic() + 1.5
            ready.set()
            while time.monotonic() < deadline and counts["transfers"] < 1024:
                try:
                    raw = bytes(rx.rx_read(timeout=50))
                except usb.core.USBTimeoutError:
                    continue
                counts["transfers"] += 1
                d = decode(raw)
                if not d:
                    continue
                counts[d["pkt_type_name"]] += 1
                if not d.get("fcs_err"):
                    for seq in range(start, start + 4):
                        if d.get("frame") == frames[seq]:
                            seen.add(seq)
                            phy = d.get("phy", {})
                            matched_phy[
                                tuple(phy.get(k) for k in ("mode_name", "mcs", "nss", "bw_mhz"))
                            ] += 1
            return {
                "counts": dict(counts),
                "exact_synthetic_frames": len(seen),
                "matched_phy": [
                    {"mode": p[0], "mcs": p[1], "nss": p[2], "width_mhz": p[3], "count": n}
                    for p, n in matched_phy.items()
                ],
                "transfer_limit_reached": counts["transfers"] == 1024,
            }

        def burst(start, rate=code):
            program_rate(tx, rate)
            ready = threading.Event()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                job = pool.submit(collect, ready, start)
                if not ready.wait(2):
                    raise RuntimeError("observer not ready")
                for seq in range(start, start + 4):
                    frame = frames[seq]
                    body = descriptor(tx, frame, seq, rate) + frame
                    wire = struct.pack("<I", len(body)) + body
                    wire += bytes((-len(wire)) % 4 + 4)
                    tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                    out["submitted"] += 1
                    time.sleep(0.05)
                return job.result(timeout=3)

        try:
            for i in range(2):
                boot(i)
            out["normal_control"] = burst(0)
            if not out["normal_control"]["exact_synthetic_frames"]:
                raise RuntimeError("no independent control receipt; skip RF stimulus")
            if args.rearm_he:
                out["normal_he_control"] = burst(4, he_code)
                if not out["normal_he_control"]["exact_synthetic_frames"]:
                    raise RuntimeError("no independent HE control; skip RF experiment")
            if args.rf_clean_start or args.rf_clean_prepare:
                # Preserve independent controls but remove inherited sniffer configuration.
                boot(0, monitor=False)
                preparation = args.rf_clean_prepare or "bare"
                prepare_after_reload(rx, preparation)
            rx.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
            time.sleep(0.2)
            for selector, value in (
                (1, 0),
                (104, 0),
                (106, 3 << 16),
                (18, 5180000),
                (15, 0),
            ):
                rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(selector, value), wait=False)
                time.sleep(0.1)
            if args.match_ta:
                set_match(frames[0][10:16])
            rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 2), wait=False)
            time.sleep(0.1)
            out["before"] = {"count": read_log_count(), "cached": snapshot(rx)}
            if args.match_ta:
                out["first_match_state"] = match_ta_state(rx, frames[0][10:16])
            out["rf_stimulus"] = burst(8 if args.rearm_he else 4)
            out["after"] = {
                "count": read_log_count(),
                "cached": snapshot(rx),
                "cached_phy_mode": (rx.rr(0x02040808) >> 4) & 15,
            }
            rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
            time.sleep(0.2)
            out["stopped"] = {"count": read_log_count(), "cached": snapshot(rx)}
            out["log_readout"] = read_log_fields(out["stopped"]["count"])
            if args.match_ta:
                out["first_match_packet_counts"] = packet_counts()
                out["match_followups"] = []
                source = frames[0][10:16]
                mismatch = source[:5] + bytes([source[5] ^ 1])
                for phase, target, start in (("mismatch", mismatch, 8), ("rematch", source, 12)):
                    set_match(target)
                    rx.mcu_cmd_word(m.MCU_CE_CMD(1), reset_log_request(), wait=False)
                    time.sleep(0.1)
                    row = {"phase": phase, "reset_count": read_log_count()}
                    out["match_followups"].append(row)
                    if row["reset_count"] != 0:
                        raise RuntimeError("log did not reset before filter batch")
                    rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 2), wait=False)
                    time.sleep(0.1)
                    row["match_state"] = match_ta_state(rx, target)
                    row["stimulus"] = burst(start)
                    rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
                    time.sleep(0.2)
                    row["count"] = read_log_count()
                    row["packet_counts"] = packet_counts()
                    row["log"] = read_log_fields(row["count"])
            if args.rearm_he:
                # Source operation_gen4m.c:mt_op_reset_txrx_counter; firmware
                # 0x9327a0/0x9327a4 explicitly zero log count and last-start offset.
                rx.mcu_cmd_word(m.MCU_CE_CMD(1), reset_log_request(), wait=False)
                time.sleep(0.1)
                out["after_counter_reset"] = {"count": read_log_count(), "cached": snapshot(rx)}
                if out["after_counter_reset"]["count"] != 0:
                    raise RuntimeError("stopped log reset did not clear count")
                rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 2), wait=False)
                time.sleep(0.1)
                out["rearmed_he_stimulus"] = burst(12, he_code)
                rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
                time.sleep(0.2)
                count = read_log_count()
                out["rearmed_stopped"] = {"count": count, "cached": snapshot(rx)}
                out["rearmed_log_readout"] = read_log_fields(count)
            out["alive_after"] = [d.alive() for d in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
            except Exception as exc:
                out["stop_error_type"] = type(exc).__name__
            out["cleanup"] = []
            for i in range(2):
                try:
                    boot(i)
                    out["cleanup"].append({"alive": radios[i].alive()})
                except Exception as exc:
                    out["cleanup"].append({"error_type": type(exc).__name__})
    print(json.dumps(out, indent=2))

    return int("error_type" in out or not all(row.get("alive") for row in out["cleanup"]))


if __name__ == "__main__":
    raise SystemExit(main())
