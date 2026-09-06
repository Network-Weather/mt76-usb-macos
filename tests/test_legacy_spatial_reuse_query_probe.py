# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import legacy_spatial_reuse_query_probe as p


def event(body, sequence=7, ext=0xA8):
    raw = bytearray(36)
    struct.pack_into("<I", raw, 0, p.m.PKT_TYPE_RX_EVENT << 27 | (36 + len(body)))
    raw[28], raw[29], raw[32] = 0xED, sequence, ext
    return bytes(raw) + body + b"private USB tail"


def test_pinned20_capability_not_old12_layout():
    assert p.request(15) == bytes([15]) + bytes(19)
    raw = event(bytes([1]) + bytes(7) + bytes([1, 0] * 10))
    result = p.summarize(raw, 7, 15)
    assert len(result["capability_flags_pinned20"]) == 20
    assert "private" not in repr(result)
    assert p.summarize(event(bytes([1]) + bytes(19)), 7, 15)["unrecognized_shape"]


def test_indicators_include_legacy_rcpi_prefix_and_padding():
    assert p.request(18) == bytes([18]) + bytes(31)
    raw = event(
        bytes([4]) + bytes(7) + struct.pack("<BB6H2x2I", 60, 61, 1, 2, 3, 4, 5, 6, 70000, 80000)
    )
    result = p.summarize(raw, 7, 18)
    assert result["non_srg_inter_ppdu_rcpi_raw"] == 60
    assert result["indicators_raw"]["inter_bss_ppdu"] == 4
    assert result["indicators_raw"]["sr_ampdu_mpdu_acked"] == 80000
    assert p.summarize(raw, 8, 18) is None


@pytest.mark.parametrize("subcommand", [1, 4, 13, 14, True, 15.0, 0xC9])
def test_only_get_subcommands(subcommand):
    with pytest.raises(ValueError, match="GET15/18"):
        p.request(subcommand)


def test_result_status_and_nonboolean_rejection():
    assert p.summarize(event(struct.pack("<2I", 0xA8, 0), ext=0), 7, 15) == {
        "command_result_status": 0
    }
    with pytest.raises(ValueError, match="non-boolean"):
        p.summarize(event(bytes([1]) + bytes(7) + bytes([2] * 20)), 7, 15)


def test_chip_guard_before_io():
    class Device:
        CHIP = p.m.CHIP_MT7925

    with pytest.raises(ValueError, match="MT7961"):
        p.query(Device(), 15)
