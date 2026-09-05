#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Three four-packet CCK or qualified HT/HE phases with TMAC ICS off/on/off.

Optional independent rate, qualified coding, or zero/negative-four power controls.
Opaque records stay local in memory; output is matched metadata/hypotheses.
"""

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


def prepared_packet(dev, sequence, nonce, power_differential=False):
    if type(power_differential) is not bool:
        raise ValueError("boolean power differential required")
    payload, wire = packet(dev, sequence, nonce, 0 if sequence % 2 == 0 else 128)
    offset = -4 if power_differential and sequence % 4 >= 2 else 0
    raw = bytearray(wire)
    word = struct.unpack_from("<I", raw, 12)[0]  # USB length4 + TXD2 offset8.
    struct.pack_into("<I", raw, 12, (word & ~(63 << 26)) | ((offset & 63) << 26))
    return payload, bytes(raw)


def planned_rate(sequence, pattern):
    if pattern == "cck-ht-he":
        return (0, 1, 0x488, 0x600)[sequence % 4]
    if pattern == "ht-he":
        return 0x488 if sequence % 2 == 0 else 0x600
    if pattern == "ht-he-blocks":
        return 0x488 if sequence % 4 < 2 else 0x600
    if pattern not in ("fixed", "blocks", "alternating"):
        raise ValueError("bounded CCK1/2 patterns only")
    return (
        0 if pattern == "fixed" else int(sequence % 4 >= 2) if pattern == "blocks" else sequence % 2
    )


def planned_coding(sequence, pattern):
    changed = int(sequence % 4 >= 2)
    if pattern == "ht-gi":
        return {"code": 0x488, "gi": changed, "ltf": 0, "ldpc": 0}
    if pattern == "ht-gi-alternating":
        return {"code": 0x488, "gi": sequence % 2, "ltf": 0, "ldpc": 0}
    if pattern in ("he-ldpc", "he-ldpc-alternating"):
        if pattern == "he-ldpc-alternating":
            changed = sequence % 2
        return {"code": 0x600, "gi": 0, "ltf": 1, "ldpc": changed}
    raise ValueError("only qualified HT GI or HE LDPC patterns")


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


def own_field_match(raw, packets):
    """Consistency check of previously mapped candidates against known frames.

    Not a general decoder: exact aggregate shape, two sequence copies and two
    length copies must all agree with a submitted synthetic frame.
    """
    shape = mac.aggregate_shape(raw)
    if shape != {"type": 12, "bytes": 288, "frame_count": 2}:
        return None
    sequence = struct.unpack_from("<I", raw, 124)[0] >> 20
    if sequence != struct.unpack_from("<I", raw, 272)[0] & 0xFFF or sequence not in packets:
        return None
    payload = packets[sequence][0]
    size = len(payload) + 4
    if any(struct.unpack_from("<I", raw, a)[0] & 0xFFFF != size for a in (48, 96)):
        return None
    return {
        "sequence": sequence,
        "matched_frame_bytes_with_fcs": size,
        "power_raw_candidate": (struct.unpack_from("<I", raw, 24)[0] >> 16) & 255,
        "rate_raw_candidate": struct.unpack_from("<I", raw, 88)[0] & 0x3FFF,
    }


def own_sequence_observation(raw, packets):
    """Previously identified fields and source masks, paired by two sequences.

    Retains format counterexamples without weakening the strict length matcher.
    No extra record words or clock origins are exported.
    """
    shape = mac.aggregate_shape(raw)
    if shape != {"type": 12, "bytes": 288, "frame_count": 2}:
        return None
    sequence = struct.unpack_from("<I", raw, 124)[0] >> 20
    if sequence not in packets or sequence != struct.unpack_from("<I", raw, 272)[0] & 0xFFF:
        return None
    size = len(packets[sequence][0])
    txv0, txv1, txv2 = struct.unpack_from("<3I", raw, 24)
    alternate_txv2 = struct.unpack_from("<I", raw, 88)[0]
    return {
        "sequence": sequence,
        "pairing": "two candidate sequence copies, length not required",
        "frame_bytes_without_fcs": size,
        "offset48_u16": struct.unpack_from("<H", raw, 48)[0],
        "offset96_u16": struct.unpack_from("<H", raw, 96)[0],
        "offset88_low14": struct.unpack_from("<I", raw, 88)[0] & 0x3FFF,
        "offset24_bits23_16": (struct.unpack_from("<I", raw, 24)[0] >> 16) & 255,
        "source_txv_at24_hypothesis": {
            "mode": (txv0 >> 12) & 15,
            "bandwidth_code": (txv0 >> 8) & 7,
            "stbc": (txv0 >> 6) & 3,
            "power_raw": (txv0 >> 16) & 255,
            "spatial_index": txv0 & 31,
            "gi": (txv1 >> 26) & 3,
            "rate_index": txv2 & 127,
            "ldpc": (txv2 >> 7) & 1,
            "nsts_raw": (txv2 >> 28) & 15,
        },
        "source_txv2_at88_hypothesis": {
            "rate_index": alternate_txv2 & 127,
            "ldpc": (alternate_txv2 >> 7) & 1,
            "nsts_raw": (alternate_txv2 >> 28) & 15,
        },
        "source_txv1_at36_hypothesis": {
            "gi": (struct.unpack_from("<I", raw, 36)[0] >> 26) & 3,
        },
    }


def candidate_fields(records, packets, statuses, received_phy=None):
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
        "power_candidates": [],
        "rate_candidates": [],
        "independent_phy_bit_candidates": [],
    }
    for offset in range(8, 285, 4):
        values = [struct.unpack_from("<I", raw, offset)[0] for _, raw in records]
        if received_phy and set(received_phy) == set(indices):
            for field, bits in (("gi", 2), ("ldpc", 1)):
                expected = [received_phy[i].get(field) for i in indices]
                if any(v is None for v in expected) or len(set(expected)) < 2:
                    continue
                for shift in range(33 - bits):
                    if [(v >> shift) & ((1 << bits) - 1) for v in values] == expected:
                        out["independent_phy_bit_candidates"].append(
                            {"field": field, "offset": offset, "shift": shift, "bits": bits}
                        )
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
        if all("power_raw" in status_by_seq[i] for i in indices):
            powers = [status_by_seq[i]["power_raw"] for i in indices]
            if len(set(powers)) >= 2:
                for shift in range(25):
                    if [(v >> shift) & 255 for v in values] == powers:
                        out["power_candidates"].append(
                            {
                                "offset": offset,
                                "shift": shift,
                                "bits": 8,
                                "matches_txs_power_raw": True,
                            }
                        )
        if all("rate_raw" in status_by_seq[i] for i in indices):
            rates = [status_by_seq[i]["rate_raw"] for i in indices]
            if len(set(rates)) >= 2:
                for shift in range(19):
                    if [(v >> shift) & 0x3FFF for v in values] == rates:
                        out["rate_candidates"].append(
                            {
                                "offset": offset,
                                "shift": shift,
                                "bits": 14,
                                "matches_txs_rate_raw": True,
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


def acquire(tx, rx, packets, sequence=None, rate_pattern="fixed", coding_pattern="fixed"):
    if len(packets) != 4:
        raise ValueError("exactly four prepared packets")
    pending = list(packets.items())
    submitted, good, statuses, matches, acks = [], set(), [], [], []
    shapes, types = collections.Counter(), collections.Counter()
    records = []  # Local-only opaque bytes; reduced before returning.
    own_phy = {}
    settings = {}
    decoder = m.decoder_for(rx)
    by_payload = {payload: index for index, (payload, _) in pending}
    start = time.monotonic()
    next_tx, attempts, malformed = start + 0.03, 0, 0
    while time.monotonic() < start + 0.4 and attempts < 1024:
        now = time.monotonic()
        if len(submitted) < 4 and now >= next_tx and now < start + 0.25:
            index, (_, wire) = pending[len(submitted)]
            if coding_pattern != "fixed":
                settings[index] = planned_coding(index, coding_pattern)
                phy.program_rate(tx, **settings[index])
            elif rate_pattern != "fixed":
                phy.program_rate(tx, planned_rate(index, rate_pattern))
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
                        own_phy[index] = {
                            k: decoded.get("phy", {}).get(k)
                            for k in ("mode_name", "mcs", "nss", "bw_mhz", "gi", "ldpc", "stbc")
                        }
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
        "exact_good_phy": own_phy,
        "programmed_coding": settings,
        "tx_status": statuses,
        "own_exact_matches_in_ics": matches,
        "differential_hypotheses": candidate_fields(records, packets, statuses, own_phy),
        "known_frame_field_matches": [
            match
            for _, raw in records
            if (match := own_field_match(raw, {i: packets[i] for i in submitted})) is not None
        ],
        "known_sequence_field_observations": [
            observation
            for _, raw in records
            if (observation := own_sequence_observation(raw, {i: packets[i] for i in submitted}))
            is not None
        ],
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
    parser.add_argument("--power-differential", action="store_true")
    parser.add_argument(
        "--coding-pattern",
        choices=("fixed", "ht-gi", "ht-gi-alternating", "he-ldpc", "he-ldpc-alternating"),
        default="fixed",
    )
    parser.add_argument(
        "--rate-pattern",
        choices=("fixed", "blocks", "alternating", "ht-he", "ht-he-blocks", "cck-ht-he"),
        default="fixed",
    )
    args = parser.parse_args()
    if not (args.activate_tmac_ics and args.acknowledge_experimental_transmit):
        parser.error("explicit TMAC ICS and transmit acknowledgments required")
    if args.power_differential and args.rate_pattern != "fixed":
        parser.error("separate power and rate differential runs required")
    if args.coding_pattern != "fixed" and (args.power_differential or args.rate_pattern != "fixed"):
        parser.error("coding controls require separate fixed-rate/no-power-offset runs")
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
            out["power_differential"] = args.power_differential
            out["rate_pattern"] = args.rate_pattern
            out["coding_pattern"] = args.coding_pattern
            for phase, enabled in enumerate((False, True, False)):
                sequence = None
                if phase:
                    attempted = True
                    sequence = send(tx, enabled)
                packets = {
                    i: prepared_packet(tx, i, nonce, args.power_differential)
                    for i in range(
                        args.sequence_base + phase * 4, args.sequence_base + phase * 4 + 4
                    )
                }
                row = acquire(tx, rx, packets, sequence, args.rate_pattern, args.coding_pattern)
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
