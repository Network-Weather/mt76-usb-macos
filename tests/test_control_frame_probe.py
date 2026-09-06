# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
from types import SimpleNamespace

import pytest

from research import control_frame_probe as p

NONCE = b"12345678"


@pytest.mark.parametrize(
    ("kind", "size", "fc"), [("rts", 16, 0xB4), ("cts", 10, 0xC4), ("ack", 10, 0xD4)]
)
def test_short_control_layout(kind, size, fc):
    payload = p.frame(kind, 2, NONCE)
    assert len(payload) == size
    assert struct.unpack_from("<HH", payload) == (fc, 0)
    assert payload[4:10] == b"\x021234\x02"
    assert payload[4] & 3 == 2
    if kind == "rts":
        assert payload[10:] == p.d.SOURCE
    assert p.frame(kind, 3, NONCE) != payload
    assert p.frame(kind, 2, b"abcdefgh") != payload


@pytest.mark.parametrize("kind", ["probe", "rts", "cts", "ack"])
def test_descriptor_header_type_duration_and_status(kind):
    dev = SimpleNamespace(CHIP=p.m.CHIP_MT7925)
    raw, payload = p.descriptor(dev, kind, 2, NONCE, "ofdm6")
    words = struct.unpack("<16I", raw)
    assert words[0] & 65535 == len(payload) + 64
    assert (words[1] >> 16) & 31 == (12 if kind == "probe" else len(payload) // 2)
    assert words[2] & (1 << 12)  # SW duration control
    assert words[2] & 63 == {"probe": 4, "rts": 0x1B, "cts": 0x1C, "ack": 0x1D}[kind]
    assert words[3] & 1  # no ACK requested, including RTS
    assert words[3] & (1 << 28)  # no BA
    assert words[5] & 255 == 18
    assert words[5] & (1 << 10)
    if kind != "probe":
        assert words[3] & ((1 << 31) | (4095 << 16) | (1 << 4)) == 0
    assert words[6] & (1 << 3)  # MAT disabled
    assert words[6] & (1 << 15) == 0  # no timestamp insertion


def test_plan_and_rates_are_bounded():
    assert p.PLAN == ("probe", "rts", "cts", "ack", "probe")
    assert p.RATES == {"ofdm6": 0x4B, "cck1": 0}
    assert set(p.FILTERS) == {0x820E5000, 0x820E5004}
    assert p.filter_value(0x820E5000, 0xFFFFFFFF - 1, 0) == 0xFFFF3FFE
    assert p.filter_value(0x820E5004, 0x12345678, 0) == 0x12345668


@pytest.mark.parametrize(
    ("kind", "sequence", "nonce"),
    [
        ("bar", 0, NONCE),
        ("rts", 20, NONCE),
        ("cts", -1, NONCE),
        ("ack", True, NONCE),
        ("ack", 0, b"short"),
    ],
)
def test_invalid_frames_refused(kind, sequence, nonce):
    with pytest.raises(ValueError):  # noqa: PT011 — tests both field-validation branches
        p.frame(kind, sequence, nonce)


def test_invalid_descriptor_and_filter_refused():
    with pytest.raises(ValueError, match="pinned legacy-rate"):
        p.descriptor(SimpleNamespace(CHIP="unsupported"), "rts", 0, NONCE, "ofdm6")
    with pytest.raises(ValueError, match="pinned legacy-rate"):
        p.descriptor(SimpleNamespace(CHIP=p.m.CHIP_MT7925), "rts", 0, NONCE, "ht8")
    for address, word, bits in (
        (0x820E5008, 0, 0),
        (0x820E5004, 0, 1),
        (0x820E5000, 0xFFFFFFFF, 0),
    ):
        with pytest.raises(ValueError, match="source-defined control-filter"):
            p.filter_value(address, word, bits)


@pytest.mark.parametrize("kind", ["probe", "rts", "cts", "ack"])
def test_old_descriptor_uses_connac2_fields(kind):
    dev = p.m.device_class_for(p.m.CHIP_MT7921)()
    raw, payload = p.descriptor(dev, kind, 2, NONCE, "cck1")
    words = struct.unpack("<16I", raw)
    assert words[0] & 65535 == len(payload) + 64
    assert (words[1] >> 11) & 31 == (12 if kind == "probe" else len(payload) // 2)
    assert words[2] & (1 << 12)
    assert words[2] & (1 << 13)  # source fixed-rate mgmt/control HTC bit retained
    assert words[8] & 63 == words[2] & 63
    assert words[5] & 255 == 18
    assert words[3] & 1
    if kind != "probe":
        assert words[2] & (1 << 10) == 0
        assert words[3] & ((1 << 31) | (4095 << 16)) == 0
