# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research import mt7925_phy_compare_probe as p


def words(a=-70, b=-50, threshold_a=-60, threshold_b=-60, selector=3):
    return dict(
        zip(
            p.REGISTERS,
            (
                a & 255,
                b & 255,
                (threshold_a & 255) << 24 | (threshold_b & 255) << 16,
                selector << 18,
            ),
            strict=True,
        )
    )


def test_signed_comparison_is_or_and_includes_equality():
    assert p.decode(words())["either_input_at_least_threshold"]
    assert p.decode(words(a=-60, b=-70))["either_input_at_least_threshold"]
    assert not p.decode(words(a=-61, b=-61))["either_input_at_least_threshold"]


def test_threshold_zero_has_source_defined_fallback_not_input_zero():
    out = p.decode(words(a=0, threshold_a=0, threshold_b=0))
    assert out["input_raw_signed8"][0] == 0
    assert out["threshold_raw_signed8"] == [0, 0]
    assert out["threshold_effective_signed8"] == [-51, -51]


@pytest.mark.parametrize("selector", [0, 1, 2, 4, 15])
def test_only_selector_three_has_comparison(selector):
    out = p.decode(words(selector=selector))
    assert not out["comparison_available"]
    assert out["either_input_at_least_threshold"] is None


@pytest.mark.parametrize("value", [-1, 1 << 32, True, 0xFFFFFFFF])
def test_invalid_or_ambiguous_hardware_word(value):
    data = words()
    data[p.REGISTERS[0]] = value
    with pytest.raises(ValueError, match=r"unsigned32|ambiguous"):
        p.decode(data)


def test_exact_scope_and_nonphysical_labels():
    with pytest.raises(ValueError, match="exact four"):
        p.decode({})
    out = p.decode(words())
    assert not out["physical_units_validated"]
    assert not any(key in out for key in ("rssi", "noise_floor", "antenna", "interference"))
