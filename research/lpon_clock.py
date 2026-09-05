# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read-only band0 LPON free-running-counter candidate on tested MT792x.

Offset37c is source-defined for related MT7916/MT7996. On the tested MT7961
and MT7925 builds it advances near1MHz, but is NOT the RXD/TXS epoch or TSF.
No counter reset, latch request or clock-setting writes are performed.
"""

import time

import mt7921u as m

LPON_COUNTER = 0x820EB37C


def read_counter(dev):
    if dev.CHIP not in (m.CHIP_MT7921, m.CHIP_MT7925):
        raise ValueError("LPON counter requires a known MT792x chip")
    before = time.monotonic()
    value = dev.rr(LPON_COUNTER)
    after = time.monotonic()
    if type(value) is not int or not 0 <= value < 0xFFFFFFFF:
        raise ValueError("invalid LPON counter word")
    return {"value_raw": value, "host_before_seconds": before, "host_after_seconds": after}
