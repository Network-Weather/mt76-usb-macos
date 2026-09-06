# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded in-memory RXD/ICS equality tests; export counts/offsets, never bytes."""

import collections
import struct

import rxd as legacy_rx
import rxd_connac3 as rx

LIMIT = 128


def paired_fields(pairs):
    """Unique-header pairs -> varying vector-copy and relative-clock candidates."""
    out = {
        "unique_header_pairs": len(pairs),
        "vector_candidates": [],
        "clock_candidates": [],
        "crxv_at24_word_agreement": [],
    }
    if len(pairs) < 8 or len({len(raw) for _, raw in pairs}) != 1:
        return out
    size = len(pairs[0][1])
    if size >= 120 and all("crxv96" in sig for sig, _ in pairs):
        for word in range(24):
            expected = [struct.unpack_from("<I", sig["crxv96"], word * 4)[0] for sig, _ in pairs]
            equal = sum(
                raw[24 + word * 4 : 28 + word * 4] == sig["crxv96"][word * 4 : 4 + word * 4]
                for sig, raw in pairs
            )
            out["crxv_at24_word_agreement"].append(
                {
                    "word": word,
                    "equal": equal,
                    "pairs": len(pairs),
                    "distinct_reference_values": len(set(expected)),
                }
            )
    sources = {}
    for name in ("prxv16", "crxv96", "prxv8", "crxv72"):
        if all(name in sig for sig, _ in pairs):
            for word in range(len(pairs[0][0][name]) // 4):
                sources[(name, word, 32, 0)] = [
                    struct.unpack_from("<I", sig[name], 4 * word)[0] for sig, _ in pairs
                ]
    if all("prxv16" in sig for sig, _ in pairs):
        for chain in (0, 1):
            sources[("prxv_rcpi", 3, 8, 8 * chain)] = [
                sig["prxv16"][12 + chain] for sig, _ in pairs
            ]
    if all("crxv72" in sig for sig, _ in pairs):
        for chain in (0, 1):
            sources[("legacy_crxv_rcpi", 6, 8, 8 * chain)] = [
                sig["crxv72"][24 + chain] for sig, _ in pairs
            ]
    for (name, word, bits, source_shift), expected in sources.items():
        # Variation is required: a zero-filled word is not a validated copy.
        if len(set(expected)) < 4:
            continue
        for offset in range(8, size - 3, 4):
            values = [struct.unpack_from("<I", raw, offset)[0] for _, raw in pairs]
            for shift in (0,) if bits == 32 else (0, 8, 16, 24):
                if all(
                    (v >> shift) & ((1 << bits) - 1) == e
                    for v, e in zip(values, expected, strict=True)
                ):
                    out["vector_candidates"].append(
                        {
                            "source": name,
                            "source_word": word,
                            "source_shift": source_shift,
                            "bits": bits,
                            "offset": offset,
                            "shift": shift,
                            "distinct_reference_values": len(set(expected)),
                        }
                    )
    if all("timestamp4" in sig for sig, _ in pairs):
        times = [struct.unpack("<I", sig["timestamp4"])[0] for sig, _ in pairs]
        if len(set(times)) >= 8:
            reference = [(v - times[0]) & 0xFFFFFFFF for v in times]
            for offset in range(8, size - 3, 4):
                values = [struct.unpack_from("<I", raw, offset)[0] for _, raw in pairs]
                differences = [
                    (((v - values[0]) - ref + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)
                    for v, ref in zip(values, reference, strict=True)
                ]
                if max(abs(v) for v in differences) <= 2048:
                    out["clock_candidates"].append(
                        {
                            "offset": offset,
                            "relative_minus_rxd_min": min(differences),
                            "relative_minus_rxd_max": max(differences),
                        }
                    )
    return out


def signatures(raw):
    """Local-only candidate signatures from a complete good-FCS normal RXD."""
    if len(raw) < rx.RXD_FIXED_LEN:
        return {}
    length = struct.unpack_from("<H", raw)[0]
    if not rx.RXD_FIXED_LEN <= length <= len(raw):
        return {}
    raw = bytes(raw[:length])
    decoded = rx.decode(raw)
    if not decoded or decoded.get("fcs_err") or not decoded.get("frame"):
        return {}
    groups = struct.unpack_from("<I", raw, 4)[0]
    off = rx.RXD_FIXED_LEN
    result = {"fixed_rxd32": raw[:32]}
    frame = decoded["frame"]
    if len(frame) >= 24:
        result["mac_header24"] = frame[:24]
    for flag in (rx.MT_RXD1_NORMAL_GROUP_4, rx.MT_RXD1_NORMAL_GROUP_1):
        if groups & flag:
            off += rx.GROUP_LEN
    if groups & rx.MT_RXD1_NORMAL_GROUP_2:
        if off + rx.GROUP_LEN > length:
            return {}
        if any(raw[off : off + 4]):
            result["timestamp4"] = raw[off : off + 4]
        off += rx.GROUP_LEN
    if groups & rx.MT_RXD1_NORMAL_GROUP_3:
        if off + rx.GROUP_LEN > length:
            return {}
        result["prxv16"] = raw[off : off + rx.GROUP_LEN]
        off += rx.GROUP_LEN
        if groups & rx.MT_RXD1_NORMAL_GROUP_5:
            if off + rx.GROUP5_LEN > length:
                return {}
            result["crxv96"] = raw[off : off + rx.GROUP5_LEN]
    return result


def legacy_signatures(raw):
    """Connac2-specific group lengths; no connac3 layout assumptions."""
    if len(raw) < 24:
        return {}
    length = struct.unpack_from("<H", raw)[0]
    if not 24 <= length <= len(raw):
        return {}
    raw = bytes(raw[:length])
    decoded = legacy_rx.decode(raw)
    if not decoded or decoded.get("fcs_err") or not decoded.get("frame"):
        return {}
    result = {"fixed_rxd24": raw[:24]}
    if len(decoded["frame"]) >= 24:
        result["mac_header24"] = decoded["frame"][:24]
    flags = (struct.unpack_from("<I", raw, 4)[0] >> 11) & 31
    off = 24 + (16 if flags & 8 else 0) + (16 if flags & 1 else 0)
    if flags & 2:
        if off + 8 > length:
            return {}
        if any(raw[off : off + 4]):
            result["timestamp4"] = raw[off : off + 4]
        off += 8
    if flags & 4:
        if off + 8 > length:
            return {}
        result["prxv8"] = raw[off : off + 8]
        off += 8
        if flags & 16:
            if off + 72 > length:
                return {}
            result["crxv72"] = raw[off : off + 72]
    return result


def reduce_matches(normal, aggregates, legacy=False):
    """Only aggregate counts and byte offsets escape this local comparison.

    Repeated RXD signatures are not treated as unique identities. Even a unique
    timestamp equality is only a candidate until a second signature agrees.
    """
    if len(normal) > LIMIT or len(aggregates) > LIMIT:
        raise ValueError("bounded local capture required")
    extract = legacy_signatures if legacy else signatures
    rows = [s for raw in normal if (s := extract(raw))]
    lookup = collections.defaultdict(lambda: collections.defaultdict(set))
    for index, row in enumerate(rows):
        for kind, value in row.items():
            if any(value):
                lookup[kind][value].add(index)
    offsets = collections.Counter()
    any_matches = collections.Counter()
    agreements = collections.Counter()
    pairs = []  # Local-only uniquely header-matched normal/diagnostic pairs.
    qualified_shapes = 0
    for raw in aggregates:
        if len(raw) < 8:
            continue
        word = struct.unpack_from("<I", raw)[0]
        size = word & 0xFFFF
        if (word >> 27) != 12 or not 8 <= size <= len(raw):
            continue
        raw = raw[:size]
        qualified_shapes += 1
        matched = collections.defaultdict(set)
        for kind, values in lookup.items():
            for target, ids in values.items():
                offset = raw.find(target, 8)
                while offset >= 0:
                    offsets[(kind, offset)] += 1
                    matched[kind].update(ids)
                    offset = raw.find(target, offset + 1)
            if matched[kind]:
                any_matches[kind] += 1
        for second in (
            "mac_header24",
            "prxv16",
            "crxv96",
            "fixed_rxd32",
            "prxv8",
            "crxv72",
            "fixed_rxd24",
        ):
            common = matched["timestamp4"] & matched[second]
            if len(common) == 1:
                agreements[second] += 1
        if len(matched["mac_header24"]) == 1:
            pairs.append((rows[next(iter(matched["mac_header24"]))], raw))
    return {
        "normal_retained": len(normal),
        "good_complete_normal": len(rows),
        "ics_retained": len(aggregates),
        "ics_type12_valid": qualified_shapes,
        "distinct_nonzero_signatures": {kind: len(values) for kind, values in lookup.items()},
        "records_with_signature_match": dict(any_matches),
        "unique_timestamp_plus_second_signature": dict(agreements),
        "offset_match_counts": [
            {"signature": kind, "offset": off, "matches": count}
            for (kind, off), count in sorted(offsets.items())
        ],
        "header_paired_field_hypotheses": paired_fields(pairs),
        "scope": "in-memory equality candidates, no identifiers/bytes/timestamps exported",
    }
