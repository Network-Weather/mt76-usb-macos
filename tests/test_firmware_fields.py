# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research.firmware_fields import (
    ICAP_CONTROL,
    IPI_CONTROL,
    icap_snapshot,
    ipi_snapshot,
    rdd_snapshot,
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


def test_rdd_phy_and_capture_domains_have_independent_tables():
    words = {
        0x84CB90: 0x84CBBC,
        0x84CB94: 0x00012004,
        0x84CBBC: 0x0806,
        0x84CA04: 0x84CAB0,
        0x84CA08: 0x0001500C,
        0x84CAB0: 0x1F00,
    }
    mode = resolve_field(words.__getitem__, 0x240020)
    assert mode["register"] == "0x83082004"
    assert mode["mask"] == "0x1c0"
    begin = resolve_field(words.__getitem__, 0x270080)
    assert begin["register"] == "0x830a500c"
    assert begin["mask"] == "0xffffffff"


def test_rdd_snapshot_is_chip_guarded_and_fixed_read_only():
    class Device:
        CHIP = "mt7921"

        def rr(self, address):
            assert address in (
                0x83082004,
                0x83080038,
                0x83080014,
                0x830A5000,
                0x830A5008,
                0x830A500C,
                0x830A5010,
                0x830A5014,
                0x830A2030,
            )
            return 0x140 if address == 0x83082004 else 0

    assert rdd_snapshot(Device())["detector_mode_bits8_6"] == 5
    Device.CHIP = "mt7925"
    with pytest.raises(ValueError, match="MT7961-only"):
        rdd_snapshot(Device())


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
