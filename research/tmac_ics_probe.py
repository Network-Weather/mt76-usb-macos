#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Three four-packet CCK1 phases with TMAC ICS off/on/off; no ambient export."""

import argparse
import collections
import contextlib
import datetime
import hashlib
import itertools
import json
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import ics_trace_probe as trace
from research import phy_tx_probe as phy
from research import rmac_ics_probe as mac
from research.ics_control_probe import valid_word
from research.noise_self_tx_probe import OLD_RAM_SHA256, packet
from research.txpower_register_probe import check_image, m, read_words

MASKS = {0x820E4120: 1, 0x820E705C: 1 << 24}
TMAC_WORDS = {
    0x84C26C: 0x84C810,
    0x84C270: 0x70120,
    0x84C810: 0x08080000,
    0x829D68: 0x82E282,
    0x829D6C: 0x82E29C,
}


def request(start):
    raw = bytearray(mac.request(start))
    struct.pack_into("<H", raw, 16, 0)  # Condition0: TMAC only.
    return bytes(raw)


def send(dev, start):
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(0x49, False) != 7:
        raise ValueError("pinned MT7925 UNI49 required")
    dev.mcu_uni(0x49, request(start), query=False, wait=False)
    return dev.msg_seq


def masks(dev):
    return {hex(a): valid_word(dev.rr(a)) & mask for a, mask in MASKS.items()}


def restore(dev, originals):
    if dev.CHIP != m.CHIP_MT7925 or set(originals) != set(MASKS):
        raise ValueError("only TMAC ICS masks")
    result = {}
    for a, mask in MASKS.items():
        bits = originals[a]
        if type(bits) is not int or bits < 0 or bits & ~mask:
            raise ValueError("invalid restoration bits")
        dev.wr(a, valid_word(dev.rr(a)) & ~mask | bits)
        result[hex(a)] = valid_word(dev.rr(a)) & mask == bits
    return result


def own_matches(raw, packets):
    shape = mac.aggregate_shape(raw)
    if shape is None:
        return []
    bounded = raw[: shape["bytes"]]
    found = []
    for sequence, (payload, wire) in packets.items():
        for name, target in (("frame", payload), ("descriptor", wire[4:68])):
            offset = bounded.find(target)
            if offset >= 0:
                found.append({"sequence": sequence, "kind": name, "offset": offset})
    return found


def candidate_fields(records, packets, statuses):
    """Local-only bytes -> differential hypotheses; never export record words.

    Association is temporal (one aggregate after each isolated submission), not
    an already-decoded sequence field. Require four distinct records/statuses.
    """
    indices = list(packets)
    status_by_seq = {s["sequence"]: s for s in statuses}
    if (
        len(records) != 4
        or [i for i, _ in records] != indices
        or len(statuses) != 4
        or set(status_by_seq) != set(indices)
    ):
        return {"qualified_temporal_pairing": False}
    if any(len(raw) != 288 for _, raw in records):
        return {"qualified_temporal_pairing": False}
    out = {
        "qualified_temporal_pairing": True,
        "association": "temporal, not decoded identity",
        "sequence_candidates": [],
        "length_candidates": [],
        "clock_candidates": [],
        "relative_clock_candidates": [],
    }
    for offset in range(8, 285, 4):
        values = [struct.unpack_from("<I", raw, offset)[0] for _, raw in records]
        for shift in range(21):
            if [(v >> shift) & 0xFFF for v in values] == indices:
                out["sequence_candidates"].append({"offset": offset, "shift": shift, "bits": 12})
        for extra in (0, 4, 64, 68):
            lengths = [len(packets[i][0]) + extra for i in indices]
            for shift in range(17):
                if [(v >> shift) & 0xFFFF for v in values] == lengths:
                    out["length_candidates"].append(
                        {
                            "offset": offset,
                            "shift": shift,
                            "bits": 16,
                            "bytes_added_to_frame": extra,
                        }
                    )
        if all("timestamp_raw" in status_by_seq[i] for i in indices):
            deltas = [
                ((v - status_by_seq[i]["timestamp_raw"] + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)
                for i, v in zip(indices, values, strict=True)
            ]
            # Only near-time candidates, never arbitrary/raw word values.
            if max(deltas) - min(deltas) <= 2048 and max(abs(d) for d in deltas) < 10000:
                out["clock_candidates"].append(
                    {"offset": offset, "minus_txs_timestamp_raw": deltas}
                )
            relative = [(v - values[0]) & 0xFFFFFFFF for v in values]
            reference = [
                (status_by_seq[i]["timestamp_raw"] - status_by_seq[indices[0]]["timestamp_raw"])
                & 0xFFFFFFFF
                for i in indices
            ]
            residual = [a - b for a, b in zip(relative, reference, strict=True)]
            if (
                all(0 < b - a < 200000 for a, b in itertools.pairwise(relative))
                and max(abs(d) for d in residual) <= 2048
            ):
                out["relative_clock_candidates"].append(
                    {"offset": offset, "relative_minus_txs": residual}
                )
    return out


def acquire(tx, rx, packets, sequence=None):
    if len(packets) != 4:
        raise ValueError("exactly four prepared packets")
    pending = list(packets.items())
    submitted, good, statuses, matches, acks = [], set(), [], [], []
    shapes, types = collections.Counter(), collections.Counter()
    records = []  # Local-only opaque bytes; reduced before returning.
    decoder = m.decoder_for(rx)
    by_payload = {payload: index for index, (payload, _) in pending}
    start = time.monotonic()
    next_tx, attempts, malformed = start + 0.03, 0, 0
    while time.monotonic() < start + 0.4 and attempts < 1024:
        now = time.monotonic()
        if len(submitted) < 4 and now >= next_tx and now < start + 0.25:
            index, (_, wire) = pending[len(submitted)]
            tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
            submitted.append(index)
            next_tx = time.monotonic() + 0.025
        for dev, ep in ((rx, rx.ep_in_pkt_rx), (tx, tx.ep_in_pkt_rx), (tx, tx.ep_in_cmd_resp)):
            attempts += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            if dev is rx:
                decoded = decoder(raw)
                if decoded and not decoded.get("fcs_err"):
                    index = by_payload.get(decoded.get("frame"))
                    if index in submitted:
                        good.add(index)
                continue
            if len(raw) >= 4:
                kind = (struct.unpack_from("<I", raw)[0] >> 27) & 31
                types[(ep, kind)] += 1
                if kind == 0:
                    statuses.extend(
                        s
                        for s in phy.c3.tx_status(raw, include_timing=True)
                        if s["pid"] == 3 and s["sequence"] in submitted
                    )
            try:
                shape = mac.aggregate_shape(raw)
                if shape:
                    shapes[(ep, shape["type"], shape["bytes"], shape["frame_count"])] += 1
                    matches.extend(own_matches(raw, {i: packets[i] for i in submitted}))
                    if submitted and len(records) < 5:
                        records.append((submitted[-1], bytes(raw[: shape["bytes"]])))
            except ValueError:
                malformed += 1
            parsed = mac.event_body(raw)
            if parsed and parsed[:2] == (1, sequence) and len(parsed[2]) == 8:
                cid, status = struct.unpack("<II", parsed[2])
                if cid == 0x49:
                    acks.append({"cid": cid, "status": status})
    return {
        "elapsed_seconds": time.monotonic() - start,
        "attempts": attempts,
        "submitted_sequences": submitted,
        "exact_good_sequences": sorted(good),
        "tx_status": statuses,
        "own_exact_matches_in_ics": matches,
        "differential_hypotheses": candidate_fields(records, packets, statuses),
        "leading_packet_types": [
            {"endpoint": ep, "type": kind, "count": n} for (ep, kind), n in sorted(types.items())
        ],
        "aggregate_shapes": [
            {"endpoint": ep, "type": kind, "bytes": size, "frame_count": count, "count": n}
            for (ep, kind, size, count), n in sorted(shapes.items())
        ],
        "invalid_aggregate_lengths": malformed,
        "acknowledgments": acks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-tmac-ics", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--sequence-base", type=int, choices=(0, 8), default=0)
    args = parser.parse_args()
    if not (args.activate_tmac_ics and args.acknowledge_experimental_transmit):
        parser.error("explicit TMAC ICS and transmit acknowledgments required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "phases": [],
        "start_request_hex": request(True).hex(),
        "max_submissions": 12,
    }
    attempted, originals = False, {}
    with contextlib.ExitStack() as stack:
        radios = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        rx, tx = radios
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        check_image(images[1][1])
        if hashlib.sha256(images[0][1]).hexdigest() != OLD_RAM_SHA256:
            raise ValueError("pinned receiver image required")

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            for i in (0, 1):
                boot(i)
            out["verified"] = trace.verify(tx)
            digest = hashlib.sha256(read_words(tx, 0x82E280, 128)).hexdigest()
            if digest != "ca0bb92e18743eeec55509b70149ecbe93454342cc80700aa62d9e32982f6b0b":
                raise ValueError("TMAC ROM mismatch")
            out["tmac_rom_sha256"] = digest
            out["tmac_metadata"] = {}
            for a, expected in TMAC_WORDS.items():
                value = valid_word(tx.rr(a))
                if value != expected:
                    raise ValueError("TMAC metadata mismatch")
                out["tmac_metadata"][hex(a)] = hex(value)
            originals = {a: valid_word(tx.rr(a)) & mask for a, mask in MASKS.items()}
            if any(originals.values()) or tx.rr(0x820E50D0) & 1:
                raise ValueError("MAC ICS already enabled")
            out["original_masks"] = masks(tx)
            phy.program_rate(tx, 0)
            nonce = os.urandom(8)
            out["sequence_base"] = args.sequence_base
            for phase, enabled in enumerate((False, True, False)):
                sequence = None
                if phase:
                    attempted = True
                    sequence = send(tx, enabled)
                packets = {
                    i: packet(tx, i, nonce, 0 if i % 2 == 0 else 128)
                    for i in range(
                        args.sequence_base + phase * 4, args.sequence_base + phase * 4 + 4
                    )
                }
                row = acquire(tx, rx, packets, sequence)
                row["ics_enabled"] = enabled
                row["masks_after"] = masks(tx)
                out["phases"].append(row)
            out["alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if attempted:
                try:
                    send(tx, False)
                    out["restored"] = restore(tx, originals)
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
