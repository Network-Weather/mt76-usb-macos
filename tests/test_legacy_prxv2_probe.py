# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research import legacy_prxv2_probe as p


class Register:
    CHIP = p.m.CHIP_MT7921

    def __init__(self):
        self.word = 0x24F00903

    def rr(self, address):
        assert address == p.REGISTER
        return self.word

    def wr(self, address, word):
        assert address == p.REGISTER
        self.word = word


def test_only_bit0_changes_and_roundtrips():
    dev = Register()
    assert p.set_field(dev, 0)["after"] == "0x24f00902"
    assert p.set_field(dev, 1)["after"] == "0x24f00903"


@pytest.mark.parametrize("value", [-1, 2, True, "0"])
def test_only_two_explicit_field_values(value):
    with pytest.raises(ValueError, match="old RMAC bit0"):
        p.set_field(Register(), value)


def test_wrong_chip_and_failed_write_rejected():
    dev = Register()
    dev.CHIP = p.m.CHIP_MT7925
    with pytest.raises(ValueError, match="old RMAC bit0"):
        p.set_field(dev, 0)
    dev = Register()
    dev.wr = lambda *_: None
    with pytest.raises(RuntimeError, match="readback failed"):
        p.set_field(dev, 0)
