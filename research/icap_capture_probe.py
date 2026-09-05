#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Bounded MT7961 on-chip ICAP experiment; no TX or host-memory DMA.

Protocol: pinned Motorola gen4m wlan_oid.h RBIST_CAP_START_T, FUNC_IDX;
wlan_oid.c wlanoidExtRfTestICapStart and wlanoidRfTestICapGetIQData.
Node 0 is a candidate from the QA legacy default, NOT a proven MT7961 ADC node.
At most 256 requested samples, ring off, architecture 0 (on-chip),
all EMI/source addresses zero. Optional one 1-KiB bank request after capture.
Only event metadata and bounded sample summary statistics leave the process.
No raw IQ, ambient frame bytes, addresses, or packet fingerprints are serialized.
Always stop capture and reload firmware after the experiment.
"""

import argparse
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.firmware_fields import icap_snapshot
from research.icap_status_probe import event_summary, status_request
from research.testmode_receiver_probe import rx_setting


def capture_request(samples=256, trigger=True, trigger_event=0, node=0):
    if samples not in (64, 256) or type(trigger) is not bool:
        raise ValueError("bounded sample count and boolean trigger required")
    if trigger_event not in (0, 0xFFFFFFFF):
        raise ValueError("only baseline or firmware-derived no-event-gate candidate")
    if node not in (0, 0x49, 0x00110000):
        raise ValueError("only baseline or source-derived node candidate")
    words = [0] * 20
    words[0] = int(trigger)
    words[2] = trigger_event
    words[3] = node
    words[4] = samples
    words[5] = samples
    # Firmware 0x0096c562: event -1 clears bit 19 rather than selecting an event.
    # Node 0x49 is the pinned QA mapping for node 8, not validated for MT7961.
    # 0x00110000: firmware-recognized packed class 0x11, format/group 0, selector 0.
    # 0x96c4d2 halves its stop count; 0x96c4f0 routes class into PHY selector.
    # ring=0, architecture=0; no EMI addresses.
    return struct.pack("<B3xI20I", 1, 11, *words)


def data_request():
    # Address 0 / offset 4 / bank 1: documented solicited ICAP retrieval shape.
    # Explicit one-KiB request instead of unbounded/default bank size zero.
    return struct.pack("<B3xI6I56x", 1, 17, 0, 4, 1, 1, 0, 0)


def channel_request(selector, value):
    if (selector, value) not in ((104, 0), (106, 3 << 16), (18, 5180000), (15, 0), (1, 13)):
        raise ValueError("only fixed ICAP channel/RX-path setup allowed")
    # gl_qa_agent.c: COMMAND_CH_SWITCH_FOR_ICAP=13, not a TX-start command.
    return struct.pack("<B3xII", 1, selector, value)


def summarize_data(body):
    if len(body) < 48:
        return None
    function, packet, bank, length, chains, samples = struct.unpack_from("<6I", body)
    if function != 17:
        return None
    out = {
        "packet_index": packet,
        "bank": bank,
        "data_length_raw": length,
        "chain_count_raw": chains,
        "sample_count_raw": samples,
    }
    if length <= 256 and len(body) >= 48 + 4 * length:
        values = struct.unpack_from(f"<{length}i", body, 48)
        out.update(
            decoded_words=length,
            nonzero_words=sum(v != 0 for v in values),
            unique_values=len(set(values)),
            min_value=min(values) if values else None,
            max_value=max(values) if values else None,
        )
    else:
        out["unexpected_data_shape"] = True
    return out


def collect(dev, seconds, seq):
    out = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            raw = bytes(dev.rx_read(timeout=100))
        except usb.core.USBTimeoutError:
            continue
        event = event_summary(raw, seq)
        if event is None or len(out) >= 32:
            continue
        if event["eid"] == 0xED and event["ext_eid"] == 4:
            body = raw[36 : 36 + event["body_bytes"]]
            if len(body) >= 4:
                event["function_raw"] = struct.unpack_from("<I", body)[0]
            data = summarize_data(body)
            if data is not None:
                event["sample_summary"] = data
        out.append(event)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--samples", type=int, choices=(64, 256), default=256)
    p.add_argument(
        "--node", type=lambda value: int(value, 0), choices=(0, 0x49, 0x00110000), default=0
    )
    p.add_argument(
        "--no-event-gate", action="store_true", help="firmware-derived event -1 candidate"
    )
    p.add_argument("--prepare-rx", action="store_true")
    p.add_argument(
        "--icap-rx", action="store_true", help="activate bounded RX after ICAP-mode entry"
    )
    p.add_argument(
        "--icap-channel", action="store_true", help="explicit ICAP channel-switch preparation"
    )
    p.add_argument("--retrieve", action="store_true")
    p.add_argument("--registers", action="store_true", help="separate ROM-derived register check")
    args = p.parse_args()
    out = {
        "tool": "icap_capture_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "samples_requested": args.samples,
        "trigger_event": 0xFFFFFFFF if args.no_event_gate else 0,
        "node_candidate": args.node,
        "architecture": 0,
        "prepare_rx": args.prepare_rx,
        "icap_rx": args.icap_rx,
        "icap_channel": args.icap_channel,
        "retrieve": args.retrieve,
        "register_checks": args.registers,
        "polls": [],
    }
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        def ext(payload, query=False):
            dev.mcu_cmd_word(
                m.MCU_EXT_CMD(4) | (m.MCU_CMD_FIELD_QUERY if query else 0),
                payload,
                wait=False,
                timeout=1000,
            )

        boot()
        try:
            if args.prepare_rx:
                dev.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
                time.sleep(0.2)
                for selector, value in ((104, 0), (106, 3 << 16), (18, 5180000), (15, 0), (1, 2)):
                    dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(selector, value), wait=False)
                    time.sleep(0.1)
            dev.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 2, 0), wait=False)
            time.sleep(0.2)
            if args.icap_channel:
                for selector, value in ((104, 0), (106, 3 << 16), (18, 5180000), (15, 0), (1, 13)):
                    dev.mcu_cmd_word(m.MCU_CE_CMD(1), channel_request(selector, value), wait=False)
                    time.sleep(0.1)
            if args.icap_rx:
                # Original MtkICAPtool starts RX after entering ICAP mode.
                # Earlier --prepare-rx ran before mode entry, which can stop it.
                for selector, value in ((104, 0), (106, 3 << 16), (18, 5180000), (15, 0), (1, 2)):
                    dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(selector, value), wait=False)
                    time.sleep(0.1)
            ext(status_request(), query=True)
            out["before"] = collect(dev, 0.3, dev.msg_seq)
            if args.registers:
                out["registers_before"] = icap_snapshot(dev)
            ext(capture_request(args.samples, trigger_event=out["trigger_event"], node=args.node))
            out["start_events"] = collect(dev, 0.3, dev.msg_seq)
            if args.registers:
                out["registers_after_start"] = icap_snapshot(dev)
            for _ in range(3):
                ext(status_request(), query=True)
                out["polls"].append(collect(dev, 0.3, dev.msg_seq))
            out["completion_observed"] = any(
                e.get("candidate_capture_done_raw") == 1 for poll in out["polls"] for e in poll
            )
            if args.registers:
                out["registers_after_polls"] = icap_snapshot(dev)
            if args.retrieve and out["completion_observed"]:
                ext(data_request(), query=True)
                out["data_events"] = collect(dev, 1.0, dev.msg_seq)
            elif args.retrieve:
                out["retrieval_skipped"] = "capture did not report completion"
            out["alive_after"] = dev.alive()
        except (m.McuError, RuntimeError, usb.core.USBError) as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                ext(
                    capture_request(
                        args.samples,
                        trigger=False,
                        trigger_event=out["trigger_event"],
                        node=args.node,
                    )
                )
                out["stop_events"] = collect(dev, 0.2, dev.msg_seq)
                if args.registers:
                    out["registers_after_stop"] = icap_snapshot(dev)
            except (m.McuError, RuntimeError, usb.core.USBError) as exc:
                out["stop_error_type"] = type(exc).__name__
            boot()
            out["cleanup_reload_alive"] = dev.alive()
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out["cleanup_reload_alive"])


if __name__ == "__main__":
    raise SystemExit(main())
