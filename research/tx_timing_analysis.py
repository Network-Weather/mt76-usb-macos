#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Offline consistency analysis of bounded MT7925 CCK-suite TXS timing.

Tests a1us timestamp /32us front-time-and-delay hypothesis against host time and
modeled PPDU airtime. No absolute clock, ranging or contention calibration.
"""

import argparse
import itertools
import json
import math
import statistics
from pathlib import Path


def ppdu_airtime_us(rate, frame_bytes):
    """CCK/OFDM6 preamble+payload; excludes SIFS and ERP signal extension.

    MAC bytes exclude hardware-added FCS. This is a model, not measured airtime.
    """
    if type(frame_bytes) is not int or not 1 <= frame_bytes <= 512:
        raise ValueError("bounded frame length required")
    if type(rate) is not int or rate not in (0, 1, 2, 3, 5, 7, 0x4B):
        raise ValueError("only bounded CCK or OFDM6")
    bits = 8 * (frame_bytes + 4)
    if rate == 0x4B:
        return 20 + 4 * math.ceil((16 + bits + 6) / 24)
    preamble = 96 if rate in (5, 7) else 192
    return preamble + math.ceil(bits / (1, 2, 5.5, 11)[rate & 3])


def unwrap(values, bits):
    limit = 1 << bits
    if not values or any(type(v) is not int or not 0 <= v < limit for v in values):
        raise ValueError("invalid clock words")
    out = [values[0]]
    for before, after in itertools.pairwise(values):
        delta = (after - before) % limit
        if not 0 < delta < limit // 2:
            raise ValueError("ambiguous or nonforward clock")
        out.append(out[-1] + delta)
    return out


def slope(x, y):
    mx, my = statistics.mean(x), statistics.mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / sum(
        (a - mx) ** 2 for a in x
    )


def analyze(trial, frame_bytes=None):
    if (
        trial.get("tool") != "phy_tx_probe"
        or trial.get("transmitter") != "mt7925"
        or trial.get("suite") not in ("cck", "preamble", "timing-burst")
        or trial.get("tx_timing") is not True
    ):
        raise ValueError("bounded MT7925 CCK timing trial required")
    size = trial.get("frame_bytes_without_fcs") if frame_bytes is None else frame_bytes
    if frame_bytes is not None and trial.get("frame_bytes_without_fcs", frame_bytes) != frame_bytes:
        raise ValueError("frame length override conflicts with recorded length")
    ppdu_airtime_us(0, size)
    count = trial["submitted"]
    if type(count) is not int or not 2 <= count <= 60:
        raise ValueError("bounded submission count required")
    radios = [r for r in trial["radios"] if r["chip"] == "mt7925"]
    if len(radios) != 1:
        raise ValueError("one transmitter required")
    records = radios[0]["tx_status"]
    if len(records) != count or any(r["count"] != 1 for r in records):
        raise ValueError("one status per submission required")
    rows = sorted((r["fields"] for r in records), key=lambda r: r["sequence"])
    if [r["sequence"] for r in rows] != list(range(count)):
        raise ValueError("unique complete sequence range required")
    for row in rows:
        if (
            row["pid"] != 3
            or row["format"] != 0
            or row["tx_count_format0"] != 1
            or row["error_bits_16_22"] != 0
            or row["rate_stbc"]
        ):
            raise ValueError("single-attempt format0 control statuses required")
        if type(row["tx_delay_raw"]) is not int or not 0 <= row["tx_delay_raw"] <= 65535:
            raise ValueError("invalid delay word")
    host = [r["status_received_host_seconds"] for r in rows]
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in host):
        raise ValueError("finite host timestamps required")
    if any(b <= a for a, b in itertools.pairwise(host)):
        raise ValueError("forward host timestamps required")
    stamps = unwrap([r["timestamp_raw"] for r in rows], 32)
    front = unwrap([r["front_time_raw_format0"] for r in rows], 25)
    groups = {}
    offsets = []
    for row, timestamp, start in zip(rows, stamps, front, strict=True):
        airtime = ppdu_airtime_us(row["rate_raw"], size)
        value = 32 * (start + row["tx_delay_raw"]) - timestamp - airtime
        offsets.append(value)
        group = groups.setdefault(
            str(row["rate_raw"]), {"delay": [], "offset": [], "airtime": airtime}
        )
        group["delay"].append(row["tx_delay_raw"])
        group["offset"].append(value)
    result = {
        "frame_bytes_without_fcs": size,
        "statuses": count,
        "timestamp_ticks_per_host_second_fit": slope(host, stamps),
        "front_ticks_per_host_second_fit": slope(host, front),
        "assumed_timestamp_tick_us": 1,
        "assumed_front_and_delay_tick_us": 32,
        "formula": "32*(front+delay)-timestamp-modeled_PPDU_airtime",
        "model_excludes_sifs_and_erp_signal_extension": True,
        "per_boot_offset_range_us": [min(offsets), max(offsets)],
        "per_boot_offset_spread_us": max(offsets) - min(offsets),
        "rates": {
            rate: {
                "count": len(g["delay"]),
                "modeled_ppdu_airtime_us": g["airtime"],
                "delay_ticks_range": [min(g["delay"]), max(g["delay"])],
                "delay_ticks_median": statistics.median(g["delay"]),
                "offset_range_us": [min(g["offset"]), max(g["offset"])],
            }
            for rate, g in groups.items()
        },
        "calibrated_clock_or_contention_measurement": False,
    }
    if trial["suite"] == "timing-burst":
        n = trial["per_phase"]
        if type(n) is not int or not 1 <= n <= 10 or count != 3 * n:
            raise ValueError("bounded three-phase burst geometry required")
        submitted = trial["host_submissions"]
        if len(submitted) != count or [r["sequence"] for r in submitted] != list(range(count)):
            raise ValueError("complete host submission sequence required")
        for row in submitted:
            if any(
                type(row[k]) not in (int, float) or not math.isfinite(row[k]) or row[k] < 0
                for k in ("start_seconds", "call_seconds")
            ):
                raise ValueError("valid host submission timing required")
        if any(b["start_seconds"] <= a["start_seconds"] for a, b in itertools.pairwise(submitted)):
            raise ValueError("forward host submissions required")
        first, last = n, 2 * n - 1
        result["burst"] = {
            "packets": n,
            "host_submission_window_us": 1e6
            * (
                submitted[last]["start_seconds"]
                + submitted[last]["call_seconds"]
                - submitted[first]["start_seconds"]
            ),
            "front_through_last_delay_span_ticks": front[last]
            + rows[last]["tx_delay_raw"]
            - front[first],
            "timestamp_span_ticks": stamps[last] - stamps[first],
            "per_frame_delay_ticks": [r["tx_delay_raw"] for r in rows[first : last + 1]],
            "front_step_minus_previous_delay_ticks": [
                front[i + 1] - front[i] - rows[i]["tx_delay_raw"] for i in range(first, last)
            ],
            "sum_modeled_airtime_us": sum(
                ppdu_airtime_us(r["rate_raw"], size) for r in rows[first : last + 1]
            ),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial", type=Path)
    parser.add_argument("--frame-bytes", type=int, help="explicit length for older probe output")
    args = parser.parse_args()
    print(json.dumps(analyze(json.loads(args.trial.read_text()), args.frame_bytes), indent=2))


if __name__ == "__main__":
    main()
