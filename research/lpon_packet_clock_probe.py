#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded PHY probe with read-only LPON clock brackets; no ambient records."""

import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m
from research import mt7925_tx_probe as c3
from research import phy_tx_probe as probe
from research.lpon_clock import read_counter

original_capture = probe.capture


def capture(dev, expected, *args, **kwargs):
    samples = []
    decode = m.decoder_for(dev)

    class Reader:
        def __getattr__(self, key):
            return getattr(dev, key)

        def rx_read(self, *a, **k):
            host_before = time.monotonic()
            before = read_counter(dev)["value_raw"]
            raw = dev.rx_read(*a, **k)
            after = read_counter(dev)["value_raw"]
            host_after = time.monotonic()
            decoded = decode(bytes(raw))
            if not decoded:
                return raw
            packet_clocks = []
            if decoded["pkt_type"] == 0 and dev.CHIP == m.CHIP_MT7925:
                for status in c3.tx_status(bytes(raw), include_timing=True):
                    if status.get("pid") == 3 and status.get("sequence") in expected:
                        packet_clocks.append(
                            {
                                "kind": "TXS",
                                "sequence": status["sequence"],
                                "timestamp_raw": status["timestamp_raw"],
                            }
                        )
            frame = decoded.get("frame", b"")
            if len(frame) >= 24 and not decoded.get("fcs_err"):
                seq = struct.unpack_from("<H", frame, 22)[0] >> 4
                if expected.get(seq) == frame:
                    packet_clocks.append(
                        {"kind": "RXD", "sequence": seq, "timestamp_raw": decoded.get("timestamp")}
                    )
            if packet_clocks:
                samples.append(
                    {
                        "counter_before_raw": before,
                        "counter_after_raw": after,
                        "host_before_seconds": host_before,
                        "host_after_seconds": host_after,
                        "packet_clocks": packet_clocks,
                    }
                )
            return raw

    result = original_capture(Reader(), expected, *args, **kwargs)
    result["lpon_packet_clock_brackets"] = samples
    return result


def main():
    if "--tx-timing" not in sys.argv:
        raise SystemExit("--tx-timing is required for the clock comparison")
    probe.capture = capture
    try:
        return probe.main()
    finally:
        probe.capture = original_capture


if __name__ == "__main__":
    raise SystemExit(main())
