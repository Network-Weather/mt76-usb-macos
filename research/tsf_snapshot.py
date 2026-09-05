# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Source-defined band0/OMAC0 TSF software-read snapshot, not a clock setter.

mt76 c5a3bd91 mt792x_get_tsf: set LPON_TCR low2 bits to3, read UTTR0/1.
Never writes UTTR or requests SW_WRITE mode1. Caller serializes USB ownership.
No assumption that this counter is the RXD/TXS clock or an absolute reference.
"""

import time

import mt7921u as m

TCR0, UTTR0, UTTR1 = 0x820EB0A8, 0x820EB080, 0x820EB084


def snapshot(dev):
    if dev.CHIP not in (m.CHIP_MT7921, m.CHIP_MT7925):
        raise ValueError("snapshot requires a known MT792x chip")
    before = dev.rr(TCR0)
    if type(before) is not int or not 0 <= before < 0xFFFFFFFF or before & 3 not in (0, 3):
        raise ValueError("invalid or busy TSF snapshot control")
    start = time.monotonic()
    dev.wr(TCR0, before | 3)
    write_done = time.monotonic()
    low, high = dev.rr(UTTR0), dev.rr(UTTR1)
    after = dev.rr(TCR0)
    end = time.monotonic()
    if any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in (low, high, after)):
        raise ValueError("invalid TSF snapshot data")
    # The read-mode bits remain3 on these dongles. Upstream repeatedly ORs3;
    # a self-clearing command bit is not specified and must not be assumed.
    if after & 3 not in (0, 3) or after == 0xFFFFFFFF or (low, high) == (0xFFFFFFFF, 0xFFFFFFFF):
        raise ValueError("invalid TSF snapshot read mode or data")
    return {
        "tsf_raw": (high << 32) | low,
        "control_before": hex(before),
        "control_after": hex(after),
        "read_mode_retained": (after & 3) == 3,
        "host_before_seconds": start,
        "host_write_done_seconds": write_done,
        "host_after_seconds": end,
    }
