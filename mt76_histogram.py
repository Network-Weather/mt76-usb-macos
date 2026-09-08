# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Experimental raw histogram wire records, not calibrated power or occupancy.

Acquisition resets shared history and needs a separately owned/restored lifetime.
These pure helpers neither start hardware nor establish freshness or coverage.
MT7921's ordinary bank and MT7925's two timer views are different profiles.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

THRESHOLD_LABELS_RAW = (-92, -89, -86, -83, -80, -75, -70, -65, -60, -55)


@dataclass(frozen=True)
class HistogramBins:
    chip: str
    source: str
    bins: tuple[tuple[int, ...], ...]
    threshold_labels_raw: tuple[int, ...] = THRESHOLD_LABELS_RAW

    @property
    def totals(self) -> tuple[int, ...]:
        """Sums of collected samples, without32-bit accumulator overflow."""
        return tuple(sum(view) for view in self.bins)


def build_histogram_request(chip: str) -> bytes:
    """MT7925 UNI36/tag2 one-shot; no duration/mask/index override."""
    if chip != "mt7925":
        raise ValueError("histogram event request supports MT7925 only")
    return struct.pack("<4xHH", 2, 4)


def _body(chip, raw, eid, sequence):
    if chip != "mt7925" or len(raw) < 44:
        raise ValueError("histogram event supports complete MT7925 records only")
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if (
        not 44 <= size <= len(raw)
        or word >> 27 != 7
        or (word >> 16) & 15 == 1
        or raw[36] != eid
        or raw[37] != sequence
    ):
        raise ValueError("histogram DMA/type/sequence mismatch")
    return raw[44:size]


def parse_histogram_ack(chip: str, raw: bytes, sequence: int) -> int:
    if type(sequence) is not int or not 1 <= sequence <= 15:
        raise ValueError("histogram ACK requires nonzero sequence1..15")
    body = _body(chip, raw, 1, sequence)
    if len(body) != 8 or struct.unpack_from("<I", body)[0] != 0x36:
        raise ValueError("histogram ACK shape/CID mismatch")
    return struct.unpack_from("<I", body, 4)[0]


def parse_histogram_event(chip: str, raw: bytes) -> HistogramBins:
    """Strict EID36/seq0 tag2/len92: two raw views, not antenna labels.

    All-zero and unequal-total arrays are retained, not repaired or labeled
    unavailable. Valid syntax does not establish exposure time or sensor health.
    """
    body = _body(chip, raw, 0x36, 0)
    if len(body) != 96 or body[:8] != struct.pack("<4xHH", 2, 92):
        raise ValueError("histogram event shape mismatch")
    return HistogramBins(
        chip,
        "firmware_timer",
        (struct.unpack_from("<11I", body, 8), struct.unpack_from("<11I", body, 52)),
    )


def parse_legacy_histogram(chip: str, raw: bytes) -> HistogramBins:
    """Exactly eleven little-endian words from the stopped MT7921 ordinary bank.

    No USB read, freeze, reset or hardware ownership is performed here.
    """
    if chip != "mt7921" or len(raw) != 44:
        raise ValueError("legacy histogram requires MT7921 and exactly44 bank bytes")
    return HistogramBins(chip, "legacy_ordinary", (struct.unpack("<11I", raw),))
