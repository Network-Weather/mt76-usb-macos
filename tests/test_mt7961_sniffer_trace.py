# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import mt7961_sniffer_trace as p


class Device:
    CHIP = p.m.CHIP_MT7921

    def __init__(self):
        self.reads = []

    def rr(self, address):
        self.reads.append(address)
        return {p.TABLE_ADDRESS: 0x24, p.TABLE_ADDRESS + 4: 0x00923D54}.get(address, 7)


def test_exact_bounded_window_and_no_code_export():
    dev = Device()
    result = p.verify(dev, struct.pack("<I", 7) * (p.CODE_LENGTH // 4))
    assert result["code_matches_pinned_image"]
    assert len(dev.reads) == 70
    assert all(address % 4 == 0 for address in dev.reads)
    assert "code" not in result
    assert "bytes" not in result


def test_code_mismatch_is_explicit():
    assert not p.verify(Device(), bytes(p.CODE_LENGTH))["code_matches_pinned_image"]


def test_wrong_chip_refused_before_reads():
    dev = Device()
    dev.CHIP = p.m.CHIP_MT7925
    with pytest.raises(ValueError, match="MT7961 and exact bounded"):
        p.verify(dev, bytes(p.CODE_LENGTH))
    assert not dev.reads


def test_wrong_length_refused_before_reads():
    dev = Device()
    with pytest.raises(ValueError, match="MT7961 and exact bounded"):
        p.verify(dev, bytes(p.CODE_LENGTH + 4))
    assert not dev.reads


def test_wrong_table_refused_before_instruction_reads():
    dev = Device()
    dev.rr = lambda address: 0
    with pytest.raises(ValueError, match="dispatcher slot differs"):
        p.verify(dev, bytes(p.CODE_LENGTH))


def test_unpinned_image_refused():
    with pytest.raises(ValueError, match="pinned MT7961"):
        p.expected_code(b"unrecognized firmware")
