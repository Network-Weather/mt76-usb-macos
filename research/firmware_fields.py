# SPDX-License-Identifier: BSD-3-Clause-Clear
"""MT7961 field mappings recovered from bounded NDS32 ROM inspection.

Research-only, pinned-firmware facts; not a cross-chip register API. No writes.
Keys encode domain, register-table index, and field-table index, NOT bit number.
ROM resolver 0x826860; domain mappers 0x830350 (IPI), 0x832174 (ICAP).
Reads can have hardware side effects; snapshots are separate diagnostic runs.
"""

import struct

IPI_CONTROL = 0x830AF04C
IPI_COUNTERS = tuple(0x830AF0A8 + 4 * i for i in range(12))
ICAP_CONTROL = 0x80021090
ICAP_REGISTERS = (ICAP_CONTROL, 0x80021098, 0x8002109C, 0x800210A4, 0x800210B4)
ICAP_PHY_REGISTERS = (
    0x83080004,
    0x83080008,
    0x830A1000,
    0x830A1004,
    0x830A3008,
    0x830AD440,
    0x830AD448,
)
KEYS = (
    0x260000,
    0x260001,
    0x260002,
    *(0x260080 + 32 * i for i in range(12)),
    0x5A0013,
    0x5A0005,
    0x5A0040,
    0x5A0060,
    0x5A00A0,
    0x5A0008,
    0x5A0120,
)


def resolve_field(read_word, key):
    """Read only ROM entries used by these exact, previously traced field keys."""
    if type(key) is not int or key not in KEYS:
        raise ValueError("only traced MT7961 IPI/ICAP keys allowed")
    table, base = (0x84CAC4, 0x830A0000) if key >> 16 == 0x26 else (0x84D550, 0x80021000)
    entry = table + 8 * ((key & 0xFFFF) >> 5)
    pointer = read_word(entry)
    offset, count, _ = struct.unpack("<HBB", struct.pack("<I", read_word(entry + 4)))
    field = key & 31
    # The traced field tables are ROM data, never follow arbitrary RAM pointers.
    if not 0x84C000 <= pointer < 0x84E000 or pointer & 1 or field >= count:
        raise ValueError("unexpected ROM field descriptor")
    pair_address = pointer + 2 * field
    pair = (read_word(pair_address & ~3) >> (8 * (pair_address & 3))) & 0xFFFF
    low, high = pair & 255, pair >> 8
    if not 0 <= low <= high < 32:
        raise ValueError("unexpected ROM field bit range")
    return {
        "key": hex(key),
        "table_entry": hex(entry),
        "field_table": hex(pointer),
        "register": hex(base + offset),
        "field_index": field,
        "field_count": count,
        "low_bit": low,
        "high_bit": high,
        "mask": hex(((1 << (high - low + 1)) - 1) << low),
    }


def ipi_snapshot(dev):
    control = dev.rr(IPI_CONTROL)
    words = [dev.rr(address) for address in IPI_COUNTERS]
    return {
        "control_raw": hex(control),
        "field_0": (control >> 5) & 1,
        "field_1": (control >> 6) & 7,
        "field_2": control & 15,
        "counter_words_raw": words,
        "counters_23bit": [word & 0x7FFFFF for word in words],
    }


def icap_snapshot(dev):
    words = {hex(address): dev.rr(address) for address in ICAP_REGISTERS}
    return {
        "registers_raw": words,
        "phy_registers_raw": {hex(address): dev.rr(address) for address in ICAP_PHY_REGISTERS},
        "active_bit": (words[hex(ICAP_CONTROL)] >> 1) & 1,
    }
