# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import txpower_register_probe as p


class Device:
    CHIP = p.m.CHIP_MT7925

    def __init__(self):
        self.reads = []

    def rr(self, address):
        self.reads.append(address)
        return 0


def test_bounded_verification():
    dev = Device()
    code, records = p.verify(dev)
    assert len(code) == 4
    assert len(records) == 2
    assert len(dev.reads) == 1246
    assert len(set(dev.reads)) == 1246
    assert not any(r["matches"] for r in code + records)
    assert p.FLAG_ADDRESS == 0x02212800 + 62623
    assert p.TABLE_BYTES == 420
    assert p.PLAN == ((6, 6, 20), (6, 8, 40), (36, 36, 20))


def test_formatter_skips_three_padding_bytes_preserves_signed_codes():
    raw = bytes(i % 256 for i in range(420))
    rows = p.unpack_table(raw)
    flat = [v for values in rows.values() for v in values]
    assert flat == list(struct.unpack("<417b", raw[:29] + raw[32:]))
    assert rows["ht40"][-1] == 28
    assert rows["vht20"][0] == 32
    assert flat[-1] == -93
    assert len(flat) == 417


@pytest.mark.parametrize("size", [0, 419, 421, 424, 834])
def test_wrong_table_size(size):
    with pytest.raises(ValueError, match="420-byte"):
        p.unpack_table(bytes(size))


@pytest.mark.parametrize("word", [-1, 1 << 32, None, True])
def test_invalid_read(word):
    dev = Device()
    dev.rr = lambda _: word
    with pytest.raises(ValueError, match="invalid read"):
        p.read_words(dev, p.TABLE_BASE, 4)


def test_wrong_chip_alignment_and_state_refused():
    dev = Device()
    dev.CHIP = p.m.CHIP_MT7921
    with pytest.raises(ValueError, match="aligned MT7925"):
        p.verify(dev)
    dev.CHIP = p.m.CHIP_MT7925
    with pytest.raises(ValueError, match="aligned MT7925"):
        p.read_words(dev, p.TABLE_BASE + 1, 4)
    with pytest.raises(ValueError, match="aligned MT7925"):
        p.read_words(dev, p.TABLE_BASE, 3)
    with pytest.raises(ValueError, match="three bounded"):
        p.sample(dev, 149, 149, 20)
    assert not dev.reads


def test_sample_compares_report_and_both_reads(monkeypatch):
    dev = Device()
    dev.tune = lambda *args: None
    monkeypatch.setattr(p.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        p, "query", lambda _: {"selected_band_power_raw": p.unpack_table(bytes(420))}
    )
    row = p.sample(dev, 6, 6, 20)
    assert row["hardware_before_matches_report"]
    assert row["hardware_after_matches_report"]
    assert row["hardware_selected_rows_unchanged"]
    assert len(dev.reads) == 211
    assert set(dev.reads) == {p.FLAG_ADDRESS & ~3} | set(range(p.TABLE_BASE, p.TABLE_BASE + 420, 4))
