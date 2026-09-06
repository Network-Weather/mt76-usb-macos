#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded passive MT7925 CSI allowlist test; no identifiers or samples exported.

Pick one transmitter already observed as both CSI and a good-FCS beacon in this
run. Add/remove only that address using station UNI0x4a/tag4. Re-START controls
separate list changes from mode effects. Every window <=1 second/512 transfers;
finally remove selected address, STOP, and fully reload normal firmware.
"""

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
from research import csi_control_probe as p
from research.csi_event_summary import parse_fields


def filter_request(add, address):
    if type(add) is not bool:
        raise ValueError("only boolean add/remove")
    if not isinstance(address, bytes) or len(address) != 6 or address[0] & 1 or not any(address):
        raise ValueError("one six-byte nonzero unicast transmitter required")
    # Public packed UNI_CMD_CSI_SET_FILTER_MODE; loaded handler maps1->add,0->remove.
    return struct.pack("<4xHHBB6s", 4, 12, int(add), 0, address)


class Window:
    def __init__(self, name):
        self.name = name
        self.beacons = collections.Counter()
        self.csi = collections.Counter()
        self.after_ack = collections.Counter()
        self.acks = []
        self.invalid = 0
        self.transfers = 0
        self.elapsed = 0

    def export(self, selected):
        return {
            "name": self.name,
            "transfers": self.transfers,
            "elapsed_s": round(self.elapsed, 3),
            "transfer_limit_reached": self.transfers == 512,
            "command_statuses": self.acks,
            "invalid_csi_events": self.invalid,
            "beacons": sum(self.beacons.values()),
            "beacon_transmitters": len(self.beacons),
            "selected_beacons": self.beacons[selected],
            "csi_reports": sum(self.csi.values()),
            "csi_transmitters": len(self.csi),
            "selected_csi_reports": self.csi[selected],
            "other_csi_reports": sum(v for k, v in self.csi.items() if k != selected),
            "after_ack_selected_csi": self.after_ack[selected],
            "after_ack_other_csi": sum(v for k, v in self.after_ack.items() if k != selected),
        }


def collect(dev, seq, name):
    window = Window(name)
    decode = m.decoder_for(dev)
    started = time.monotonic()
    while time.monotonic() - started < 1 and window.transfers < 512:
        try:
            raw = bytes(dev.rx_read(timeout=100))
        except usb.core.USBTimeoutError:
            continue
        window.transfers += 1
        decoded = decode(raw)
        if decoded and not decoded.get("fcs_err"):
            frame = decoded.get("frame", b"")
            if len(frame) >= 36 and frame[0] == 0x80:
                window.beacons[frame[10:16]] += 1
        shape = p.event_shape(raw, dev.CHIP, seq)
        if shape is None:
            continue
        if "command_result_status" in shape:
            window.acks.append(shape["command_result_status"])
        if shape.get("candidate_csi_event"):
            try:
                fields = parse_fields(raw[44 : 44 + shape["body_bytes"]])
            except ValueError:
                window.invalid += 1
                continue
            ta = fields[10][:6]
            window.csi[ta] += 1
            if window.acks:
                window.after_ack[ta] += 1
    window.elapsed = time.monotonic() - started
    return window


def main():
    out = {
        "tool": "csi_filter_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    windows = []
    selected = None
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        original = dev.uni_option
        dev.uni_option = lambda cid, query=False: 7 if cid == 0x4A else original(cid, query)

        def send(name, payload):
            dev.mcu_uni(0x4A, payload, wait=False, timeout=1000)
            window = collect(dev, dev.msg_seq, name)
            windows.append(window)
            if window.acks != [0]:
                raise RuntimeError("CSI control did not acknowledge success exactly once")
            return window

        try:
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)
            send("stop_before", p.request(dev.CHIP, False))
            send("beacon_selector", p.beacon_selector_request(0))
            baseline = send("unfiltered_start", p.request(dev.CHIP, True))
            eligible = baseline.csi.keys() & baseline.beacons.keys()
            if len(eligible) < 2:
                out["filter_skipped"] = "need at least two CSI/beacon sources for discrimination"
            else:
                selected = max(eligible, key=baseline.csi.__getitem__)
                send("add_selected", filter_request(True, selected))
                send("remove_selected", filter_request(False, selected))
                send("readd_selected", filter_request(True, selected))
                send("restart_after_readd", p.request(dev.CHIP, True))
            send("stop_after", p.request(dev.CHIP, False))
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                if selected is not None:
                    dev.mcu_uni(0x4A, filter_request(False, selected), wait=False, timeout=1000)
                dev.mcu_uni(0x4A, p.request(dev.CHIP, False), wait=False, timeout=1000)
            except Exception as exc:
                out["cleanup_stop_error_type"] = type(exc).__name__
            dev.uni_option = original
            dev.bringup(*images, log=lambda *_: None)
            out["cleanup_reload_alive"] = dev.alive()
    out["phases"] = [window.export(selected) for window in windows]
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
