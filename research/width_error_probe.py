#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded 20/40MHz TX with anonymous failed-frame metadata and PHY controls.

At most28 synthetic no-ACK frames. Known volatile counter/filter bits only; restore
original bits and reload both radios. No power, calibration or NVM changes.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import usb.core

import mt7921u as m
from research import phy_tx_probe as p
from research.error_frame_probe import failed_metadata, mac_fcs_sample, rfcr_word
from research.normal_phy_counter_probe import CONTROL, MASK, control_value
from research.phy_stats_probe import hardware_snapshot

PLAN = (
    ("ht20_before", 0x488, 20),
    ("ht15_error_control", 0x48F, 20),
    ("ht40", 0x488, 40),
    ("ht20_after", 0x488, 20),
    ("he20_before", 0x600, 20),
    ("he40", 0x600, 40),
    ("he20_after", 0x600, 20),
)
FREQUENCY_PLAN = (
    ("ht20_primary_before", 0x488, 20),
    ("ht40_primary", 0x488, 40),
    ("ht40_center", 0x488, 40),
    ("ht40_secondary", 0x488, 40),
    ("ht40_primary_repeat", 0x488, 40),
    ("ht20_primary_after", 0x488, 20),
)
RX_CHANNELS = (6, 6, 8, 10, 6, 6)
SECONDARY_PLAN = (
    ("ht20_primary_before", 0x488, 20),
    ("ht20_secondary_before", 0x488, 20),
    ("ht40_secondary", 0x488, 40),
    ("ht20_secondary_after", 0x488, 20),
    ("ht40_secondary_repeat", 0x488, 40),
    ("ht20_primary_after", 0x488, 20),
)
SECONDARY_CHANNELS = (6, 10, 10, 10, 10, 6)
RXPATH_PLAN = (
    ("ht20_before", 0x488, 20),
    ("ht40_before_rxpath", 0x488, 40),
    ("ht40_after_rxpath", 0x488, 40),
    ("ht20_after", 0x488, 20),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--enable-error-capture", action="store_true")
    parser.add_argument("--enable-counters", action="store_true")
    parser.add_argument(
        "--suite", choices=("width", "frequency", "secondary", "rxpath"), default="width"
    )
    args = parser.parse_args()
    if not all(
        (args.acknowledge_experimental_transmit, args.enable_error_capture, args.enable_counters)
    ):
        parser.error("explicit TX, error-capture and counter-write opt-ins required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "bounded no-ACK MT7925 probes with TX configured primary6/center8/40MHz; MT7961 FCS filter open and known PHY counter enable; no power changes",
        "suite": args.suite,
        "maximum_submissions": {"width": 28, "frequency": 24, "secondary": 24, "rxpath": 16}[
            args.suite
        ],
        "submitted": 0,
        "phases": [],
    }
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        rx, tx = radios
        images = [m.load_firmware(d.CHIP, m.firmware_dir()) for d in radios]
        out["firmware_sha256"] = {
            d.CHIP: [hashlib.sha256(b).hexdigest() for b in image]
            for d, image in zip(radios, images, strict=True)
        }
        original_rfcr = None
        original_counter = None
        marker = b"\xdd\x0c\x02NW\x01" + os.urandom(8)

        def boot(i, wide):
            d = radios[i]
            d.bringup(*images[i], log=lambda *_: None)
            d.set_monitor_mode()
            d.set_sniffer(True)
            d.tune("2.4GHz", 6, 8 if wide else 6, 40 if wide else 20)

        try:
            for i in (0, 1):
                boot(i, True)
            original_rfcr = rfcr_word(rx)
            out["rfcr_before"] = hex(original_rfcr)
            rx.set_rxfilter(0, m.MT7921_FIF_BIT_CLR, 2)
            time.sleep(0.05)
            out["rfcr_open"] = hex(rfcr_word(rx))
            if rfcr_word(rx) & 2:
                raise ValueError("FCS filter did not open")
            original_counter = rx.rr(CONTROL)
            rx.wr(CONTROL, control_value(original_counter, False))
            rx.wr(CONTROL, control_value(rx.rr(CONTROL), True))
            out["original_counter_bits"] = original_counter & MASK
            out["enabled_counter_bits"] = rx.rr(CONTROL) & MASK
            if out["enabled_counter_bits"] != 0xA00:
                raise ValueError("PHY counter enable readback failed")
            decode = m.decoder_for(rx)
            plan = {
                "width": PLAN,
                "frequency": FREQUENCY_PLAN,
                "secondary": SECONDARY_PLAN,
                "rxpath": RXPATH_PLAN,
            }[args.suite]
            previous_rx_channel = None
            for phase, (name, code, width) in enumerate(plan):
                channels = SECONDARY_CHANNELS if args.suite == "secondary" else RX_CHANNELS
                rx_channel = channels[phase] if args.suite in ("frequency", "secondary") else 6
                retune = args.suite == "frequency" or (
                    args.suite == "secondary" and rx_channel != previous_rx_channel
                )
                if retune:
                    rx.tune("2.4GHz", rx_channel, rx_channel, 20)
                    rx.set_rxfilter(0, m.MT7921_FIF_BIT_CLR, 2)
                    time.sleep(0.05)
                    if rfcr_word(rx) & 2 or rx.rr(CONTROL) & MASK != 0xA00:
                        raise ValueError("receiver control changed on retune")
                previous_rx_channel = rx_channel
                if args.suite == "rxpath" and phase == 2:
                    rx.set_chan_info(
                        control_ch=6,
                        center_ch=8,
                        bw=m.WIDTH_TO_CMD_CBW[40],
                        band=0,
                        cmd_ext=m.MCU_EXT_CMD_SET_RX_PATH,
                    )
                    time.sleep(0.05)
                    out["rxpath_sent"] = True
                    if rfcr_word(rx) & 2 or rx.rr(CONTROL) & MASK != 0xA00:
                        raise ValueError("receiver control changed after RX_PATH")
                he = code == 0x600
                p.program_rate(tx, code, ltf=int(he), ldpc=int(he))
                current = {
                    "rx_channel": rx_channel,
                    "rx_width_mhz": 20 if args.suite in ("frequency", "secondary") else 40,
                    "receiver_retuned": retune,
                    "name": name,
                    "rate_code": code,
                    "tx_width_mhz": width,
                    "ltf": int(he),
                    "ldpc": int(he),
                    "windows": [],
                }
                out["phases"].append(current)
                for i in range(4):
                    sequence = 4 * phase + i
                    frame = p.c3.controlled_frame(sequence) + marker
                    row = {
                        "sequence": sequence,
                        "before": mac_fcs_sample(rx),
                        "exact_good": False,
                        "good_phy": [],
                        "failed_metadata": [],
                        "tx_status": [],
                    }
                    current["windows"].append(row)
                    row["phy_before"] = hardware_snapshot(rx)
                    body = (
                        p.descriptor(tx, frame, sequence, code, fixed_bw=True, width_mhz=width)
                        + frame
                    )
                    wire = struct.pack("<I", len(body)) + body
                    wire += bytes((-len(wire)) % 4 + 4)
                    tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
                    out["submitted"] += 1
                    deadline, transfers = time.monotonic() + 0.1, 0
                    while time.monotonic() < deadline and transfers < 256:
                        for radio in (rx, tx):
                            try:
                                raw = bytes(radio.rx_read(timeout=1))
                            except usb.core.USBTimeoutError:
                                continue
                            transfers += 1
                            if radio is tx:
                                if (
                                    len(raw) >= 4
                                    and (struct.unpack_from("<I", raw)[0] >> 27) & 31 == 0
                                ):
                                    row["tx_status"].extend(
                                        s
                                        for s in p.c3.tx_status(raw, include_timing=True)
                                        if s["sequence"] == sequence and s["pid"] == 3
                                    )
                                continue
                            decoded = decode(raw)
                            meta = failed_metadata(decoded)
                            if meta:
                                row["failed_metadata"].append(meta)
                            if (
                                decoded
                                and decoded.get("frame") == frame
                                and not decoded.get("fcs_err")
                            ):
                                row["exact_good"] = True
                                row["good_phy"].append(
                                    {
                                        k: decoded.get("phy", {}).get(k)
                                        for k in ("mode_name", "mcs", "nss", "bw_mhz", "ldpc", "gi")
                                    }
                                )
                    row["after"] = mac_fcs_sample(rx)
                    row["phy_after"] = hardware_snapshot(rx)
                    row["transfer_limit_reached"] = transfers >= 256
                    time.sleep(0.05)
            out["alive_after"] = [d.alive() for d in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if original_counter is not None:
                try:
                    value = rx.rr(CONTROL)
                    control_value(value, False)
                    rx.wr(CONTROL, (value & ~MASK) | (original_counter & MASK))
                    out["counter_bits_restored"] = (rx.rr(CONTROL) & MASK) == (
                        original_counter & MASK
                    )
                except Exception as exc:
                    out["counter_restore_error_type"] = type(exc).__name__
            if original_rfcr is not None:
                try:
                    rx.set_rxfilter(
                        0, m.MT7921_FIF_BIT_SET if original_rfcr & 2 else m.MT7921_FIF_BIT_CLR, 2
                    )
                    time.sleep(0.05)
                    out["rfcr_fcs_bit_restored"] = (rfcr_word(rx) & 2) == (original_rfcr & 2)
                except Exception as exc:
                    out["restore_error_type"] = type(exc).__name__
            out["cleanup_reload_alive"] = []
            for i in (0, 1):
                try:
                    boot(i, False)
                    out["cleanup_reload_alive"].append(radios[i].alive())
                except Exception as exc:
                    out["cleanup_reload_alive"].append(False)
                    out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))

    return int(
        "error_type" in out
        or not out.get("rfcr_fcs_bit_restored")
        or not out.get("counter_bits_restored")
        or not all(out.get("alive_after", [False]))
        or not all(out.get("cleanup_reload_alive", [False]))
    )


if __name__ == "__main__":
    raise SystemExit(main())
