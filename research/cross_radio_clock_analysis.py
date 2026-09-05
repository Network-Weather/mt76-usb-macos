#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Compare exact own-frame MT7961 RXD and MT7925 TXS clocks offline.

Tests packet-duration dependence, not an absolute timestamp latch, calibrated
clock synchronization or propagation time. Both clocks have an unknown origin.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.tx_timing_analysis import analyze as analyze_tx
from research.tx_timing_analysis import ppdu_airtime_us, slope, unwrap


def analyze(trial):
    if trial.get("suite") != "cck":
        raise ValueError("bounded CCK/OFDM rate control required")
    # Reuse complete, unique, single-attempt format0 TX status validation.
    analyze_tx(trial)
    tx = next(r for r in trial["radios"] if r["chip"] == "mt7925")
    receivers = [r for r in trial["radios"] if r["chip"] == "mt7921"]
    if len(receivers) != 1:
        raise ValueError("one MT7961 receiver required")
    records = receivers[0].get("own_rx_timing", [])
    if not 2 <= len(records) <= trial["submitted"]:
        raise ValueError("at least two bounded own RX timestamps required")
    sequences = [r["sequence"] for r in records]
    if any(type(s) is not int or not 0 <= s < trial["submitted"] for s in sequences):
        raise ValueError("invalid own RX sequence")
    if len(set(sequences)) != len(sequences):
        raise ValueError("duplicate own RX sequence")
    rx = sorted(records, key=lambda r: r["sequence"])
    statuses = {r["fields"]["sequence"]: r["fields"] for r in tx["tx_status"]}
    selected = [statuses[r["sequence"]] for r in rx]
    tx_time = unwrap([r["timestamp_raw"] for r in selected], 32)
    rx_time = unwrap([r["rxd_timestamp_raw"] for r in rx], 32)
    size = trial["frame_bytes_without_fcs"]
    offsets, raw_deltas, corrected_rx, rates = [], [], [], {}
    for row, t, r in zip(selected, tx_time, rx_time, strict=True):
        duration = ppdu_airtime_us(row["rate_raw"], size)
        delta = r - t
        offset = delta - duration
        raw_deltas.append(delta)
        offsets.append(offset)
        corrected_rx.append(r - duration)
        group = rates.setdefault(
            str(row["rate_raw"]), {"airtime": duration, "delta": [], "offset": []}
        )
        group["delta"].append(delta)
        group["offset"].append(offset)
    return {
        "frame_bytes_without_fcs": size,
        "matched_frames": len(rx),
        "submitted_frames": trial["submitted"],
        "formula": "RXD_timestamp - TXS_timestamp - modeled_PPDU_airtime",
        "assumed_timestamp_tick_us": 1,
        "raw_clock_difference_range_ticks": [min(raw_deltas), max(raw_deltas)],
        "per_boot_offset_range_us": [min(offsets), max(offsets)],
        "per_boot_offset_spread_us": max(offsets) - min(offsets),
        "airtime_corrected_rx_per_tx_tick_fit": slope(tx_time, corrected_rx),
        "rates": {
            rate: {
                "matched_frames": len(g["delta"]),
                "modeled_ppdu_airtime_us": g["airtime"],
                "raw_clock_difference_median_ticks": statistics.median(g["delta"]),
                "corrected_offset_range_us": [min(g["offset"]), max(g["offset"])],
            }
            for rate, g in rates.items()
        },
        "absolute_latch_point_or_propagation_time_validated": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(json.loads(args.trial.read_text())), indent=2))
