# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Named, raw MCU counters for the repository's pinned firmware profiles.

No direct MMIO reads, automatic percentage conversion, or register configuration.
Use read_counters inside session.call when acquisition owns the device. Retain
the session epoch/channel generation alongside samples before comparing them.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from enum import IntEnum

import mt7921u as m


class Counter(IntEnum):
    RX_MPDU = 1
    RX_FCS_ERROR = 2
    RX_MDRDY = 3
    PRIMARY_CCA = 4
    CCA_NAV_TX = 5
    CCK_RX_DURATION = 6
    OFDM_RX_DURATION = 7
    PRIMARY_ED = 8
    NAV = 9
    IDLE_SLOTS = 10


class CounterUnit(IntEnum):
    COUNT = 0
    DURATION_TICKS = 1
    IDLE_SLOTS = 2


@dataclass(frozen=True)
class CounterDescriptor:
    counter: Counter
    offset: int
    unit: CounterUnit
    wire_bits: int
    hardware_bits: int | None
    accumulator_bits: int | None
    tick_ns: int | None
    hardware_saturates: bool = False

    @property
    def name(self) -> str:
        return self.counter.name.lower()


# Source/ROM mappings and qualification limits: docs/MT7925_MIB.md,
# docs/SUBCHANNEL_MEASUREMENTS.md, docs/FIRMWARE_RECON.md. A wire u64 does
# not establish accumulator width. Tick conversion for durations is unresolved.
_PROFILES = {
    m.CHIP_MT7921: (
        (Counter.RX_MPDU, 2, CounterUnit.COUNT, None, None, False),
        (Counter.RX_MDRDY, 7, CounterUnit.COUNT, None, None, False),
        (Counter.PRIMARY_CCA, 11, CounterUnit.DURATION_TICKS, None, None, False),
        (Counter.CCA_NAV_TX, 14, CounterUnit.DURATION_TICKS, None, None, False),
    ),
    m.CHIP_MT7925: (
        (Counter.RX_MPDU, 2, CounterUnit.COUNT, 32, None, False),
        (Counter.RX_FCS_ERROR, 0, CounterUnit.COUNT, 32, None, False),
        (Counter.RX_MDRDY, 11, CounterUnit.COUNT, 32, None, False),
        (Counter.PRIMARY_CCA, 17, CounterUnit.DURATION_TICKS, 32, None, False),
        (Counter.CCA_NAV_TX, 19, CounterUnit.DURATION_TICKS, 24, None, False),
        (Counter.CCK_RX_DURATION, 12, CounterUnit.DURATION_TICKS, 32, None, False),
        (Counter.OFDM_RX_DURATION, 13, CounterUnit.DURATION_TICKS, 32, None, False),
        (Counter.PRIMARY_ED, 20, CounterUnit.DURATION_TICKS, 24, None, False),
        (Counter.NAV, 52, CounterUnit.DURATION_TICKS, 24, None, False),
        (Counter.IDLE_SLOTS, 7, CounterUnit.IDLE_SLOTS, 16, 9000, True),
    ),
}


def counter_descriptors(chip: str) -> tuple[CounterDescriptor, ...]:
    """Describe the pinned profile, not a probe of the currently loaded firmware.

    None means unknown, not zero bits/ticks. Idle's 9-us hardware slot cadence
    does not recover slots lost to saturation between firmware samples.
    """
    if chip not in _PROFILES:
        raise ValueError("unsupported chip")
    return tuple(
        CounterDescriptor(c, off, unit, 64 if chip == m.CHIP_MT7925 else 32, bits, None, ns, sat)
        for c, off, unit, bits, ns, sat in _PROFILES[chip]
    )


def _offsets(chip, offsets):
    offsets = tuple(offsets)
    if (
        chip not in _PROFILES
        or not 1 <= len(offsets) <= 16
        or (chip == m.CHIP_MT7921 and len(offsets) != 1)
        or any(type(v) is not int or not 0 <= v <= 511 for v in offsets)
        or len(set(offsets)) != len(offsets)
    ):
        raise ValueError("invalid chip/offset request")
    return offsets


def build_mib_request(chip: str, offsets, band: int = 0) -> bytes:
    """Pure bounded wire encoder, matching C mt_mib_request (not an I/O API)."""
    offsets = _offsets(chip, offsets)
    if type(band) is not int or band not in (0, 1):
        raise ValueError("band index must be 0 or 1")
    if chip == m.CHIP_MT7921:
        return struct.pack("<IIQ", band, offsets[0], 0)
    return struct.pack("<B3x", band) + b"".join(struct.pack("<HHI", 0, 8, o) for o in offsets)


def parse_mib_reply(chip: str, body: bytes, offsets) -> tuple[int, ...]:
    """Strict complete requested set; malformed/missing/duplicate entries raise.

    This consumes a reply body after MCU sequence matching. EXT has no offset
    echo. UNI's measured prefix varies; only aligned tag0/length8-or-16 echoes
    qualify, including a complete final entry. No partial measurements on error.
    """
    offsets = _offsets(chip, offsets)
    if chip == m.CHIP_MT7921:
        if len(body) < 32:
            raise ValueError("short EXT MIB reply")
        return (struct.unpack_from("<I", body, 28)[0],)
    found = {}
    for at in range(0, len(body) - 7, 2):
        tag, size, echoed = struct.unpack_from("<HHI", body, at)
        if tag != 0 or size not in (8, 16) or echoed not in offsets:
            continue
        if at + 16 > len(body) or echoed in found:
            raise ValueError("truncated or ambiguous UNI MIB entry")
        found[echoed] = struct.unpack_from("<Q", body, at + 8)[0]
    if len(found) != len(offsets):
        raise ValueError("missing UNI MIB entry")
    return tuple(found[o] for o in offsets)


def parse_mib_event(chip: str, raw: bytes, sequence: int, offsets) -> tuple[int, ...]:
    """Validate a matched MCU record's DMA bounds; ignore only USB tail padding."""
    offsets = _offsets(chip, offsets)
    header = 44 if chip == m.CHIP_MT7925 else 36
    seq_at = 37 if chip == m.CHIP_MT7925 else 29
    if type(sequence) is not int or not 1 <= sequence <= 15 or len(raw) < header:
        raise ValueError("invalid MIB event header/sequence")
    word = struct.unpack_from("<I", raw)[0]
    size = word & 0xFFFF
    if (
        not header <= size <= min(len(raw), 1024)
        or word >> 27 != m.PKT_TYPE_RX_EVENT
        or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
        or raw[seq_at] != sequence
    ):
        raise ValueError("invalid MIB event DMA bounds/type/sequence")
    return parse_mib_reply(chip, raw[header:size], offsets)


@dataclass(frozen=True)
class CounterReading:
    descriptor: CounterDescriptor
    raw: int


@dataclass(frozen=True)
class CounterSample:
    chip: str
    readings: tuple[CounterReading, ...]
    opened_us: int
    closed_us: int
    legacy_dropped_frames: int


def read_counters(dev, counters) -> CounterSample:
    """Read a finite named set through MCU band0, with no direct read-clear access.

    Caller owns an initialized pinned-firmware device (or executes via session.call).
    Old-chip requests are serialized singly; new-chip requests are batched, not
    hardware-atomic. The outer host interval includes all requests. Unsupported
    names fail before I/O; transport/parser failures raise, never become zeros.
    No delta/wrap/percentage inference is made while accumulator widths and some
    units remain unresolved. Legacy discards exclude session consumer overflow.
    """
    names = tuple(counters)
    if not 1 <= len(names) <= 16 or any(not isinstance(c, Counter) for c in names):
        raise ValueError("request 1..16 Counter names")
    if len(set(names)) != len(names):
        raise ValueError("duplicate counter")
    supported = {d.counter: d for d in counter_descriptors(dev.CHIP)}
    if any(c not in supported for c in names):
        raise ValueError("counter not supported by pinned chip profile")
    descriptors = tuple(supported[c] for c in names)
    offsets = tuple(d.offset for d in descriptors)
    groups = (offsets,) if dev.CHIP == m.CHIP_MT7925 else tuple((o,) for o in offsets)
    values = []
    dropped = dev.mcu_wait_dropped_frames
    opened = time.monotonic_ns() // 1000
    for group in groups:
        request = build_mib_request(dev.CHIP, group)
        if dev.CHIP == m.CHIP_MT7925:
            reply = dev.mcu_uni(0x22, request, query=True, timeout=700)
        else:
            reply = dev.mcu_cmd_word(m.MCU_EXT_CMD(0x5A), request, timeout=700)
        values.extend(parse_mib_event(dev.CHIP, reply, dev.msg_seq, group))
    return CounterSample(
        dev.CHIP,
        tuple(CounterReading(d, v) for d, v in zip(descriptors, values, strict=True)),
        opened,
        time.monotonic_ns() // 1000,
        dev.mcu_wait_dropped_frames - dropped,
    )
