# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research import legacy_rxv_control_probe as p


class Register:
    CHIP = p.m.CHIP_MT7921

    def __init__(self, word=1):
        self.word, self.writes = word, []

    def rr(self, address):
        assert address == p.REGISTER
        return self.word

    def wr(self, address, word):
        assert address == p.REGISTER
        self.word = word
        self.writes.append(word)


def test_rx_and_rxv_start_use_distinct_source_fields():
    dev = Register(0x80000081)
    p.apply_control(dev, "rxv_started")
    assert dev.writes == [0x80000081, 0x80000091]
    dev = Register(0x80000090)
    p.apply_control(dev, "rx_resumed_report_off")
    assert dev.writes == [0x80000090, 0x80000091, 0x80000011]
    # Register model intentionally does not invent hardware self-clearing behavior.


def test_reporting_does_not_change_other_bits():
    dev = Register(0x80000001)
    p.apply_control(dev, "rx_report_only")
    p.apply_control(dev, "rx_resumed_report_off")
    assert dev.writes == [0x80000081, 0x80000081, 0x80000081, 0x80000001]


def test_rejects_wrong_chip_unknown_stage_and_tx_reporting():
    with pytest.raises(ValueError, match="fixed old-chip"):
        p.apply_control(Register(), "arbitrary")
    with pytest.raises(ValueError, match="TX reporting"):
        p.apply_control(Register(0x101), "rxv_started")
    dev = Register()
    dev.CHIP = p.m.CHIP_MT7925
    with pytest.raises(ValueError, match="fixed old-chip"):
        p.apply_control(dev, "rxv_started")


def test_quiesce_uses_all_three_source_writes(monkeypatch):
    class Hardware(Register):
        def wr(self, address, word):
            super().wr(address, word)
            if word & 4:
                self.word = word & ~4

    dev = Hardware(0x80000091)
    assert p.quiesce(dev)["raw"] == "0x80000080"
    assert dev.writes == [0x80000090, 0x80000080, 0x80000084]
    monkeypatch.setattr(p.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="quiesce did not complete"):
        p.quiesce(Register(0x91))
