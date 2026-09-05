# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
from types import SimpleNamespace

import pytest

import mt7921u as m
from research import mt7925_tx_probe as probe
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
    deep = struct.unpack("<16I", build_txwi(frame, 17, -32))
    assert deep[2] == (32 << 26) | 4
    assert deep[:2] == words[:2]
    assert deep[3:] == words[3:]
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


@pytest.mark.parametrize("format_id", [0, 1, 2, 3])
def test_optional_raw_timing_fields_masked_and_format_guarded(format_id):
    words = [
        format_id << 23 | 0x480,
        7 << 20,
        0x1234ABCD,
        3 << 24 | 0x80,
        0xFFFFFFFF,
        0xE2345678,
    ] + [0] * 6
    raw = struct.pack("<4I", 64, 0, 0, 0) + struct.pack("<12I", *words)
    plain = tx_status(raw)[0]
    result = tx_status(raw, include_timing=True)[0]
    assert "timestamp_raw" not in plain
    assert result["timestamp_raw"] == 0xFFFFFFFF
    assert result["tx_delay_raw"] == 0xABCD
    assert result["rate_stbc"]
    assert result["front_time_raw_format0"] == (0x345678 if format_id == 0 else None)
    assert "private" not in repr(tx_status(raw + b"private USB tail", include_timing=True))


def test_capture_power_phase_assignment_and_exact_bytes(monkeypatch):
    samples = []
    for seq, signal in ((0, -50), (12, -54), (36, -58), (60, -50)):
        frame = m.build_probe_request(probe.SOURCE, probe.SSID, seq)
        frame = frame[:-6] + bytes((1, 1, 0x8C))
        samples.append(
            {
                "pkt_type": 2,
                "pkt_type_name": "NORMAL",
                "frame": frame,
                "rssi": signal,
                "phy": {"mode_name": "OFDM", "rate_mbps": 6.0},
            }
        )
    items = iter(range(4))
    times = iter((0, 0, 1, 2, 3, 9))
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(m, "decoder_for", lambda dev: lambda raw: samples[raw[0]])
    dev = SimpleNamespace(CHIP=m.CHIP_MT7921, rx_read=lambda **kw: bytes((next(items),)))
    barrier = SimpleNamespace(wait=lambda **kw: None)
    result = probe.capture(dev, 8, barrier, 60, [0, -8, 0, -16, 0])
    assert result["unique_sequences"] == 3
    assert result["counts"]["controlled_bytes_exact"] == 3
    assert [p["median_rssi"] for p in result["phases"]] == [-50, -54, None, -58, None]
    assert [p["unique_sequences"] for p in result["phases"]] == [1, 1, 0, 1, 0]


def test_capture_assigns_transmit_status_to_phase(monkeypatch):
    words = [0x4B, (36 << 20) | 10, 0, 3 << 24, 0, 1 << 25] + [0] * 6
    raw = struct.pack("<4I", 64, 0, 0, 0) + struct.pack("<12I", *words)
    times = iter((0, 0, 9))
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        m, "decoder_for", lambda dev: lambda raw: {"pkt_type": 0, "pkt_type_name": "TXS"}
    )
    dev = SimpleNamespace(CHIP=m.CHIP_MT7925, rx_read=lambda **kw: raw)
    barrier = SimpleNamespace(wait=lambda **kw: None)
    result = probe.capture(dev, 8, barrier, 60, [0, -8, 0, -16, 0])
    assert result["phases"][3]["tx_power_raw_values"] == {10: 1}
    assert result["tx_status"][0]["fields"]["tx_count_format0"] == 1


def test_alternate_rate_selects_native_table_slots_without_other_changes():
    frame = probe.controlled_frame(3, True)
    assert frame[-4:] == bytes((1, 2, 0x8C, 0x6C))
    slow = struct.unpack("<16I", build_txwi(frame, 3, disable_mat=True))
    fast = struct.unpack("<16I", build_txwi(frame, 3, disable_mat=True, rate="ofdm54"))
    assert slow[:6] == fast[:6]
    assert slow[7:] == fast[7:]
    assert slow[6] >> 16 & 63 == 18
    assert fast[6] >> 16 & 63 == 25
    assert [probe.planned_rate(i, True) for i in range(4)] == ["ofdm6", "ofdm54", "ofdm6", "ofdm54"]
    assert probe.planned_rate(3, False) == "ofdm6"
    assert probe.RATES["ofdm54"] == (25, 0x4C, 54.0)


def test_interleaved_capture_keeps_rate_and_power_phase_separate(monkeypatch):
    samples = []
    for seq, signal in ((0, -60), (1, -61), (12, -64), (13, -65), (36, -68), (37, -69)):
        speed = probe.RATES[probe.planned_rate(seq, True)][2]
        samples.append(
            {
                "pkt_type": 2,
                "pkt_type_name": "NORMAL",
                "frame": probe.controlled_frame(seq, True),
                "rssi": signal,
                "phy": {"mode_name": "OFDM", "rate_mbps": speed},
            }
        )
    items = iter(range(6))
    times = iter((0, 0, 1, 2, 3, 4, 5, 9))
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(m, "decoder_for", lambda dev: lambda raw: samples[raw[0]])
    dev = SimpleNamespace(CHIP=m.CHIP_MT7921, rx_read=lambda **kw: bytes((next(items),)))
    result = probe.capture(
        dev, 8, SimpleNamespace(wait=lambda **kw: None), 60, [0, -8, 0, -16, 0], True
    )
    assert result["counts"]["controlled_rate_mismatch"] == 0
    assert result["counts"]["controlled_bytes_exact"] == 6
    assert result["phases"][3]["by_received_rate"]["OFDM:54.0"] == {
        "unique_sequences": 1,
        "median_rssi": -69,
    }
