#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Four own normal HT8 controls, then four or eight RF-mode ICS stimuli.

Compare only stable, source-identified cached vector bytes in memory against
own-header ICS records. No opaque data export or arbitrary RAM/command reads.
"""

import argparse
import collections
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

from research import legacy_ics_own_probe as own
from research import legacy_ics_probe as legacy
from research.cfo_crosscheck_probe import decode_cached_fields
from research.noise_self_tx_probe import packet
from research.testmode_receiver_probe import rx_setting
from research.txpower_register_probe import check_image, m

CACHE_BASE = 0x02040808
CACHE_BYTES = 96  # Traced18 C-RXV +2 P-RXV1 +4 P-RXV2 words, not a whole RAM dump.


def frequency_request(channel):
    # Pinned gl_hook_api.c SetChannel uses RF_AT_FUNCID_CHNL_FREQ18, kHz.
    if type(channel) is not int or channel not in (6, 36):
        raise ValueError("only channel6/36 receive frequencies")
    return struct.pack("<B3xII", 1, 18, 2437000 if channel == 6 else 5180000)


def cache_read(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned MT7961 cache only")
    words = [dev.rr(a) for a in range(CACHE_BASE, CACHE_BASE + CACHE_BYTES, 4)]
    if any(type(w) is not int or not 0 <= w <= 0xFFFFFFFF for w in words):
        raise ValueError("invalid cached word")
    return struct.pack("<24I", *words)


def compare_cache(first, second, records, packets):
    if len(first) != CACHE_BYTES or len(second) != CACHE_BYTES or len(records) > 128:
        raise ValueError("bounded cache and record set required")
    stable = first == second
    out = {"cache_stable": stable, "matched_own_crxv_sequences": [], "candidate_fields": []}
    if not stable or first[:72] in (bytes(72), b"\xff" * 72):
        return out
    words = struct.unpack("<24I", first)
    fields = decode_cached_fields(words[0], words[20], words[21])
    for raw in records:
        observation = own.own_ics_observation(raw, packets)
        if observation is None or raw[16:88] != first[:72]:
            continue
        sequence = observation["sequence"]
        out["matched_own_crxv_sequences"].append(sequence)
        # Equality of a complete changing C-RXV is stronger than a time-only guess,
        # but still not an independently decoded RF-mode payload/FCS verdict.
        out["cached_fields_for_matched_own_crxv"] = fields
        for offset in range(8, len(raw) - 7, 4):
            lo, hi = struct.unpack_from("<II", raw, offset)
            candidate = decode_cached_fields(words[0], lo, hi)
            if fields["raw_signed20"] not in (0, -1) and all(
                candidate[k] == fields[k] for k in ("raw_signed20", "firmware_snr_field")
            ):
                out["candidate_fields"].append(
                    {"sequence": sequence, "offset": offset, "cfo_and_snr_masks_match": True}
                )
        matches = []
        offset = raw.find(first[80:96], 8)
        while offset >= 0:
            matches.append(offset)
            offset = raw.find(first[80:96], offset + 1)
        out.setdefault("prxv2_16byte_matches", []).append(
            {"sequence": sequence, "offsets": matches}
        )
    return out


def rf_collect(tx, rx, packets):
    if len(packets) not in (4, 8):
        raise ValueError("four or eight RF stimuli")
    pending, submitted, records, own_seen = list(packets.items()), [], [], set()
    counts = collections.Counter()
    statuses = []
    start = time.monotonic()
    next_tx, attempts = start + 0.03, 0
    while time.monotonic() - start < 1.0 and attempts < 2048:
        now = time.monotonic()
        if len(submitted) < len(packets) and now >= next_tx and now < start + 0.7:
            i, (_, wire) = pending[len(submitted)]
            tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
            submitted.append(i)
            next_tx = time.monotonic() + 0.05
        for dev, ep in ((rx, rx.ep_in_pkt_rx), (tx, tx.ep_in_pkt_rx), (tx, tx.ep_in_cmd_resp)):
            attempts += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            if len(raw) < 4:
                continue
            kind = struct.unpack_from("<I", raw)[0] >> 27
            if dev is tx:
                if kind == 0:
                    statuses.extend(
                        s
                        for s in own.phy.c3.tx_status(raw)
                        if s["pid"] == 3 and s["sequence"] in submitted
                    )
                continue
            counts[kind] += 1
            shape = legacy.aggregate_shape(raw)
            if shape and len(records) < 128:
                records.append(bytes(raw[: shape["bytes"]]))
                observation = own.own_ics_observation(raw, {i: packets[i] for i in submitted})
                if observation:
                    own_seen.add(observation["sequence"])
        if len(own_seen) == len(packets):
            break  # Freeze the cache promptly after the last known diagnostic.
    rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
    time.sleep(0.05)
    first, second = cache_read(rx), cache_read(rx)
    return {
        "elapsed_seconds": time.monotonic() - start,
        "attempts": attempts,
        "submitted_sequences": submitted,
        "receiver_packet_types": dict(counts),
        "own_header_sequences": sorted(own_seen),
        "own_header_field_hypotheses": [
            v
            for raw in records
            if (v := own.own_ics_observation(raw, {i: packets[i] for i in submitted})) is not None
        ],
        "tx_status": statuses,
        "cached_vector_comparison": compare_cache(
            first, second, records, {i: packets[i] for i in submitted}
        ),
        "aggregate_shapes": [
            {"bytes": size, "frame_count": frames, "count": n}
            for (size, frames), n in sorted(
                collections.Counter(
                    (len(raw), legacy.aggregate_shape(raw)["frame_count"]) for raw in records
                ).items()
            )
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-rf-ics", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--channel", type=int, choices=(6, 36), default=36)
    parser.add_argument("--rf-packets", type=int, choices=(4, 8), default=4)
    args = parser.parse_args()
    if not (args.activate_rf_ics and args.acknowledge_experimental_transmit):
        parser.error("explicit RF/ICS and transmit acknowledgments required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "max_submissions": 4 + args.rf_packets,
        "channel": args.channel,
    }
    originals, attempted, rf_attempted = {}, False, False
    with contextlib.ExitStack() as stack:
        rx, tx = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        radios = (rx, tx)
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        check_image(images[1][1])
        if hashlib.sha256(images[0][1]).hexdigest() != legacy.OLD_RAM_SHA256:
            raise ValueError("pinned receiver required")

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel == 6 else "5GHz", args.channel, args.channel, 20)

        try:
            for i in (0, 1):
                boot(i)
            out["verified_receiver"] = legacy.verify(rx)
            originals = {a: legacy.valid_word(rx.rr(a)) & mask for a, mask in legacy.MASKS.items()}
            if (
                originals[0x820E50D0]
                or originals[0x820E705C]
                or legacy.valid_word(rx.rr(0x820E4120)) & 1
            ):
                raise ValueError("ICS already enabled")
            own.phy.program_rate(tx, 0x488)
            nonce = os.urandom(8)
            packets = {i: packet(tx, i, nonce, 0) for i in range(4 + args.rf_packets)}
            out["normal_control"] = own.acquire(tx, rx, {i: packets[i] for i in range(4)})
            if len(out["normal_control"]["exact_good_phy"]) != 4:
                raise ValueError("four independent normal controls required before RF mode")
            rf_attempted = True
            rx.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 0, 1, 0), wait=False)
            time.sleep(0.2)
            for selector, value in ((1, 0), (104, 0), (106, 3 << 16), (18, 0), (15, 0)):
                payload = (
                    frequency_request(args.channel)
                    if selector == 18
                    else rx_setting(selector, value)
                )
                rx.mcu_cmd_word(m.MCU_CE_CMD(1), payload, wait=False)
                time.sleep(0.1)
            attempted = True
            legacy.send(rx, True)
            rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 2), wait=False)
            time.sleep(0.1)
            out["rf_on_masks"] = legacy.masks(rx)
            out["rf_stimulus"] = rf_collect(
                tx, rx, {i: packets[i] for i in range(4, 4 + args.rf_packets)}
            )
            # Source GET36/subselector40 returns the finite log count; not a reset.
            raw = rx.mcu_cmd_word(m.MCU_CE_CMD(1), struct.pack("<B3xII", 2, 36, 40), timeout=1000)
            body = rx.reply_body(raw)
            if len(body) < 8 or struct.unpack_from("<I", body)[0] != 36:
                raise ValueError("missing matched log count")
            count = struct.unpack_from("<I", body, 4)[0]
            if count > 5:
                raise ValueError("finite log count outside pinned bound")
            out["stopped_finite_log_count"] = count
            out["after_stop_masks"] = legacy.masks(rx)
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if rf_attempted:
                try:
                    rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
                except Exception as exc:
                    out["rf_stop_error_type"] = type(exc).__name__
            if attempted:
                try:
                    legacy.send(rx, False)
                    out["restored"] = legacy.restore(rx, originals)
                except Exception as exc:
                    out["restore_error_type"] = type(exc).__name__
            out["cleanup_reload_alive"] = []
            for i in (0, 1):
                try:
                    boot(i)
                    out["cleanup_reload_alive"].append(radios[i].alive())
                except Exception:
                    out["cleanup_reload_alive"].append(False)
    print(json.dumps(out, indent=2))
    return int(
        any(k.endswith("error_type") for k in out)
        or not all(out.get("cleanup_reload_alive", [False]))
        or not all(out.get("restored", {}).values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
