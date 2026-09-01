#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Capture one channel to a radiotap pcap that Wireshark can read.

Passive receive only. Once frames land in a pcap, every existing 802.11 tool
works on them and our decode can be checked against an independent one.

Usage: sniff_to_pcap.py <channel> <duration_seconds> [out.pcap] [band]
       band is 2.4GHz | 5GHz | 6GHz (default 2.4GHz)

Firmware is loaded from $MT7921_FW_DIR, defaulting to <repo>/firmware.
"""

import argparse
import os
import struct
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

FW_DIR = os.environ.get("MT7921_FW_DIR", os.path.join(REPO_ROOT, "firmware"))
CHAN_BAND = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}

LINKTYPE_IEEE802_11_RADIOTAP = 127

# radiotap "present" bits we emit, in ascending bit order (required).
RT_FLAGS = 1 << 1
RT_CHANNEL = 1 << 3
RT_DBM_ANTSIGNAL = 1 << 5

RT_FLAG_BADFCS = 0x40

CH_FLAG_CCK = 0x0020
CH_FLAG_OFDM = 0x0040
CH_FLAG_2GHZ = 0x0080
CH_FLAG_5GHZ = 0x0100


def freq_for(band: str, chan: int) -> int:
    if band == "2.4GHz":
        return 2484 if chan == 14 else 2407 + chan * 5
    if band == "5GHz":
        return 5000 + chan * 5
    if band == "6GHz":
        return 5950 + chan * 5
    raise ValueError(f"unknown band {band!r}")


def radiotap(freq: int, band: str, rssi, bad_fcs: bool) -> bytes:
    """An 8-byte header plus flags, channel and signal, correctly aligned."""
    present = RT_FLAGS | RT_CHANNEL | RT_DBM_ANTSIGNAL
    body = b""
    body += struct.pack("<B", RT_FLAG_BADFCS if bad_fcs else 0)  # offset 8
    body += b"\x00"  # pad to align 2
    ch_flags = CH_FLAG_2GHZ | CH_FLAG_CCK if band == "2.4GHz" else CH_FLAG_5GHZ | CH_FLAG_OFDM
    body += struct.pack("<HH", freq, ch_flags)  # offsets 10..13
    body += struct.pack("<b", rssi if rssi is not None else -128)  # offset 14
    hdr = struct.pack("<BBHI", 0, 0, 8 + len(body), present)
    return hdr + body


def pcap_header(snaplen: int = 65535) -> bytes:
    return struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, snaplen, LINKTYPE_IEEE802_11_RADIOTAP)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=int)
    parser.add_argument("duration", type=float, help="capture duration in seconds")
    parser.add_argument("output", nargs="?", default="capture.pcap")
    parser.add_argument("band", nargs="?", choices=sorted(CHAN_BAND), default="2.4GHz")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    args = parser.parse_args()
    if not 1 <= args.channel <= 255:
        parser.error("channel must be between 1 and 255")
    if not 0 < args.duration <= 86400:
        parser.error("duration must be greater than 0 and at most 86400 seconds")
    chan = args.channel
    secs = args.duration
    out = args.output
    band = args.band

    with open(os.path.join(FW_DIR, "WIFI_MT7961_patch_mcu_1_2_hdr.bin"), "rb") as fh:
        patch = fh.read()
    with open(os.path.join(FW_DIR, "WIFI_RAM_CODE_MT7961_1.bin"), "rb") as fh:
        ram = fh.read()

    mode = "wb" if args.overwrite else "xb"
    with m.Mt7921uDevice() as dev, open(out, mode) as fh:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        dev.set_chan_info(control_ch=chan, center_ch=chan, bw=m.CMD_CBW_20MHZ, band=CHAN_BAND[band])
        dev.config_sniffer(control_ch=chan, center_ch=chan, band_name=band, bw=m.SNIFFER_BW_20)
        time.sleep(0.2)
        fh.write(pcap_header())
        print(f"channel {chan} ({band}), {secs:g}s -> {out}")

        freq = freq_for(band, chan)
        n = written = 0
        deadline = time.monotonic() + secs
        while time.monotonic() < deadline:
            try:
                raw = bytes(dev.rx_read(timeout=500))
            except usb.core.USBError:
                continue
            n += 1
            d = rxd.decode(raw)
            if d is None:
                continue
            frame = d.get("frame")
            if not frame or len(frame) < 10:
                continue
            # The descriptor's channel is authoritative; a hop may be in flight.
            f = freq
            if d.get("band") and d.get("channel"):
                f = freq_for(d["band"], d["channel"])
            rt = radiotap(f, d.get("band", band), d.get("rssi"), bool(d.get("fcs_err")))
            pkt = rt + frame
            now = time.time()
            fh.write(struct.pack("<IIII", int(now), int((now % 1) * 1e6), len(pkt), len(pkt)))
            fh.write(pkt)
            written += 1
        print(f"{n} transfers, {written} frames written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
