# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research.cfo_crosscheck_probe import VECTOR_ADDRESSES, compare, decode_cached_fields, snapshot


def encode(raw, bw=0, snr=0):
    raw &= 0xFFFFF
    return bw << 8, ((raw & 8191) << 19) | (snr << 13), raw >> 13


@pytest.mark.parametrize("raw", [0, 1, -1, 23948, -23948, 524287, -524288])
def test_signed20_and_20mhz_integer_conversion(raw):
    fields = decode_cached_fields(*encode(raw, snr=27))
    assert fields["raw_signed20"] == raw
    assert fields["firmware_integer_factor"] == 19
    assert fields["firmware_frequency_offset_s32"] == (raw * 19) // 16
    assert fields["firmware_snr_field"] == 27


def test_bandwidth_conversion_is_instruction_order_not_float_rounding():
    for bw, factor in enumerate((19, 38, 76, 152)):
        fields = decode_cached_fields(*encode(1000, bw=bw))
        assert fields["firmware_integer_factor"] == factor
        assert fields["firmware_frequency_offset_s32"] == (1000 * factor) // 16


def test_live_vector_example():
    # Only the identified bitfields from the live sample; other bits removed.
    fields = decode_cached_fields(0, 329474048, 125)
    assert fields["raw_signed20"] == -23948
    assert fields["firmware_frequency_offset_u32"] == 4294938857
    assert fields["firmware_snr_field"] == 27


@pytest.mark.parametrize("bad", [-1, 1 << 32, True, 1.0])
def test_reject_invalid_words(bad):
    with pytest.raises(ValueError, match="32-bit"):
        decode_cached_fields(0, bad, 0)


def test_snapshot_reads_only_three_identified_words():
    class Device:
        CHIP = "mt7921"

        def __init__(self):
            self.addresses = []

        def rr(self, address):
            self.addresses.append(address)
            return 0

    dev = Device()
    snapshot(dev)
    assert tuple(dev.addresses) == VECTOR_ADDRESSES
    dev.CHIP = "mt7925"
    with pytest.raises(ValueError, match="MT7961"):
        snapshot(dev)
    assert tuple(dev.addresses) == VECTOR_ADDRESSES


def test_comparison_excludes_wrong_band_or_changed_cache():
    fields = decode_cached_fields(*encode(-23948, snr=27))
    words = [0] * 66
    words[19], words[49] = 4294938857, 27
    stats = {"body_bytes": 300, "reported_band_u32": 0, "candidate_prefix_words_le": words}
    assert compare(fields, fields, stats)["frequency_offset_exact_match"] is True
    assert compare(fields, fields, stats)["snr_exact_match"] is True
    for band in (1, 2, 100, None):
        assert "frequency_offset_exact_match" not in compare(
            fields, fields, stats | {"reported_band_u32": band}
        )
    assert "frequency_offset_exact_match" not in compare(
        fields, fields | {"raw_signed20": 0}, stats
    )
    with pytest.raises(ValueError, match="300-byte"):
        compare(fields, fields, {})
