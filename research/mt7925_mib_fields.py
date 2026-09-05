# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Two pinned MT7925 UNI22 counter mappings, independently resolved through ROM.

Not a general MIB API. Direct reads consume hardware samples and compete with
firmware accumulation. No writes; the caller must own the counter stream.
"""

import mt7921u as m

INTERNAL_IDS = {0: 49, 2: 119}
REGISTERS = {0: 0x820ED7F0, 2: 0x820ED9A8}
FIELD_TABLES = {0: 0x8555F0, 2: 0x8554D8}


def field_key(offset):
    """Reproduce ROM8334a6's band0 key deposit for only the two traced IDs."""
    if type(offset) is not int or offset not in INTERNAL_IDS:
        raise ValueError("only traced UNI offsets 0 and 2 allowed")
    return ((INTERNAL_IDS[offset] + 0x3E810) & 0xFFFF) << 5


def resolve_field(read_word, offset):
    """Verify the exact ROM descriptor without reading the hardware counter."""
    key = field_key(offset)
    entry = 0x84D79C + 8 * ((key & 0xFFFF) >> 5)
    pointer = read_word(entry)
    descriptor = read_word(entry + 4)
    if pointer != FIELD_TABLES[offset] or descriptor != 0x10000 | (REGISTERS[offset] & 0xFFFF):
        raise ValueError("unexpected pinned ROM MIB descriptor")
    if read_word(pointer) & 0xFFFF != 0x1F00:
        raise ValueError("unexpected pinned ROM MIB bit pair")
    return {
        "wire_offset": offset,
        "internal_id": INTERNAL_IDS[offset],
        "key": hex(key),
        "table_entry": hex(entry),
        "field_table": hex(pointer),
        "register": hex(REGISTERS[offset]),
        "low_bit": 0,
        "high_bit": 31,
    }


def paired_sample(dev):
    """Consume two consecutive samples per counter; do not subtract them."""
    if dev.CHIP != m.CHIP_MT7925:
        raise ValueError("MT7925-only MIB registers")
    result = {}
    for offset, address in REGISTERS.items():
        values = []
        for _ in range(2):
            word = dev.rr(address)
            if type(word) is not int or not 0 <= word < 0xFFFFFFFF:
                raise ValueError("invalid or ambiguous MIB counter word")
            values.append(word)
        result[offset] = {"address": hex(address), "paired_raw": values}
    return result
