#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Does MT7961's RF-test receiver report live changes under bounded Wi-Fi TX?

Starts RX only on MT7961, never its factory transmitter. Sends 36 synthetic no-ACK
OFDM6 probes from MT7925 on channel 36/20 MHz at 50 ms spacing, in 0/-16/0 power-code
phases bracketed by quiet dwells. No identifiers or frame contents are emitted.
Counters include ambient traffic; they are not synthetic delivery counts. Signal
words remain raw. Reload both firmware images on every exit after setup.

Protocol facts: pinned MediaTek station source documented in STATION_TESTMODE.md;
gl_hook_api.c MT_ATESetChannel says kHz; MT_ATEStartRX sets function 1 to 2.
Only stop, frequency 5180000 kHz, 20 MHz, RX-path/band selection, and RX-start
writes are permitted. Optional monitor validation adds 12 control packets (48 total).
"""

import argparse
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

import mt7921u as m
from research import mt7925_tx_probe as txp
from research.phy_tx_probe import capture
from research.station_testmode_probe import at_query, summarize


def rx_setting(selector, value):
    if (selector, value) not in (
        (1, 0),
        (1, 2),
        (18, 5180000),
        (15, 0),
        (104, 0),
        (106, 1 << 16),
        (106, 2 << 16),
        (106, 3 << 16),
        (71, 0),
        (72, 0),
        (73, 0),
    ):
        raise ValueError("only fixed-channel receive settings allowed")
    return struct.pack("<B3xII", 1, selector, value)


def read_stats(dev):
    out = {}
    for selector in (34, 35, 46, 50):
        raw = dev.mcu_cmd_word(m.MCU_CE_CMD(1), at_query(selector), timeout=1000)
        value = summarize(dev.reply_body(raw), selector)
        if "value_u32" not in value:
            raise RuntimeError("missing echoed scalar query reply")
        out[str(selector)] = value["value_u32"]
    return out


def read_settings(dev):
    out = {}
    for selector in (15, 18, 71, 72, 73, 104, 106, 32):
        raw = dev.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 2, selector, 0), timeout=1000)
        out[str(selector)] = summarize(dev.reply_body(raw), selector)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--acknowledge-experimental-transmit", action="store_true")
    p.add_argument(
        "--select-band", action="store_true", help="select band 0 without an RX-path write"
    )
    p.add_argument(
        "--rx-path", type=int, choices=(1, 2, 3), help="RX antenna mask, encoded in high 16 bits"
    )
    p.add_argument(
        "--engineering-bw", action="store_true", help="also set CBW/DBW/primary to 20 MHz"
    )
    p.add_argument(
        "--verify-monitor-control",
        action="store_true",
        help="12 exact-frame control packets before test mode",
    )
    args = p.parse_args()
    if not args.acknowledge_experimental_transmit:
        p.error("explicit TX acknowledgment required")
    out = {
        "tool": "testmode_receiver_probe",
        "date_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "channel": 36,
        "width_mhz": 20,
        "submitted": 0,
        "control_submitted": 0,
        "rx_path": args.rx_path,
        "engineering_bw": args.engineering_bw,
        "select_band": args.select_band,
        "phases": [],
    }
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("5GHz", 36, 36, 20)

        for i in range(2):
            boot(i)
        rx, tx = radios
        try:
            txp.set_ofdm_rate(tx)

            def transmit(seq, power):
                frame = txp.controlled_frame(seq)
                body = txp.build_txwi(frame, seq, power, disable_mat=True) + frame
                wire = struct.pack("<I", len(body)) + body
                wire += bytes((-len(wire)) % 4 + 4)
                tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                time.sleep(0.05)

            if args.verify_monitor_control:
                ready, stop = threading.Event(), threading.Event()
                expected = {seq: txp.controlled_frame(seq) for seq in range(12)}
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    job = pool.submit(capture, rx, expected, 12, ready, stop)
                    try:
                        if not ready.wait(5):
                            raise RuntimeError("monitor control not ready")
                        for seq in range(12):
                            transmit(seq, 0)
                            out["control_submitted"] += 1
                        time.sleep(0.2)
                    finally:
                        stop.set()
                    out["monitor_control"] = job.result(timeout=3)
                if not out["monitor_control"]["phases"][0]["unique_exact_frames"]:
                    raise RuntimeError("no independent monitor control decode")
            rx.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
            time.sleep(0.2)
            settings = [(1, 0)]
            if args.select_band or args.rx_path is not None:
                settings += [(104, 0)]
            if args.rx_path is not None:
                # Pinned operation_gen4m.c mt_op_set_rx_path: band first,
                # then RX mask in high 16 bits (not an unshifted antenna mask).
                settings += [(106, args.rx_path << 16)]
            settings += [(18, 5180000), (15, 0)]
            if args.engineering_bw:
                settings += [(71, 0), (72, 0), (73, 0)]
            settings += [(1, 2)]
            out["setting_requests"] = settings
            for selector, value in settings:
                rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(selector, value), wait=False)
                time.sleep(0.1)
            if args.rx_path is not None or args.engineering_bw or args.select_band:
                out["setting_queries"] = read_settings(rx)
            out["initial"] = read_stats(rx)
            for name, power in (
                ("quiet_before", None),
                ("tx_0", 0),
                ("tx_minus16", -16),
                ("tx_0_return", 0),
                ("quiet_after", None),
            ):
                start = time.monotonic()
                if power is None:
                    time.sleep(0.6)
                else:
                    for _ in range(12):
                        seq = out["control_submitted"] + out["submitted"]
                        transmit(seq, power)
                        out["submitted"] += 1
                out["phases"].append(
                    {
                        "name": name,
                        "power_code": power,
                        "elapsed_s": round(time.monotonic() - start, 4),
                        "stats": read_stats(rx),
                    }
                )
            rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
            time.sleep(0.2)
            out["stopped_initial"] = read_stats(rx)
            time.sleep(0.6)
            out["stopped_after_dwell"] = read_stats(rx)
            out["alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            out["cleanup"] = []
            for i in range(2):
                try:
                    boot(i)
                    out["cleanup"].append({"chip": radios[i].CHIP, "alive": radios[i].alive()})
                except Exception as exc:
                    out["cleanup"].append(
                        {"chip": radios[i].CHIP, "error_type": type(exc).__name__}
                    )
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not all(row.get("alive") for row in out["cleanup"]))


if __name__ == "__main__":
    raise SystemExit(main())
