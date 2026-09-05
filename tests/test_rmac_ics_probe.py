# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import rmac_ics_probe as p


def test_source_request_layout():
    raw = p.request(True)
    assert len(raw) == 92
    assert raw[:8] == struct.pack("<4xHH", 0, 88)
    assert raw[8:16] == bytes([0, 1, 0, 0, 2, 0, 0, 0])
    assert struct.unpack_from("<7H", raw, 16) == (1, 0, 0, 0, 0, 0, 0)
    assert raw[30:] == bytes(62)
    assert p.request(False)[9] == 0
    with pytest.raises(ValueError, match="boolean"):
        p.request(1)


@pytest.mark.parametrize("kind", [12, 13])
def test_shape_never_exports_payload_or_fid(kind):
    raw = struct.pack("<IHH", 16 | (3 << 16) | (kind << 27), 0, 0x1234)
    raw += b"private!" + b"usb padding"
    assert p.aggregate_shape(raw) == {"type": kind, "bytes": 16, "frame_count": 3}


@pytest.mark.parametrize("length", [0, 7, 17, 65535])
def test_bad_lengths(length):
    raw = struct.pack("<I", length | (12 << 27)) + bytes(12)
    with pytest.raises(ValueError, match="length"):
        p.aggregate_shape(raw)


def test_not_ics():
    assert p.aggregate_shape(bytes(7)) is None
    assert p.aggregate_shape(struct.pack("<I", 16 | (2 << 27)) + bytes(12)) is None


def test_restore_only_two_masks():
    class Device:
        CHIP = p.m.CHIP_MT7925

        def __init__(self):
            self.words = {0x820E50D0: 0x1235, 0x820E705C: 0x11000000}

        def rr(self, a):
            return self.words[a]

        def wr(self, a, v):
            self.words[a] = v

    dev = Device()
    assert all(p.restore(dev, dict.fromkeys(p.MASKS, 0)).values())
    assert dev.words == {0x820E50D0: 0x1234, 0x820E705C: 0x10000000}
    with pytest.raises(ValueError, match="pinned"):
        p.restore(dev, {0xDEADBEEF: 0})
