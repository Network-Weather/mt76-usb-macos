# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research import mt7925_noise_hist_probe as p


class Device:
    CHIP = p.m.CHIP_MT7925

    def __init__(self):
        self.values = {p.CONTROL: 0x12340000, p.RESET: 0x40000}
        self.reads = []
        self.writes = []

    def rr(self, address):
        self.reads.append(address)
        return self.values.get(address, 0)

    def wr(self, address, value):
        self.writes.append((address, value))
        self.values[address] = value


def test_live_code_verifier_is_fixed_and_read_only():
    dev = Device()
    rows = p.verify(dev)
    assert len(rows) == 5
    assert len(dev.reads) == 1174
    assert len(set(dev.reads)) == 1174
    assert not dev.writes
    assert not any(r["matches"] for r in rows)
    assert p.THRESHOLD_ADDRESS == 0x02212800 + 18220


def test_reset_preserves_unrelated_bits():
    dev = Device()
    p.reset(dev)
    assert dev.writes == [(p.RESET, 0x40000), (p.RESET, 0x20040000), (p.RESET, 0x40000)]


def test_enable_stop_preserves_unrelated_bits():
    dev = Device()
    p.set_bits(dev, p.CONTROL, 5)
    p.set_bits(dev, p.CONTROL, 0)
    assert dev.writes == [(p.CONTROL, 0x12340005), (p.CONTROL, 0x12340000)]
    assert p.DURATIONS == (0.25, 1.0)
    assert p.CHANNELS == (1, 6, 11, 36)
    assert set(p.MASKS) == {0x83082004, 0x83088230}


def test_only_two_source_traced_bank0_windows():
    dev = Device()
    assert p.banks(dev) == {"ordinary_getter": [0] * 11, "timer_getter": [0] * 11}
    assert dev.reads == list(range(0x83088600, 0x8308862C, 4)) + list(
        range(0x83001000, 0x8300102C, 4)
    )
    assert not dev.writes


def test_compare_reads_only_two_additional_source_windows():
    dev = Device()
    assert len(p.banks(dev, True)) == 4
    assert len(dev.reads) == 44
    assert dev.reads[22:] == list(range(0x83098600, 0x8309862C, 4)) + list(
        range(0x83011000, 0x8301102C, 4)
    )
    assert not dev.writes


def test_controls_are_read_only_and_masked():
    dev = Device()
    dev.values[p.CONTROL] |= 5
    assert p.controls(dev) == {"0x83082004": 5, "0x83092004": 0}
    assert dev.reads == [p.CONTROL, 0x83092004]
    assert not dev.writes


def test_mib_crosscheck_uses_only_source_selected_offsets(monkeypatch):
    def sample(dev, offsets, band):
        assert offsets == (11, 12, 13, 17, 19, 20, 52)
        assert band == 0
        return dict.fromkeys(offsets, 5), 1.0

    monkeypatch.setattr(p.mib, "sample", sample)
    assert p.mib_sample(Device())["values"] == dict.fromkeys(p.MIB_OFFSETS, 5)


def test_missing_crosscheck_counter_refused(monkeypatch):
    monkeypatch.setattr(p.mib, "sample", lambda *_: ({}, 1.0))
    with pytest.raises(ValueError, match="missing source-named"):
        p.mib_sample(Device())


@pytest.mark.parametrize(
    ("address", "word", "bits"),
    [
        (0x83092004, 0, 5),
        (p.CONTROL, -1, 0),
        (p.CONTROL, 0xFFFFFFFF, 0),
        (p.CONTROL, True, 0),
        (p.CONTROL, 0, 8),
        (p.RESET, 0, 1),
        (p.CONTROL, 0, -1),
        (p.CONTROL, 0, True),
    ],
)
def test_invalid_write_refused(address, word, bits):
    with pytest.raises(ValueError, match="pinned histogram masks"):
        p.masked(address, word, bits)


def test_wrong_chip_refused_before_writes():
    dev = Device()
    dev.CHIP = p.m.CHIP_MT7921
    with pytest.raises(ValueError, match="MT7925 histogram"):
        p.reset(dev)
    with pytest.raises(ValueError, match="MT7925 histogram"):
        p.set_bits(dev, p.CONTROL, 5)
    assert not dev.writes
    assert not dev.reads


def test_failed_enable_readback():
    dev = Device()
    dev.wr = lambda *_: None
    with pytest.raises(RuntimeError, match="readback failed"):
        p.set_bits(dev, p.CONTROL, 5)
