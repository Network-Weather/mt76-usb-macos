# SPDX-License-Identifier: BSD-3-Clause-Clear
from types import SimpleNamespace

import pytest

from research import evm_cn_probe as p
from research import evm_cn_stimulus_probe as s


def test_fields_follow_firmware_byte_order_and_nine_bit_shift():
    assert p.fields((0x81 << 24) | (0x42 << 16) | (0x123 << 7) | 0x7F) == {
        "cn_raw_u9": 0x123,
        "evm_rx0_raw_u8": 0x81,
        "evm_rx1_raw_u8": 0x42,
    }
    assert p.fields(0)["cn_raw_u9"] == 0


@pytest.mark.parametrize("word", [True, -1, 0xFFFFFFFF, 1 << 32, 1.0])
def test_reject_bad_word(word):
    with pytest.raises(ValueError, match="CN/EVM"):
        p.fields(word)


def test_only_fixed_read_and_chip_guard():
    reads = []
    dev = SimpleNamespace(CHIP=p.m.CHIP_MT7921, rr=lambda a: reads.append(a) or 0)
    assert p.read(dev)["word"] == "0x0"
    assert reads == [0x83086088]
    dev.CHIP = p.m.CHIP_MT7925
    with pytest.raises(ValueError, match="MT7961"):
        p.read(dev)
    assert len(reads) == 1


def test_stimulus_order_nonce_and_twelve_frame_ceiling():
    assert s.PHASES == (("cck_before", 0), ("ht8_2ss", 0x488), ("cck_after", 0))
    nonce = b"\xdd\x0c\x02NW\x01" + bytes(8)
    frames = [s.frame_for(i, nonce) for i in range(12)]
    assert len(set(frames)) == 12
    assert all(frame.endswith(nonce) for frame in frames)


@pytest.mark.parametrize("sequence", [-1, 12, True, 0.0])
def test_stimulus_rejects_outside_fixed_batch(sequence):
    with pytest.raises(ValueError, match="twelve-frame"):
        s.frame_for(sequence, b"\xdd\x0c\x02NW\x01" + bytes(8))


def test_stimulus_requires_explicit_ack_before_usb(monkeypatch):
    monkeypatch.setattr(s.sys, "argv", ["evm_cn_stimulus_probe"])
    with pytest.raises(SystemExit) as exc:
        s.main()
    assert exc.value.code == 2
