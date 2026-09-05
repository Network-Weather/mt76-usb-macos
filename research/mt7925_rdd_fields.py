# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Pinned MT7925 radar field map from ROM834812, not copied from MT7961.

Read-only research helpers. No buffer payloads, arbitrary keys or direct writes.
"""

import struct

import mt7921u as m

KEYS = (0x2A0020, 0x2D0000, 0x2D0080, 0x2D00E0, 0x2D01A0)
FIELD_TABLES = dict(zip(KEYS, (0x8558F8, 0x8558D0, 0x8558C0, 0x8558B4, 0x855894), strict=True))


def resolve_field(read_word, key):
    if type(key) is not int or key not in KEYS:
        raise ValueError("only traced MT7925 RDD keys allowed")
    table, base = {
        0x2A: (0x84E7C4, 0x83080000),
        0x2D: (0x84E6E4, 0x830A0000),
    }[key >> 16]
    entry = table + 8 * ((key & 0xFFFF) >> 5)
    pointer = read_word(entry)
    offset, count, _ = struct.unpack("<HBB", struct.pack("<I", read_word(entry + 4)))
    field = key & 31
    if pointer != FIELD_TABLES[key] or field >= count:
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
        "field_count": count,
        "low_bit": low,
        "high_bit": high,
        "mask": hex(((1 << (high - low + 1)) - 1) << low),
    }


def snapshot(dev):
    """Read only the five independently mapped band0 detector/ring registers."""
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925-only RDD registers")
    words = {}
    for address in (0x83082004, 0x830A5000, 0x830A500C, 0x830A5010, 0x830A5014):
        word = dev.rr(address)
        if type(word) is not int or not 0 <= word < 0xFFFFFFFF:
            raise ValueError("invalid RDD register word")
        words[address] = word
    return {
        "registers_raw": {hex(address): hex(word) for address, word in words.items()},
        "detector_mode_bits8_6": (words[0x83082004] >> 6) & 7,
        "capture_field_2d0000": words[0x830A5000] & 1,
        "buffer_begin": hex(words[0x830A500C]),
        "buffer_end": hex(words[0x830A5010]),
        "producer_word": hex(words[0x830A5014]),
    }
