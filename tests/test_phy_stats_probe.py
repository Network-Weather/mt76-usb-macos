# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import phy_stats_probe as p


@pytest.mark.parametrize("offset", range(0, 40, 4))
def test_only_identified_aligned_phy_words(offset):
    assert p.request(offset) == struct.pack("<B3xII", 2, 41, offset)


@pytest.mark.parametrize("offset", [-4, 1, 37, 40, True, 0.0])
def test_bad_phy_offsets(offset):
    with pytest.raises(ValueError, match="aligned"):
        p.request(offset)


def test_scalar_tail_is_discarded_and_range_checked():
    assert p.scalar(struct.pack("<4I", 41, 65535, 0xDEADBEEF, 0xABCDEF01)) == 65535
    for body in (b"", struct.pack("<II", 40, 0), struct.pack("<II", 41, 65536)):
        with pytest.raises(ValueError, match="PHY"):
            p.scalar(body)


def test_register_extraction_matches_firmware_order():
    class Device:
        CHIP = p.m.CHIP_MT7921

        def rr(self, address):
            index = p.REGISTERS.index(address)
            return 2 * index | ((2 * index + 1) << 16)

    assert p.hardware_snapshot(Device()) == dict(zip(p.COUNTER_NAMES, range(10), strict=True))
