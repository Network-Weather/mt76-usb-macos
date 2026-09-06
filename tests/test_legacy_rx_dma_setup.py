# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research import legacy_rx_dma_setup as p


class Device:
    CHIP = p.m.CHIP_MT7921

    def __init__(self):
        self.word = p.NORMAL | 0x30000080

    def rr(self, address):
        assert address == p.REGISTER
        return self.word

    def wr(self, address, word):
        assert address == p.REGISTER
        self.word = word


def test_only_five_fields_change_and_roundtrip():
    dev = Device()
    assert p.MASK == 0xCFFFFF7F
    assert p.apply(dev, "rf_setup")["after"] == hex(p.RF | 0x30000080)
    assert p.apply(dev, "normal")["after"] == hex(p.NORMAL | 0x30000080)


@pytest.mark.parametrize("mode", [None, True, 0x4000427F, "arbitrary"])
def test_no_arbitrary_configuration(mode):
    with pytest.raises(ValueError, match="only pinned"):
        p.apply(Device(), mode)


def test_wrong_chip_and_readback_rejected():
    dev = Device()
    dev.CHIP = p.m.CHIP_MT7925
    with pytest.raises(ValueError, match="only pinned"):
        p.apply(dev, "rf_setup")
    dev = Device()
    dev.wr = lambda *_: None
    with pytest.raises(RuntimeError, match="readback failed"):
        p.apply(dev, "rf_setup")
