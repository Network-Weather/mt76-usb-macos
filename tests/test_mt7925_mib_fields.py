# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research import mt7925_mib_fields as f


@pytest.mark.parametrize(
    ("offset", "key", "entry"), [(0, 0x1D0820, 0x84D9A4), (2, 0x1D10E0, 0x84DBD4)]
)
def test_resolve_two_observed_fields(offset, key, entry):
    words = {
        entry: f.FIELD_TABLES[offset],
        entry + 4: 0x10000 | (f.REGISTERS[offset] & 65535),
        f.FIELD_TABLES[offset]: 0x1F00,
    }
    assert f.field_key(offset) == key
    result = f.resolve_field(words.__getitem__, offset)
    assert result["register"] == hex(f.REGISTERS[offset])
    assert result["high_bit"] == 31


@pytest.mark.parametrize("offset", [True, -1, 1, 7, 119, "0"])
def test_untraced_offsets_rejected_without_reads(offset):
    with pytest.raises(ValueError, match="only traced"):
        f.resolve_field(lambda _: pytest.fail("unexpected read"), offset)


@pytest.mark.parametrize(
    ("pointer", "desc", "pair"),
    [(0x8555F4, 0x107F0, 0x1F00), (0x8555F0, 0x10760, 0x1F00), (0x8555F0, 0x107F0, 0x1F10)],
)
def test_mapping_change_rejected(pointer, desc, pair):
    words = {0x84D9A4: pointer, 0x84D9A8: desc, 0x8555F0: pair}
    with pytest.raises(ValueError, match="unexpected pinned"):
        f.resolve_field(words.__getitem__, 0)


def test_paired_read_order_and_no_subtraction():
    class Device:
        CHIP = f.m.CHIP_MT7925

        def __init__(self):
            self.calls = []
            self.values = iter([20, 1, 100, 0])

        def rr(self, address):
            self.calls.append(address)
            return next(self.values)

    dev = Device()
    result = f.paired_sample(dev)
    assert result[0]["paired_raw"] == [20, 1]
    assert result[2]["paired_raw"] == [100, 0]
    assert dev.calls == [0x820ED7F0, 0x820ED7F0, 0x820ED9A8, 0x820ED9A8]
    dev.CHIP = f.m.CHIP_MT7921
    with pytest.raises(ValueError, match="MT7925-only"):
        f.paired_sample(dev)


@pytest.mark.parametrize("word", [None, True, -1, 0xFFFFFFFF, 0x100000000])
def test_bad_counter_rejected(word):
    class Device:
        CHIP = f.m.CHIP_MT7925

        def rr(self, _):
            return word

    with pytest.raises(ValueError, match="invalid or ambiguous"):
        f.paired_sample(Device())
