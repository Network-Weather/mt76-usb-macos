#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Separate MT7925 MIB counters with a bounded, controlled Wi-Fi burst.

An MT7921/MT7961-class adapter sends directed Probe Requests for a synthetic,
nonexistent SSID at the existing injector's fixed 1 Mb/s CCK rate. An MT7925 adapter passively captures
the burst and atomically samples selected UNI MIB counters. The sequence alternates
baseline and injected phases so ambient drift is visible.

No observed SSID, BSSID, payload, or real device address is written to output.
The transmitted identifier and source address are fixed synthetic test values.
Transmission is refused without --acknowledge-experimental-transmit and capped
at 300 frames.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mcu_stats as mcs  # noqa: E402
import mib_survey as legacy_survey  # noqa: E402
import mt7925_mib_characterize as mib  # noqa: E402
import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

MAX_INJECTED_FRAMES = 300
DEFAULT_OFFSETS = (0, 2, 11, 12, 13, 17, 18, 19, 20)
READ_TIMEOUT_MS = 200
SYNTHETIC_SRC = bytes.fromhex("02005e105ada")
SYNTHETIC_SRC_STR = ":".join(f"{b:02x}" for b in SYNTHETIC_SRC)
SYNTHETIC_SSID = b"mt76-mib-cal"
INJECT_RATE_MBPS = 1.0
FCS_BYTES = 4


def expected_airtime_us(frame_len: int, count: int) -> float:
    """Airtime of `count` injected frames, including the hardware-appended FCS."""
    one_us = rxd.airtime_us(frame_len + FCS_BYTES, rxd.MT_PHY_TYPE_CCK, INJECT_RATE_MBPS)
    return (one_us or 0.0) * count


def legacy_sample(dev) -> tuple[dict[str, int | None], float]:
    """Read the MT7921 counters whose semantics are already established."""
    opened = time.monotonic()
    values = {
        "p_cca_time_us": legacy_survey.read_mcu_offset(dev, mcs.MIB_PRIMARY_CCA_TIME),
        "cca_nav_tx_time_us": legacy_survey.read_mcu_offset(dev, 14),
    }
    closed = time.monotonic()
    return values, (opened + closed) / 2


def legacy_result(before, after, before_at: float, after_at: float) -> dict:
    elapsed_us = (after_at - before_at) * 1e6
    values = {}
    for name in before:
        first = before[name]
        last = after[name]
        delta = None if first is None or last is None else (last - first) % (1 << 32)
        values[name] = {
            "delta": delta,
            "fraction_if_us": (
                None if delta is None or elapsed_us <= 0 else round(delta / elapsed_us, 6)
            ),
        }
    return {"sample_interval_us": round(elapsed_us), "values": values}


def counter_result(before, after, before_at: float, after_at: float) -> dict:
    elapsed_us = (after_at - before_at) * 1e6
    out = {}
    for offs in before:
        first = before[offs]
        last = after[offs]
        delta = None if first is None or last is None else last - first
        out[str(offs)] = {
            "delta": delta,
            "fraction_if_us": (
                None if delta is None or elapsed_us <= 0 else round(delta / elapsed_us, 6)
            ),
        }
    return {"sample_interval_us": round(elapsed_us), "values": out}


def receive_phase(
    dev,
    label: str,
    seconds: float,
    offsets: tuple[int, ...],
    ready: threading.Barrier,
    result: dict,
    failures: list[str],
) -> None:
    try:
        dropped_before = getattr(dev, "mcu_wait_dropped_frames", 0)
        before, before_at = mib.sample(dev, offsets, 0)
        decode = m.decoder_for(dev)
        aggregates = rxd.AggregationTracker()
        decoded_us = 0.0
        frames = 0
        injected_seen = 0
        usb_errors = 0
        timeouts = 0

        def bill(done) -> float:
            return sum(aggregate.airtime_us() or 0.0 for aggregate in done)

        # Counter reads finish on both radios before either starts its interval. This is the
        # same rendezvous rule as cross_measure.py: synchronous MCU reads after release can
        # push the tail of a short burst outside the receiver's window without failing loudly.
        ready.wait(timeout=10)
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            try:
                raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
            except usb.core.USBTimeoutError:
                timeouts += 1
                continue
            except usb.core.USBError:
                usb_errors += 1
                continue
            if not raw:
                continue
            decoded = decode(raw)
            if not decoded or not decoded.get("frame"):
                continue
            frames += 1
            parsed = rxd.parse_80211(decoded["frame"])
            if parsed.get("addr2") == SYNTHETIC_SRC_STR:
                injected_seen += 1
            decoded_us += bill(aggregates.feed(decoded, len(decoded["frame"]), parsed.get("addr2")))
        decoded_us += bill(aggregates.flush())
        frame_window_us = (time.monotonic() - started) * 1e6
        after, after_at = mib.sample(dev, offsets, 0)
        dropped = getattr(dev, "mcu_wait_dropped_frames", 0) - dropped_before
        result.update(
            {
                "label": label,
                "frame_window_us": round(frame_window_us),
                "decoded_frames": frames,
                "injected_frames_seen": injected_seen,
                "decoded_airtime_us": round(decoded_us),
                "decoded_airtime_fraction": round(decoded_us / frame_window_us, 6),
                "frames_dropped_by_mcu_reads": dropped,
                "usb_errors": usb_errors,
                "read_timeouts": timeouts,
                "counters": counter_result(before, after, before_at, after_at),
            }
        )
        if usb_errors:
            raise RuntimeError(f"{usb_errors} USB errors during the dwell; no RF claim is valid")
    # A worker failure must be surfaced to the main thread rather than disappearing
    # behind Thread.join(); the error is bounded before it enters the JSON result.
    except Exception as exc:
        failures.append(f"{type(exc).__name__}: {exc}"[:200])
        ready.abort()


def transmit_burst(dev, count: int, gap: float, seq_base: int = 0) -> dict:
    sent = 0
    started = time.monotonic()
    frame_len = 0
    errors = []
    for index in range(count):
        seq = seq_base + index
        # A directed, nonexistent SSID avoids the response amplification caused by
        # wildcard probes while remaining an ordinary management frame.
        frame = m.build_probe_request(SYNTHETIC_SRC, SYNTHETIC_SSID, seq)
        frame_len = len(frame)
        try:
            dev.inject(frame, dev.ep_out_ac_be, seq=seq)
            sent += 1
        except (usb.core.USBError, RuntimeError) as exc:
            errors.append(str(exc)[:100])
            break
        time.sleep(gap)
    return {
        "requested": count,
        "sent": sent,
        "gap_s": gap,
        "elapsed_s": round(time.monotonic() - started, 3),
        "expected_airtime_us": round(expected_airtime_us(frame_len, sent)),
        "errors": errors,
        "alive_after": dev.alive(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--channel", type=int, default=6, choices=(1, 6, 11))
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--transmit", type=int, default=300)
    parser.add_argument("--active-phases", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--gap", type=float, default=0.005)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--offsets", type=mib.parse_offsets, default=DEFAULT_OFFSETS)
    args = parser.parse_args()

    if not args.acknowledge_experimental_transmit:
        parser.error("refusing to transmit without --acknowledge-experimental-transmit")
    if not 1 <= args.transmit <= MAX_INJECTED_FRAMES:
        parser.error(f"--transmit must be between 1 and {MAX_INJECTED_FRAMES}")
    if args.transmit < args.active_phases:
        parser.error("--transmit must provide at least one frame per active phase")
    if not 0.005 <= args.gap <= 1.0:
        parser.error("--gap must be between 0.005 and 1.0 seconds")
    largest_burst = (args.transmit + args.active_phases - 1) // args.active_phases
    if not largest_burst * args.gap + 1 <= args.seconds <= 60:
        parser.error("--seconds must contain the whole burst plus at least one second")

    adapters = m.describe_supported_devices()
    receivers = [entry for entry in adapters if entry["chip"] == m.CHIP_MT7925]
    senders = [entry for entry in adapters if entry["chip"] == m.CHIP_MT7921]
    if not receivers or not senders:
        print("need one MT7925 receiver and one MT7921 transmitter", file=sys.stderr)
        return 2

    rx_entry = receivers[0]
    tx_entry = senders[0]
    rx = m.open_device_at(rx_entry["address"])
    tx = m.open_device_at(tx_entry["address"])
    rx_patch, rx_ram = m.load_firmware(rx.CHIP, m.firmware_dir())
    tx_patch, tx_ram = m.load_firmware(tx.CHIP, m.firmware_dir())

    results = []
    bursts = []
    failures: list[str] = []
    with rx, tx:
        rx.bringup(rx_patch, rx_ram, log=lambda *a: None)
        tx.bringup(tx_patch, tx_ram, log=lambda *a: None)
        for dev in (rx, tx):
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", args.channel, args.channel, 20)

        base_count, extra = divmod(args.transmit, args.active_phases)
        active_counts = [base_count + (index < extra) for index in range(args.active_phases)]
        phase_plan = [False]
        for _ in active_counts:
            phase_plan.extend((True, False))
        active_index = 0
        seq_base = 0

        for active in phase_plan:
            phase = {}
            ready = threading.Barrier(2)
            thread = threading.Thread(
                target=receive_phase,
                args=(
                    rx,
                    "injected" if active else "baseline",
                    args.seconds,
                    args.offsets,
                    ready,
                    phase,
                    failures,
                ),
            )
            thread.start()
            reference_before, reference_before_at = legacy_sample(tx)
            try:
                ready.wait(timeout=10)
            except threading.BrokenBarrierError:
                failures.append("radios did not rendezvous before the dwell")
                thread.join(timeout=1)
                break
            reference_started = time.monotonic()
            if active:
                count = active_counts[active_index]
                bursts.append(
                    transmit_burst(
                        tx,
                        count,
                        args.gap,
                        seq_base=seq_base,
                    )
                )
                seq_base += count
                active_index += 1
            remaining = args.seconds - (time.monotonic() - reference_started)
            if remaining > 0:
                time.sleep(remaining)
            reference_after, reference_after_at = legacy_sample(tx)
            thread.join(timeout=args.seconds + 10)
            if thread.is_alive():
                failures.append("receiver thread did not finish")
                break
            phase["mt7921_reference"] = legacy_result(
                reference_before,
                reference_after,
                reference_before_at,
                reference_after_at,
            )
            results.append(phase)

    print(
        json.dumps(
            {
                "tool": "mt7925_mib_perturb",
                "channel": f"2.4GHz:{args.channel}",
                "passive_receiver": rx_entry["usb_id"],
                "controlled_transmitter": tx_entry["usb_id"],
                "synthetic_source": True,
                "directed_synthetic_ssid": True,
                "offsets": list(args.offsets),
                "phases": results,
                "bursts": bursts,
                "failures": failures,
            },
            indent=2,
        )
    )
    if failures or sum(burst["sent"] for burst in bursts) != args.transmit:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
