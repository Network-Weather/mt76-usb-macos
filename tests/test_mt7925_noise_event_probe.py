# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import mt7925_noise_event_probe as p


def event():
    body = struct.pack("<4xHH22I", 2, 92, *range(22))
    raw = bytearray(44)
    struct.pack_into("<I", raw, 0, (p.m.PKT_TYPE_RX_EVENT << 27) | 140)
    raw[36] = 0x36
    return bytes(raw) + body + b"private USB padding"


def test_exact_request_and_event_no_padding_export():
    assert p.request().hex() == "0000000002000400"
    result = p.summarize(event())
    assert result["timer_index0"] == list(range(11))
    assert result["timer_index1"] == list(range(11, 22))
    assert "private" not in repr(result)


@pytest.mark.parametrize(("offset", "value"), [(36, 1), (37, 1), (44, 1), (48, 0), (50, 88)])
def test_wrong_event_rejected(offset, value):
    raw = bytearray(event())
    raw[offset] = value
    with pytest.raises(ValueError, match="noise event"):
        p.summarize(raw)


def test_truncated_and_normal_frame_not_exported():
    for raw in (b"", event()[:139], struct.pack("<I", (2 << 27) | 140) + event()[4:]):
        with pytest.raises(ValueError, match="noise event"):
            p.summarize(raw)


@pytest.mark.parametrize("address", list(p.MASKS))
def test_preserves_nonmask_bits(address):
    mask = p.MASKS[address]
    assert p.masked(address, 0xA5A55A5A, 0) == 0xA5A55A5A & ~mask
    assert p.masked(address, 0, mask) == mask
    with pytest.raises(ValueError, match="pinned histogram masks"):
        p.masked(address, 0, 0xFFFFFFFF)
    with pytest.raises(ValueError, match="pinned histogram masks"):
        p.masked(address, 0xFFFFFFFF, 0)


def test_no_other_address():
    with pytest.raises(ValueError, match="pinned histogram masks"):
        p.masked(0x83088234, 0, 0)


@pytest.mark.parametrize(("chip", "option"), [(p.m.CHIP_MT7921, 7), (p.m.CHIP_MT7925, 3)])
def test_wrong_chip_or_option_never_sends(chip, option):
    class Device:
        CHIP = chip

        def uni_option(self, *_):
            return option

        def mcu_uni(self, *_args, **_kwargs):
            pytest.fail("unexpected command")

    with pytest.raises(ValueError, match="SET/ACK"):
        p.activate(Device())


def test_send_does_not_wait_and_discard_sequence_zero():
    class Device:
        CHIP = p.m.CHIP_MT7925
        msg_seq = 7

        def uni_option(self, *_):
            return 7

        def mcu_uni(self, cid, body, **kwargs):
            assert cid == 0x36
            assert body == p.request()
            assert kwargs == {"query": False, "wait": False}

    assert p.activate(Device()) == 7
