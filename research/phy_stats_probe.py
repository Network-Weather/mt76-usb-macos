#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded MT7961 PHY counters: CE1 GET41, ten aligned snapshot words.

GET offset0 refreshes ten 16-bit PHY statistics, offsets4..36 read the snapshot.
No TX or direct register writes. Optional separate MMIO comparison reads the
five firmware-identified registers; reads may affect counters. No payloads,
addresses, firmware reply tail bytes, or signal calibration claims are exported.
Every phase has a one-second/512-transfer ceiling. Normal reload on every exit.
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
from research.testmode_receiver_probe import rx_setting

COUNTER_NAMES = (
    "cck_pd",
    "ofdm_pd",
    "cck_sfd_error",
    "cck_sig_error",
    "ofdm_tag_error",
    "ofdm_sig_error",
    "cck_fcs_error",
    "ofdm_fcs_error",
    "cck_mdrdy",
    "ofdm_mdrdy",
)
REGISTERS = (0x83081010, 0x8308101C, 0x83081020, 0x83081024, 0x83081014)


def request(offset):
    if type(offset) is not int or offset not in range(0, 40, 4):
        raise ValueError("only ten aligned PHY snapshot offsets")
    return struct.pack("<B3xII", 2, 41, offset)


def scalar(body):
    if len(body) < 8 or struct.unpack_from("<I", body)[0] != 41:
        raise ValueError("missing PHY scalar pair")
    value = struct.unpack_from("<I", body, 4)[0]
    if value > 65535:
        raise ValueError("PHY counter exceeds firmware 16-bit extraction")
    return value


def hardware_snapshot(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned MT7961 PHY registers only")
    words = [dev.rr(address) for address in REGISTERS]
    values = [half for word in words for half in (word & 65535, word >> 16)]
    return dict(zip(COUNTER_NAMES, values, strict=True))


def snapshot(dev):
    values = []
    for offset in range(0, 40, 4):
        raw = dev.mcu_cmd_word(m.MCU_CE_CMD(1), request(offset), timeout=1000)
        values.append(scalar(dev.reply_body(raw)))
    return dict(zip(COUNTER_NAMES, values, strict=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registers", action="store_true")
    args = parser.parse_args()
    out = {
        "tool": "phy_stats_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "register_checks": args.registers,
        "rows": [],
    }
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        def observe(phase):
            row = {"phase": phase}
            out["rows"].append(row)
            if args.registers:
                row["hardware_before"] = hardware_snapshot(dev)
            try:
                row["counters"] = snapshot(dev)
            except (m.McuError, ValueError) as exc:
                row["query_error_type"] = type(exc).__name__
            if args.registers:
                row["hardware_after"] = hardware_snapshot(dev)

        def receive():
            counts = collections.Counter()
            decoder = m.decoder_for(dev)
            deadline = time.monotonic() + 1
            transfers = 0
            while time.monotonic() < deadline and transfers < 512:
                try:
                    raw = bytes(dev.rx_read(timeout=50))
                except usb.core.USBTimeoutError:
                    continue
                transfers += 1
                packet = decoder(raw)
                counts[packet.get("pkt_type_name", "unknown") if packet else "short"] += 1
            return {
                "transfers": transfers,
                "packet_types": dict(counts),
                "limit_reached": transfers == 512,
            }

        try:
            boot()
            observe("normal")
            out["normal_window"] = receive()
            observe("normal_second")
            dev.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
            time.sleep(0.2)
            for selector, value in (
                (1, 0),
                (104, 0),
                (106, 3 << 16),
                (18, 5180000),
                (15, 0),
                (1, 2),
            ):
                dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(selector, value), wait=False)
                time.sleep(0.1)
            observe("rf_rx")
            out["rf_window"] = receive()
            observe("rf_rx_second")
            dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
            time.sleep(0.2)
            observe("stopped")
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                dev.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
            except Exception as exc:
                out["stop_error_type"] = type(exc).__name__
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
