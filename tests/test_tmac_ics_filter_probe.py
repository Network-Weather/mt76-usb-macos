# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import tmac_ics_filter_probe as p


def test_filter_request_only_changes_action_operation_and_condition():
    raw = p.request(1)
    baseline = p.t.request(True)
    assert len(raw) == 92
    assert [i for i, (a, b) in enumerate(zip(raw, baseline, strict=True)) if a != b] == [9, 14, 16]
    assert raw[9] == 2
    assert raw[14] == 5
    assert struct.unpack_from("<7H", raw, 16) == (1, 0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize("mask", [True, -1, 2, 32, 65535])
def test_no_other_category_or_sweep(mask):
    with pytest.raises(ValueError, match="five traced"):
        p.request(mask)


def test_all_five_mask_does_not_touch_band_or_other_conditions():
    raw = p.request(31)
    assert struct.unpack_from("<7H", raw, 16) == (31, 0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    ("sequence", "fc", "length"), [(0, 0x40, 65), (1, 8, 47), (2, 0x40, 65), (3, 0x88, 49)]
)
def test_mixed_frames_are_bounded_existing_synthetic_classes(sequence, fc, length):
    class Device:
        CHIP = p.t.m.CHIP_MT7925

    payload, wire = p.mixed_packet(Device(), sequence, bytes(8))
    assert len(payload) == length
    assert struct.unpack_from("<H", payload)[0] == fc
    assert payload[2:4] == bytes(2)
    assert wire[68 : 68 + length] == payload
    assert struct.unpack_from("<I", wire, 12)[0] & (1 << 12)


def test_restore_preserves_enable_and_unrelated_bits():
    class Device:
        CHIP = p.t.m.CHIP_MT7925
        word = 0x80201F01

        def rr(self, address):
            assert address == 0x820E4120
            return self.word

        def wr(self, address, value):
            assert address == 0x820E4120
            self.word = value

    dev = Device()
    assert p.restore_filter(dev, 0x100)
    assert dev.word == 0x80200101
    with pytest.raises(ValueError, match="five traced"):
        p.restore_filter(dev, 1)
