# SPDX-License-Identifier: BSD-3-Clause-Clear
import sys

import pytest

from research import mt7925_subchannel_probe as p


def test_only_mapped_source_offsets_no_unmapped_secondary160():
    assert len(p.OFFSETS) == len(set(p.OFFSETS)) == 23
    assert 94 not in p.OFFSETS
    assert set(p.OFFSETS) == {
        0,
        2,
        7,
        11,
        12,
        13,
        17,
        18,
        19,
        20,
        52,
        84,
        91,
        92,
        93,
        *range(95, 103),
    }


@pytest.mark.parametrize(
    ("width", "active", "cca"),
    [(20, 1, set()), (40, 2, {91}), (80, 4, {91, 92}), (160, 8, {91, 92, 93})],
)
def test_width_gates_inactive_artifacts_without_channel_or_unit_claims(width, active, cca):
    delta = dict.fromkeys(p.OFFSETS, 1000000)
    delta[7] = 65535
    result = p.width_summary(delta, width)
    assert set(result["ed_enabled_width_indices"]) == set(range(active))
    assert set(result["ed_outside_enabled_width_indices"]) == set(range(active, 8))
    assert set(result["secondary_cca_within_width"]) == cca
    assert result["idle_at_16bit_limit"]
    assert not result["physical_channel_mapping_validated"]
    assert "raw" in result["units"]


@pytest.mark.parametrize("width", [True, 0, 10, 320, "80"])
def test_unsupported_width_fails(width):
    with pytest.raises(ValueError, match="only tested"):
        p.width_summary({}, width)


def test_idle_below_limit():
    assert not p.width_summary(dict.fromkeys(p.OFFSETS, 42), 20)["idle_at_16bit_limit"]


def test_cli_requires_opt_in_before_usb(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["probe"])
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("unexpected USB open"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2
