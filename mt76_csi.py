# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Experimental pinned MT7925 beacon/20MHz CSI wire primitives; no I/O.

See docs/STATION_CSI.md for source, firmware and hardware evidence. These helpers
do not establish a streaming lifecycle, calibrate I/Q, or identify a beacon from
the report alone. Apply the beacon selector and host filtering in an explicitly
owned session. Addresses and coefficient arrays are sensitive in-memory data.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum


class CsiAction(IntEnum):
    STOP = 0
    START = 1
    BEACON_SELECTOR = 2
    RECEIVER_COUNT = 3
    ADD_TRANSMITTER = 4
    REMOVE_TRANSMITTER = 5


def build_csi_request(chip: str, action: CsiAction, *, receivers=0, transmitter=None) -> bytes:
    """Finite band0 controls only; START clears firmware transmitter filters.

    Apply transmitter allowlist AFTER START, then receiver count LAST. Firmware ACKs
    do not discard already queued events: the host must enforce its filter too.
    STOP does not restore every configuration field; reload after experiments.
    """
    if chip != "mt7925":
        raise ValueError("CSI profile supports MT7925 only")
    if not isinstance(action, CsiAction) or type(receivers) is not int:
        raise ValueError("invalid CSI action or receiver count")
    if receivers != 0 and action != CsiAction.RECEIVER_COUNT:
        raise ValueError("receiver count only applies to its CSI action")
    if transmitter is not None and action not in (
        CsiAction.ADD_TRANSMITTER,
        CsiAction.REMOVE_TRANSMITTER,
    ):
        raise ValueError("transmitter only applies to CSI filter actions")
    if action in (CsiAction.STOP, CsiAction.START):
        return struct.pack("<4xHH", action, 4)
    if action == CsiAction.BEACON_SELECTOR:
        return struct.pack("<4xHHBI2x", 2, 11, 0, 0x20)
    if action == CsiAction.RECEIVER_COUNT:
        if receivers not in (1, 2):
            raise ValueError("CSI requires one or two receivers")
        return struct.pack("<4xHHB3x", 3, 8, receivers)
    if (
        not isinstance(transmitter, bytes)
        or len(transmitter) != 6
        or transmitter[0] & 1
        or not any(transmitter)
    ):
        raise ValueError("CSI filter requires one nonzero unicast transmitter")
    return struct.pack("<4xHHBB6s", 4, 12, action == CsiAction.ADD_TRANSMITTER, 0, transmitter)


def _event_body(chip, raw, eid, sequence):
    if chip != "mt7925" or type(sequence) is not int or not 0 <= sequence <= 15 or len(raw) < 44:
        raise ValueError("unsupported or short CSI event")
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if (
        not 44 <= size <= len(raw)
        or word >> 27 != 7
        or (word >> 16) & 15 == 1
        or raw[36] != eid
        or raw[37] != sequence
    ):
        raise ValueError("invalid CSI event DMA/type/identity")
    return raw[44:size]


def parse_csi_ack(chip: str, raw: bytes, sequence: int) -> int:
    """Return status only from an exact matched UNI4a command-result envelope."""
    if not sequence:
        raise ValueError("CSI ACK requires nonzero sequence")
    body = _event_body(chip, raw, 1, sequence)
    if len(body) != 8 or struct.unpack_from("<I", body)[0] != 0x4A:
        raise ValueError("invalid CSI command result")
    return struct.unpack_from("<I", body, 4)[0]


def parse_csi_tlvs(body: bytes) -> dict[int, bytes]:
    """Bounded structural parser, also used by broader research-only layouts.

    Unknown tags are length-checked and returned, not interpreted. Do not log
    this dictionary: it contains private transmitter and coefficient data.
    """
    if not 8 <= len(body) <= 8192:
        raise ValueError("CSI body size")
    if struct.unpack_from("<HH", body, 4) != (0, len(body) - 4):
        raise ValueError("CSI outer TLV")
    fields = {}
    pos = 8
    while pos < len(body):
        if (
            len(body) - pos == 36
            and fields
            and next(reversed(fields)) == 25
            and len(fields[25]) == 4
            and not any(body[pos:])
        ):
            break
        if len(fields) >= 64 or len(body) - pos < 8:
            raise ValueError("CSI inner header")
        tag, length = struct.unpack_from("<II", body, pos)
        pos += 8
        if tag > 63 or length > 8192:
            raise ValueError("CSI out-of-range inner header")
        if tag in fields or length > len(body) - pos:
            raise ValueError("CSI duplicate or truncated field")
        fields[tag] = body[pos : pos + length]
        pos += length
    return fields


@dataclass(frozen=True)
class BeaconCsiReport:
    version: int
    data_count: int
    rx_index: int
    tx_index: int
    rx_mode_raw: int
    rx_rate_raw: int
    channel_index_raw: int  # Not an RF channel number; observed zero on channel36.
    rssi_raw_s8: int
    snr_raw: int  # No calibrated SNR conversion.
    mcu_gpt_raw: int  # Wrapping32-bit, approximately1us; NOT TSF/RXD/ToA.
    transmitter: bytes = field(repr=False)
    i: tuple[int, ...] = field(repr=False)
    q: tuple[int, ...] = field(repr=False)


def parse_beacon_csi(chip: str, raw: bytes) -> BeaconCsiReport:
    """Accept only evidenced version22, band0, 20MHz OFDM6, 64-I/Q profile.

    Reject CCK count13/storage64 as unusable, unknown versions, wider/segmented
    reports and unsupported receiver indices. Validity still requires a matching
    configured session/epoch/filter, not just these bytes. No pairing is implied.
    """
    fields = parse_csi_tlvs(_event_body(chip, raw, 0x4A, 0))
    required = (0, 1, 2, 3, 4, 5, 8, 9, 12, 18, 20, 21, 25)
    if any(len(fields.get(tag, b"")) != 4 for tag in required):
        raise ValueError("CSI required scalar size")
    words = {tag: struct.unpack("<I", fields[tag])[0] for tag in required}
    if (
        words[0] != 22
        or words[5] != 64
        or words[12] != (11 << 16 | 1)
        or words[18] not in (0, 1)
        or any(words[tag] for tag in (1, 4, 8, 20, 21))
    ):
        raise ValueError("CSI report outside pinned beacon20 profile")
    if len(fields.get(10, b"")) != 8 or any(len(fields.get(tag, b"")) != 128 for tag in (6, 7)):
        raise ValueError("CSI transmitter or I/Q dimensions")
    transmitter = fields[10][:6]
    if transmitter[0] & 1 or not any(transmitter):
        raise ValueError("CSI invalid transmitter")
    rssi = words[2] & 255
    return BeaconCsiReport(
        22,
        64,
        words[18],
        0,
        1,
        11,
        words[9],
        rssi if rssi < 128 else rssi - 256,
        words[3],
        words[25],
        transmitter,
        struct.unpack("<64h", fields[6]),
        struct.unpack("<64h", fields[7]),
    )
