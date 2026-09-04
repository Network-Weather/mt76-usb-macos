# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

import mt7921u as m
from research.mt7925_tx_probe import ITCR, ITDR0, ITDR1, build_txwi, set_ofdm_rate, tx_status


def test_connac3_probe_descriptor_geometry():
    frame = m.build_probe_request(bytes.fromhex("020000000001"), b"test", 17)
    words = struct.unpack("<16I", build_txwi(frame, 17))
    assert words[0] & 65535 == len(frame) + 64
    assert words[1] == 0x800C8000
    assert words[2] == 4
    assert words[3] == 0x90117811
    assert words[5] == 0x403
    assert words[6] == 0x00120014  # rate TABLE slot 18, not OFDM 0x4b
    assert words[7:] == (0,) * 9
    changed = struct.unpack("<16I", build_txwi(frame, 17, -8))
    assert changed[2] == (56 << 26) | 4
    assert changed[:2] == words[:2]
    assert changed[3:] == words[3:]
    no_mat = struct.unpack("<16I", build_txwi(frame, 17, disable_mat=True))
    assert no_mat[6] == words[6] | 8
    assert no_mat[:6] == words[:6]
    assert no_mat[7:] == words[7:]
    with pytest.raises(ValueError, match="Probe Request"):
        build_txwi(b"", 0)
    with pytest.raises(ValueError, match="out of range"):
        build_txwi(frame, 0, 1)


def test_rate_table_write_sequence():
    class Device:
        CHIP = m.CHIP_MT7925

        def __init__(self):
            self.writes = []

        def wr(self, address, value):
            self.writes.append((address, value))

        def rr(self, address):
            return 0x10012 if address == ITCR else 0x4B

    dev = Device()
    assert set_ofdm_rate(dev)["staging_rate"] == 0x4B
    assert dev.writes == [(ITDR0, 0x4B), (ITDR1, 64), (ITCR, 0x80010012)]


def test_connac3_status_uses_four_word_header_twelve_word_records():
    words = [0x4B, (17 << 20) | 36, 0, 3 << 24] + [0] * 8
    raw = struct.pack("<4I", 64, 0, 0, 0) + struct.pack("<12I", *words)
    assert tx_status(raw) == [
        {
            "sequence": 17,
            "format": 0,
            "rate_raw": 75,
            "power_raw": 36,
            "ack_error_bits": 0,
            "error_bits_16_22": 0,
            "tx_count_format0": 0,
            "pid": 3,
        }
    ]
    assert tx_status(raw[:-1]) == []
