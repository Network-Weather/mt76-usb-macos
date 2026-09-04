#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Does the occupancy counter agree with a second radio, and with known transmitted airtime?

Every occupancy figure this project has produced so far was validated against ambient traffic
with no ground truth: the counter was compared with the driver's own decode of the same
frames, which shares the receiver and every assumption behind it. Two stronger checks are
possible with two adapters.

**Agreement (default, passive).** Two radios tuned to the same channel see the same air. Their
primary-CCA counters should report the same occupancy within the difference between two
receivers. A large disagreement means the counter is measuring something local to one chip
rather than the channel, which no single-radio experiment can reveal.

**Ground truth (--transmit N).** One radio sends N spaced frames of known length at a known
rate while the other measures. The expected airtime is arithmetic rather than an estimate, so
this is the only check here that can catch a scale error -- a counter reporting half or twice
the truth would agree with itself and with a second radio, and pass every other test.

Transmit is experimental here. This sends at most MAX_INJECTED_FRAMES spaced frames, refuses
without an explicit flag, and checks the chip still answers afterwards. It uses the existing
injector rather than making transmit more capable.

Usage:
  cross_measure.py --band 5GHz --channel 36 --seconds 8
  cross_measure.py --band 5GHz --channel 36 --transmit 60 --acknowledge-experimental-transmit
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

import mcu_stats as mcs  # noqa: E402
import mib_survey as survey  # noqa: E402
import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

#: Frames per burst. examples/inject_demo.py caps at 3 and the repository describes injection
#: as rate limited, but that limit works around a Linux-side problem that does not apply to
#: this userspace driver on macOS (David, 2026-09-03). The cap here is instead set by what the
#: experiment needs: enough airtime to rise clearly above a quiet channel's floor, and few
#: enough that a burst fits inside one dwell. It is still a cap, because sustained transmit
#: remains untested and `alive()` is checked after every burst.
MAX_INJECTED_FRAMES = 1000
#: Spacing between injected frames. Wide enough that consecutive frames cannot be mistaken for
#: one PPDU by the measuring radio, tight enough that a full burst fits in a few seconds.
INJECT_GAP_S = 0.005
#: Injection is implemented for the MT7921 TXWI only.
TRANSMIT_CHIP = m.CHIP_MT7921
#: _build_txwi programs MT_TXD6_FIXED_BW with TX_RATE_1M_CCK unconditionally (mt7921u.py),
#: so expected airtime follows the TXWI and not the band. Deriving it from the band instead
#: reported a 5 GHz burst at 6 Mb/s OFDM, seven times faster than what actually goes out.
INJECT_RATE_MBPS = 1.0
INJECT_PHY_MODE = rxd.MT_PHY_TYPE_CCK
#: How long a radio may take to reach its dwell before the sender gives up waiting. The two
#: chips do not boot firmware in the same time, so this cannot be a fixed sleep.
READY_TIMEOUT_S = 30.0
#: Locally administered source address, so an injected frame cannot be mistaken for a real
#: device's traffic by anything watching.
SYNTHETIC_SRC = bytes.fromhex("02005e105ada")
#: The same address as the decoders render it, for matching a received frame's transmitter.
SYNTHETIC_SRC_STR = ":".join(f"{b:02x}" for b in SYNTHETIC_SRC)
#: Two receivers on one channel will not agree exactly. Beyond this they are not measuring the
#: same thing, and the run says so rather than averaging the disagreement away.
AGREEMENT_TOLERANCE = 0.35
READ_TIMEOUT_MS = 200


def measure(
    dev, band: str, channel: int, seconds: float, out: dict, ready: threading.Barrier | None = None
) -> None:
    """Occupancy and decoded airtime over one dwell, bracketing the CCA counter tightly."""
    decode = m.decoder_for(dev)
    aggregates = rxd.AggregationTracker()
    decoded_us = 0.0
    frames = 0
    #: Frames whose transmitter is the synthetic source this tool injects from. A receiver
    #: seeing these is independent proof the burst reached the air, which no counter on the
    #: transmitting radio can provide.
    ours = 0
    # Read the counter first, then rendezvous. Waiting before this read means the sender is
    # released while every receiver still owes an MCU round trip, and a short burst can be
    # over before anyone is in their read loop -- measured: 300 frames, zero received.
    cca_before = survey.read_cca(dev)
    if ready is not None:
        # Every radio waits here until all of them are tuned, counters sampled, and about to
        # listen, so the burst lands inside the window meant to contain it. A fixed sleep
        # cannot do this: the two chips take different times to boot their firmware.
        ready.wait(timeout=READY_TIMEOUT_S)
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        try:
            raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
        except usb.core.USBTimeoutError:
            continue
        except usb.core.USBError:
            continue
        if not raw:
            continue
        d = decode(raw)
        if not d or not d.get("frame"):
            continue
        frames += 1
        parsed = rxd.parse_80211(d["frame"])
        if parsed.get("addr2") == SYNTHETIC_SRC_STR:
            ours += 1
        for aggregate in aggregates.feed(d, len(d["frame"]), parsed.get("addr2")):
            decoded_us += aggregate.airtime_us() or 0.0
    elapsed_us = (time.monotonic() - started) * 1e6
    for aggregate in aggregates.flush():
        decoded_us += aggregate.airtime_us() or 0.0
    cca_after = survey.read_cca(dev)

    busy = None if (cca_before is None or cca_after is None) else cca_after - cca_before
    out.update(
        {
            "chip": dev.CHIP,
            "dwell_us": round(elapsed_us),
            "busy_us": busy,
            "busy_fraction": None if busy is None else round(busy / elapsed_us, 5),
            "frames_decoded": frames,
            "injected_frames_seen": ours,
            "decoded_airtime_us": round(decoded_us),
        }
    )


def transmit(dev, count: int, out: dict) -> None:
    """Send `count` spaced probe requests, and report the airtime that should imply."""
    frames = []
    for seq in range(count):
        frame = m.build_probe_request(SYNTHETIC_SRC, b"", seq)
        frames.append(frame)
    sent = 0
    started = time.monotonic()
    for seq, frame in enumerate(frames):
        try:
            dev.inject(frame, dev.ep_out_ac_be, seq=seq)
            sent += 1
        except (usb.core.USBError, RuntimeError) as exc:
            out.setdefault("errors", []).append(str(exc)[:60])
            break
        time.sleep(INJECT_GAP_S)
    out.update(
        {
            "requested": count,
            "sent": sent,
            "bytes_each": len(frames[0]) if frames else 0,
            "elapsed_s": round(time.monotonic() - started, 2),
            "alive_after": dev.alive(),
        }
    )


def expected_airtime_us(n: int, frame_len: int) -> float:
    """What n injected frames should occupy, at the rate the TXWI actually programs."""
    one = rxd.airtime_us(frame_len, INJECT_PHY_MODE, INJECT_RATE_MBPS)
    return 0.0 if one is None else one * n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--band", default="5GHz", choices=sorted(m.CHAN_BAND))
    parser.add_argument("--channel", type=int, default=36)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument(
        "--transmit",
        type=int,
        default=0,
        help=f"inject this many spaced frames (max {MAX_INJECTED_FRAMES})",
    )
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 120:
        parser.error("--seconds must be between 1 and 120")
    if args.transmit:
        if args.transmit > MAX_INJECTED_FRAMES:
            parser.error(f"--transmit is capped at {MAX_INJECTED_FRAMES} frames")
        if not args.acknowledge_experimental_transmit:
            parser.error("refusing to transmit without --acknowledge-experimental-transmit")
        if args.transmit * INJECT_GAP_S > args.seconds:
            parser.error("the dwell is shorter than the burst it is supposed to contain")

    adapters = m.describe_supported_devices()
    if len(adapters) < 2:
        print(f"need two adapters, found {len(adapters)}", file=sys.stderr)
        return 2

    out: dict = {
        "tool": "cross_measure",
        "mt76_usb_macos": m.__version__,
        "channel": f"{args.band}:{args.channel}",
        "radios": {},
    }
    if args.transmit:
        senders = [a for a in adapters if a["chip"] == TRANSMIT_CHIP]
        if not senders:
            print(f"transmit needs an {TRANSMIT_CHIP}; none attached", file=sys.stderr)
            return 2
        sender = senders[0]
        receivers = [a for a in adapters if a["address"] != sender["address"]]
    else:
        sender = None
        receivers = adapters[:2]

    results: dict[str, dict] = {a["address"]: {"usb_id": a["usb_id"]} for a in receivers}
    tx_result: dict = {}
    #: A thread that dies takes its dwell with it, and join() returns normally either way.
    #: Without collecting these, a run where no radio measured anything exits 0.
    failures: list[dict] = []
    ready = threading.Barrier(len(receivers) + (1 if sender else 0))

    def guard(name: str, fn) -> None:
        try:
            fn()
        except BaseException as exc:
            failures.append({"worker": name, "error": f"{type(exc).__name__}: {exc}"[:160]})
            # A radio that never arrives would otherwise hang everyone waiting on it.
            ready.abort()

    def run_receiver(entry: dict) -> None:
        dev = m.open_device_at(entry["address"])
        patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
        with dev:
            dev.bringup(patch, ram, log=lambda *a: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            center = m.center_channel(args.band, args.channel, 20) or args.channel
            dev.tune(args.band, args.channel, center, 20)
            measure(dev, args.band, args.channel, args.seconds, results[entry["address"]], ready)

    def run_sender() -> None:
        dev = m.open_device_at(sender["address"])
        patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
        with dev:
            dev.bringup(patch, ram, log=lambda *a: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            center = m.center_channel(args.band, args.channel, 20) or args.channel
            dev.tune(args.band, args.channel, center, 20)
            # Wait until every receiver is tuned and entering its dwell, so the burst lands
            # inside the window being measured rather than beside it.
            ready.wait(timeout=READY_TIMEOUT_S)
            # The transmitting radio is the only one here that can read the counters, so it
            # brackets its own burst. `cca_nav_tx` includes transmit time and `p_cca` does
            # not, so the pair separates "the medium was busy" from "we made it busy".
            before_counters = {
                name: survey.read_mcu_offset(dev, offs)
                for offs, name in mcs.MIB_OFFSETS_MT7921.items()
            }
            started = time.monotonic()
            transmit(dev, args.transmit, tx_result)
            after_counters = {
                name: survey.read_mcu_offset(dev, offs)
                for offs, name in mcs.MIB_OFFSETS_MT7921.items()
            }
            tx_result["self_measured"] = {
                name: (
                    None
                    if (before_counters[name] is None or after_counters[name] is None)
                    else (after_counters[name] - before_counters[name]) % (1 << 32)
                )
                for name in after_counters
            }
            tx_result["burst_window_us"] = round((time.monotonic() - started) * 1e6)

    threads = [
        threading.Thread(target=guard, args=(a["address"], lambda a=a: run_receiver(a)))
        for a in receivers
    ]
    if sender:
        threads.append(threading.Thread(target=guard, args=("sender", run_sender)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    out["radios"] = results
    if failures:
        out["failures"] = failures
    if sender:
        out["transmit"] = tx_result | {"from": sender["usb_id"], "at": sender["address"]}
        if tx_result.get("sent"):
            out["transmit"]["expected_airtime_us"] = round(
                expected_airtime_us(tx_result["sent"], tx_result["bytes_each"])
            )
            out["transmit"]["rate_mbps"] = INJECT_RATE_MBPS

    fractions = [r["busy_fraction"] for r in results.values() if r.get("busy_fraction") is not None]
    if len(fractions) == 2 and max(fractions) > 0:
        spread = abs(fractions[0] - fractions[1]) / max(fractions)
        out["agreement"] = {
            "busy_fractions": fractions,
            "relative_spread": round(spread, 4),
            "agree": spread <= AGREEMENT_TOLERANCE,
            "tolerance": AGREEMENT_TOLERANCE,
        }
    elif fractions:
        out["agreement"] = {
            "busy_fractions": fractions,
            "agree": None,
            "note": "only one radio reported occupancy",
        }

    print(json.dumps(out, indent=2))
    if failures:
        for f in failures:
            print(f"  worker {f['worker']} failed: {f['error']}", file=sys.stderr)
        print("inconclusive: a radio never ran its dwell", file=sys.stderr)
        return 2
    agreement = out.get("agreement") or {}
    if agreement.get("agree") is False:
        print(
            "\nThe two radios disagree beyond tolerance. That is the result: the counter is "
            "measuring something one chip sees and the other does not.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
