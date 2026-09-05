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
Only stop, frequency 5180000 kHz, 20 MHz, and RX-start writes are permitted.
"""

import argparse
import contextlib
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mt7921u as m
from research import mt7925_tx_probe as txp
from research.station_testmode_probe import at_query, summarize


def rx_setting(selector, value):
    if (selector, value) not in ((1, 0), (1, 2), (18, 5180000), (15, 0)):
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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = p.parse_args()
    if not args.acknowledge_experimental_transmit:
        p.error("explicit TX acknowledgment required")
    out = {
        "tool": "testmode_receiver_probe",
        "date_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "channel": 36,
        "width_mhz": 20,
        "submitted": 0,
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
            rx.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
            time.sleep(0.2)
            for selector, value in ((1, 0), (18, 5180000), (15, 0), (1, 2)):
                rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(selector, value), wait=False)
                time.sleep(0.1)
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
                        seq = out["submitted"]
                        frame = txp.controlled_frame(seq)
                        body = txp.build_txwi(frame, seq, power, disable_mat=True) + frame
                        wire = struct.pack("<I", len(body)) + body
                        wire += bytes((-len(wire)) % 4 + 4)
                        tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                        out["submitted"] += 1
                        time.sleep(0.05)
                out["phases"].append(
                    {
                        "name": name,
                        "power_code": power,
                        "elapsed_s": round(time.monotonic() - start, 4),
                        "stats": read_stats(rx),
                    }
                )
            rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
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
