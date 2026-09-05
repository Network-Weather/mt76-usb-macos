# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
from types import SimpleNamespace

import pytest

from research import mt7925_diagnostic_stats_probe as p


def test_basic_empty_is_not_zero_statistics():
    assert p.parse(p.request(0), 0) == {"tag": 0, "tlv_bytes": 4, "counters_available": False}


def test_diagnostic_offsets_and_private_pointer_exclusion():
    body = bytearray(204)
    struct.pack_into("<HHI", body, 4, 3, 200, 1)
    for i, (_, (at, _)) in enumerate(p.CACHE_FIELDS.items(), 1):
        struct.pack_into("<I", body, 4 + at, i)
    struct.pack_into("<I", body, 4 + 0x30, 11)
    struct.pack_into("<I", body, 4 + 0xAC, 0xDEADBEEF)
    out = p.parse(body, 3)
    assert list(out["cached_mac_counters"].values()) == list(range(1, 10))
    assert out["channel_state"]["primary"] == 11
    assert out["phy_section_zero_filled"]
    assert not out["phy_counters_available"]
    assert "deadbeef" not in str(out).lower()
    assert str(0xDEADBEEF) not in str(out)
    body[4 + 0x5C] = 1
    assert not p.parse(body, 3)["phy_section_zero_filled"]
    assert not p.parse(body, 3)["phy_counters_available"]


@pytest.mark.parametrize("body", [b"", bytes(7), struct.pack("<4xHH", 3, 4), bytes(204)])
def test_malformed_or_unexpected_replies_rejected(body):
    with pytest.raises(ValueError, match=r"statistics|pinned"):
        p.parse(body, 3)


@pytest.mark.parametrize("tag", [1, 2, 6, 0x80, True])
def test_only_traced_non_peer_requests(tag):
    with pytest.raises(ValueError, match="basic0"):
        p.request(tag)


def test_cache_reads_only_nine_exact_software_words():
    addresses = []
    dev = SimpleNamespace(CHIP=p.m.CHIP_MT7925, rr=lambda a: addresses.append(a) or 0)
    p.snapshot(dev)
    assert addresses == [0x224C408 + offset for _, offset in p.CACHE_FIELDS.values()]
    assert all(a < 0x80000000 for a in addresses)


@pytest.mark.parametrize(("suite", "tag"), [("basic-repeat", 0), ("diagnostic-repeat", 3)])
def test_repeat_suites_hold_channel_and_tag_fixed(suite, tag):
    assert p.plan(suite) == ((6, tag),) * 6
    assert len(p.plan("channel")) == 6
    with pytest.raises(ValueError, match="bounded"):
        p.plan("sweep")


def test_three_four_boundary_is_exact_and_no_extra_tag():
    assert p.plan("diagnostic-three") == ((6, 3),) * 3
    assert p.plan("diagnostic-four") == ((6, 3),) * 4


def test_only_three_release_list_counters_are_read():
    addresses = []
    dev = SimpleNamespace(CHIP=p.m.CHIP_MT7925, rr=lambda a: addresses.append(a) or 4)
    assert set(p.pool_counts(dev).values()) == {4}
    assert addresses == [0x222EFC0, 0x222ED84, 0x222E238]
