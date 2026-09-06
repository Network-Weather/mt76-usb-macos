# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Pinned RF-init five-field control; no address, buffer or mask CLI."""

import hashlib
import struct

from research import legacy_ics_probe as legacy
from research.txpower_register_probe import m

REGISTER = 0x820E7050
FIELDS = ((0, 6), (8, 12), (13, 15), (16, 27), (30, 31))
MASK = sum(((1 << (hi - lo + 1)) - 1) << lo for lo, hi in FIELDS)
NORMAL, RF = 0x4001442F, 0x4000427F
WINDOWS = (
    (0x82DE58, 192, "21ba8c1420210be15aec59dddd047a64c24e87d9fb35e7bd48ce3f66e62ec925"),
    (0x94BE50, 108, "887b809f8406b9641bb3e1b11f45c39a4bcd9d3bc07079f06cc9b91341bb9195"),
)


def verify(dev):
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("old-chip DMA setup only")
    for address, expected in ((0x2014F14, 0x2013898), (0x2013898, 0x82DE58), (0x84C24C, 0x84C2B0)):
        if legacy.valid_word(dev.rr(address)) != expected:
            raise ValueError("DMA mapper pointer mismatch")
    if legacy.valid_word(dev.rr(0x84C250)) & 0xFFFFFF != (5 << 16) | 0x50:
        raise ValueError("DMA field descriptor mismatch")
    for index, (lo, hi) in enumerate(FIELDS):
        address = 0x84C2B0 + index * 2
        pair = (legacy.valid_word(dev.rr(address & ~3)) >> ((address & 3) * 8)) & 65535
        if pair != lo | hi << 8:
            raise ValueError("DMA bit-pair mismatch")
    hashes = []
    for address, size, expected in WINDOWS:
        raw = b"".join(
            struct.pack("<I", legacy.valid_word(dev.rr(a)))
            for a in range(address, address + size, 4)
        )
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected:
            raise ValueError("DMA pinned code mismatch")
        hashes.append({"base": hex(address), "bytes": size, "sha256": digest})
    return {"register": hex(REGISTER), "mask": hex(MASK), "fields": FIELDS, "windows": hashes}


def apply(dev, mode):
    if dev.CHIP != m.CHIP_MT7921 or mode not in ("normal", "rf_setup"):
        raise ValueError("only pinned normal/RF setup")
    before = legacy.valid_word(dev.rr(REGISTER))
    value = NORMAL if mode == "normal" else RF
    dev.wr(REGISTER, (before & ~MASK) | value)
    after = legacy.valid_word(dev.rr(REGISTER))
    if after & MASK != value:
        raise RuntimeError("DMA setup readback failed")
    return {"before": hex(before), "after": hex(after), "mode": mode}
