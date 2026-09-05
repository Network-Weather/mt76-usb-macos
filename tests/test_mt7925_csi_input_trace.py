# SPDX-License-Identifier: BSD-3-Clause-Clear
import hashlib

import pytest

from research import mt7925_csi_input_trace as p


class Device:
    CHIP = p.m.CHIP_MT7925

    def __init__(self):
        self.reads = []

    def rr(self, address):
        self.reads.append(address)
        return 0


def test_fixed_bounded_code_only_windows():
    dev = Device()
    rows = p.verify(dev)
    assert len(rows) == 10
    assert len(dev.reads) == 1176
    assert len(set(dev.reads)) == 1173  # adjacent eligibility/metadata windows overlap12 bytes
    assert {a for a in dev.reads if dev.reads.count(a) == 2} == {
        0xE0060D00,
        0xE0060D04,
        0xE0060D08,
    }
    assert all(a % 4 == 0 for a in dev.reads)
    assert all(0xE0026C00 <= a < 0xE0026C00 + 594896 or 0x9171E8 <= a < 0x9181E8 for a in dev.reads)
    assert not any(row["matches"] for row in rows)
    assert all(
        set(row) == {"name", "address", "bytes", "sha256", "expected_sha256", "matches"}
        for row in rows
    )
    assert sum(row["bytes"] for row in rows) == 4704


def test_hash_success_with_synthetic_fixture(monkeypatch):
    monkeypatch.setattr(
        p, "WINDOWS", (("fixture", 0xE0061390, 4, hashlib.sha256(bytes(4)).hexdigest()),)
    )
    assert p.verify(Device())[0]["matches"]


def test_wrong_chip_refused_before_reads():
    dev = Device()
    dev.CHIP = p.m.CHIP_MT7921
    with pytest.raises(ValueError, match="MT7925 CSI code"):
        p.verify(dev)
    assert not dev.reads


@pytest.mark.parametrize("word", [-1, 1 << 32, None, True])
def test_invalid_read_refused(word):
    dev = Device()
    dev.rr = lambda _: word
    with pytest.raises(ValueError, match="invalid instruction read"):
        p.verify(dev)


def test_wrong_image_refused():
    with pytest.raises(ValueError, match="pinned MT7925"):
        p.check_image(b"not the firmware")
