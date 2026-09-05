# SPDX-License-Identifier: BSD-3-Clause-Clear
import hashlib

import pytest

from research import ics_trace_probe as p


class Device:
    CHIP = p.m.CHIP_MT7925

    def __init__(self, words=None):
        self.words = words or {}
        self.reads = []

    def rr(self, address):
        self.reads.append(address)
        return self.words.get(address, 0)


def test_snapshot_fixed_reads_and_masks():
    dev = Device({0x81031000: 0x8C600013, 0x82023090: 0x402, 0x82024090: 0x400})
    result = p.snapshot(dev)
    assert dev.reads == list(p.STATE_ADDRESSES)
    assert result["prerequisite_bit27"] == 1
    assert result["capture_trigger_bits"] == [1, 0]
    assert "local_only_hex" not in str(result)


def test_wrong_image_stops_before_metadata():
    dev = Device()
    with pytest.raises(ValueError, match="code mismatch"):
        p.verify(dev)
    assert len(dev.reads) == 1470
    assert all(a not in dev.reads for a in p.METADATA)


def test_verified_metadata_no_pointer_chasing(monkeypatch):
    monkeypatch.setattr(
        p, "WINDOWS", (("fixture", 0x900000, 4, hashlib.sha256(bytes(4)).hexdigest()),)
    )
    words = dict(p.METADATA)
    words[0x221C07C] |= 0xAAAA0000
    dev = Device(words)
    assert p.verify(dev)["metadata"]["0x221c07c"] == "0x49"
    assert dev.reads == [0x900000, *p.METADATA]


def test_metadata_mismatch_stops_without_following_pointer(monkeypatch):
    monkeypatch.setattr(p, "WINDOWS", ())
    dev = Device({0x221C07C: 0x49, 0x221C080: 0xDEADBEEF})
    with pytest.raises(ValueError, match="metadata mismatch"):
        p.verify(dev)
    assert dev.reads == [0x221C07C, 0x221C080]


def test_metadata_field_pairs():
    assert p.METADATA[0x84D1F8].to_bytes(4, "little")[2:] == bytes([27, 27])
    assert p.METADATA[0x84F188].to_bytes(4, "little")[:2] == bytes([10, 10])
    assert p.METADATA[0x84F18C].to_bytes(4, "little")[2:] == bytes([1, 1])


def test_reads_are_aligned_and_do_not_include_sram():
    assert all(a % 4 == 0 for a in (*p.METADATA, *p.STATE_ADDRESSES))
    assert all(size % 4 == 0 and a % 4 == 0 for _, a, size, _ in p.WINDOWS)
    assert not any(0x418000 <= a < 0x41C000 for a in p.STATE_ADDRESSES)
