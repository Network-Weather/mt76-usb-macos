# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Bounded MT7925 fixed-rate table read, from ROM83c14e..83c174.

Writes only the volatile indirect-read selector, not a table entry. Caller must
serialize with all other table users. Only the two previously exercised slots
are allowed. No firmware bytes, peer entries, profiles or power tables read.
"""

import mt7921u as m
from research.mt7925_tx_probe import ITCR, ITDR0, ITDR1


def read_slot(dev, index):
    if dev.CHIP != m.CHIP_MT7925 or type(index) is not int or index not in (18, 25):
        raise ValueError("MT7925 fixed-rate read permits only slots18/25")
    # ROM writes EXEC | index, OP16=0 / SELECT25:24=0, then reads both data
    # registers. It does not use ITCR readback as a completion/index witness.
    dev.wr(ITCR, (1 << 31) | index)
    words = (dev.rr(ITDR0), dev.rr(ITDR1))
    if any(type(w) is not int or not 0 <= w <= 0xFFFFFFFF for w in words):
        raise ValueError("invalid indirect table data")
    if words == (0xFFFFFFFF, 0xFFFFFFFF):
        raise ValueError("all-ones indirect table data")
    return words
