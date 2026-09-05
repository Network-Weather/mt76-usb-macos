# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import legacy_ics_probe as p


def test_source_ce_request_has_no_uni_wrapper():
    raw = p.request(True)
    assert len(raw) == 84
    assert raw[:8] == bytes([0, 1, 0, 0, 2, 0, 0, 0])
    assert struct.unpack_from("<7H", raw, 8) == (1, 0, 0, 0, 0, 0, 0)
    assert raw[22:] == bytes(62)
    assert p.request(False)[1] == 0
    with pytest.raises(ValueError, match="boolean"):
        p.request(1)


def test_exact_legacy_mask_restore_preserves_other_bits():
    class Device:
        CHIP = p.m.CHIP_MT7921

        def __init__(self):
            self.words = {a: mask | 0x80000000 for a, mask in p.MASKS.items()}

        def rr(self, a):
            return self.words[a]

        def wr(self, a, value):
            self.words[a] = value

    dev = Device()
    assert all(p.restore(dev, dict.fromkeys(p.MASKS, 0)).values())
    assert set(dev.words.values()) == {0x80000000}
    with pytest.raises(ValueError, match="legacy"):
        p.restore(dev, {0x820E0000: 0})


def test_verification_rejects_wrong_chip_and_pins_relocated_slot():
    class Device:
        CHIP = p.m.CHIP_MT7925

    with pytest.raises(ValueError, match="MT7961"):
        p.verify(Device())
    assert p.TABLE_WORDS[0x02025EEC + 0x44C] == 0x93
    assert all(a % 4 == size % 4 == 0 for a, size, _ in p.WINDOWS)
