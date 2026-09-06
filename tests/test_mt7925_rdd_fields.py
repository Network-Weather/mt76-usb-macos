# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research import mt7925_rdd_fields as f


@pytest.mark.parametrize(
    ("key", "entry", "pointer", "offset", "pair", "mask"),
    [
        (0x2A0020, 0x84E7CC, 0x8558F8, 0x2004, 0x0806, "0x1c0"),
        (0x2D0000, 0x84E6E4, 0x8558D0, 0x5000, 0x0000, "0x1"),
        (0x2D0080, 0x84E704, 0x8558C0, 0x500C, 0x1F00, "0xffffffff"),
        (0x2D00E0, 0x84E71C, 0x8558B4, 0x5010, 0x1F00, "0xffffffff"),
        (0x2D01A0, 0x84E74C, 0x855894, 0x5014, 0x1F00, "0xffffffff"),
    ],
)
def test_independent_new_chip_descriptors(key, entry, pointer, offset, pair, mask):
    words = {entry: pointer, entry + 4: 0x10000 | offset, pointer: pair}
    result = f.resolve_field(words.__getitem__, key)
    assert result["mask"] == mask
    base = 0x83080000 if key >> 16 == 0x2A else 0x830A0000
    assert result["register"] == hex(base + offset)


@pytest.mark.parametrize("key", [True, -1, 0x240020, 0x2D0020])
def test_untraced_or_other_chip_keys_fail_before_read(key):
    with pytest.raises(ValueError, match="traced"):
        f.resolve_field(lambda _: pytest.fail("unexpected read"), key)


@pytest.mark.parametrize(
    ("pointer", "meta", "pair"),
    [(0x84CBBC, 0x12004, 0), (0x8558F8, 0x2004, 0), (0x8558F8, 0x12004, 0x2000)],
)
def test_unexpected_descriptor_or_range_rejected(pointer, meta, pair):
    words = {0x84E7CC: pointer, 0x84E7D0: meta, 0x8558F8: pair}
    with pytest.raises(ValueError, match="unexpected ROM"):
        f.resolve_field(words.__getitem__, 0x2A0020)


def test_snapshot_exact_read_set_and_chip_guard():
    class Device:
        CHIP = f.m.CHIP_MT7925

        def rr(self, address):
            return {
                0x83082004: 0x140,
                0x830A5000: 0x81,
                0x830A500C: 0x401C00,
                0x830A5010: 0x401E00,
                0x830A5014: 0x401C00,
            }[address]

    result = f.snapshot(Device())
    assert result["detector_mode_bits8_6"] == 5
    assert result["capture_field_2d0000"] == 1
    assert result["buffer_end"] == "0x401e00"
    Device.CHIP = f.m.CHIP_MT7921
    with pytest.raises(ValueError, match="MT7925-only"):
        f.snapshot(Device())


@pytest.mark.parametrize("word", [None, True, -1, 0xFFFFFFFF])
def test_bad_mmio_words_rejected(word):
    class Device:
        CHIP = f.m.CHIP_MT7925

        def rr(self, address):
            return word

    with pytest.raises(ValueError, match="invalid"):
        f.snapshot(Device())
