# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research.firmware_fields import (
    ICAP_CONTROL,
    IPI_CONTROL,
    icap_snapshot,
    ipi_snapshot,
    resolve_field,
)


def test_key_field_index_is_not_bit_number():
    words = {0x84D550: 0x84D650, 0x84D554: 0x00150090, 0x84D674: 0x01010000}
    result = resolve_field(words.__getitem__, 0x5A0013)
    assert result["register"] == "0x80021090"
    assert result["field_index"] == 19
    assert result["low_bit"] == result["high_bit"] == 1
    assert result["mask"] == "0x2"


def test_full_word_mask():
    words = {0x84D560: 0x84D648, 0x84D564: 0x00010098, 0x84D648: 0x1F00}
    assert resolve_field(words.__getitem__, 0x5A0040)["mask"] == "0xffffffff"


@pytest.mark.parametrize("key", [True, -1, 0x5AFFFF, 0x260003])
def test_untraced_keys_never_read(key):
    with pytest.raises(ValueError, match="traced"):
        resolve_field(lambda _: pytest.fail("unexpected read"), key)


@pytest.mark.parametrize(
    ("pointer", "meta", "pair"),
    [
        (0x2000000, 0x40000, 0),
        (0x84CB81, 0x40000, 0),
        (0x84CB80, 0, 0),
        (0x84CB80, 0x40000, 0x2000),
    ],
)
def test_bad_descriptor_stops(pointer, meta, pair):
    words = {0x84CAC4: pointer, 0x84CAC8: meta, 0x84CB80: pair}
    with pytest.raises(ValueError, match="unexpected ROM"):
        resolve_field(words.__getitem__, 0x260000)


def test_snapshots_are_fixed_register_reads():
    class Device:
        def rr(self, address):
            return {IPI_CONTROL: 0x121, ICAP_CONTROL: 2}.get(address, 0xFF800003)

    result = ipi_snapshot(Device())
    assert [result[f"field_{i}"] for i in range(3)] == [1, 4, 1]
    assert result["counters_23bit"] == [3] * 12
    assert icap_snapshot(Device())["active_bit"] == 1
