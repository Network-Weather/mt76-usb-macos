# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import mt7921u as m
from research.control_frames import parse_control
from research.dual_radio_probe import delta32, fit_clock, fixed_rate_txwi, tx_status_records


def test_compressed_blockack_wrap_and_unsent_tail():
    header = struct.pack("<HH", 0x94, 123) + bytes.fromhex("020000000001020000000002")
    frame = header + struct.pack("<HHQ", 0x5004, 4094 << 4, 0b1101)
    decoded = parse_control(frame)
    assert decoded["ack_sequences"] == [4094, 0, 1]
    assert decoded["zero_positions_through_last_ack"] == 1
    assert decoded["tid"] == 5
    assert decoded["duration_id"] == 123
    assert parse_control(frame[:-1])["error"] == "short_bitmap"
    # Multi-STA is not a compressed single-TID bitmap.
    assert "unsupported" in parse_control(header + struct.pack("<H", 0x16))


def test_ack_has_no_invented_transmitter_and_rts_has_two_addresses():
    frame = struct.pack("<HH", 0xD4, 0) + b"\x02" * 6
    assert "ta" not in parse_control(frame)
    rts = struct.pack("<HH", 0xB4, 20) + b"\x02" * 6 + b"\x04" * 6
    assert parse_control(rts)["ta"] == b"\x04" * 6


def test_clock_wrap_drift_and_holdout():
    assert delta32(5, 0xFFFFFFFC) == 9
    pairs = [
        ((0xFFFF0000 + i * 100000) % 2**32, (70000 + i * 100002) % 2**32, i / 10)
        for i in range(100)
    ]
    result = fit_clock(pairs)
    assert result["relative_drift_ppm"] == 20
    assert result["second_half_prediction"]["max_us_if_1mhz"] == 0
    assert fit_clock(pairs[:3])["status"] == "insufficient_pairs"
    assert fit_clock(pairs, split_index=0)["status"] == "insufficient_split_pairs"
    assert fit_clock(pairs, split_index=30)["second_half_prediction"]["max_us_if_1mhz"] == 0
    stepped = [(a, b if i < 30 else b + 1000, t) for i, (a, b, t) in enumerate(pairs)]
    assert fit_clock(stepped, split_index=30)["second_half_prediction"]["median_us_if_1mhz"] == 1000


def test_fixed_ofdm_changes_only_rate_word_and_keeps_no_ack():
    dev = object.__new__(m.Mt7921uDevice)
    frame = m.build_probe_request(bytes.fromhex("020000000003"), b"test")
    original = dev._build_txwi(frame, 7, 3)
    changed = fixed_rate_txwi(dev, frame, 7, "ofdm6", True)
    assert original[:24] == changed[:24]
    assert original[28:] == changed[28:]
    assert struct.unpack_from("<I", changed, 24)[0] == 0x004B0004
    assert struct.unpack_from("<I", changed, 12)[0] & 1


def test_txs_bounds_and_format():
    words = (0x8000004B, 27, 0, 3 << 24, 0, 0, 0, 0)
    raw = struct.pack("<II8I", 40, 0, *words)
    assert tx_status_records(raw + b"padding")[0]["rate"] == 0x4B
    assert tx_status_records(raw[:39]) == []
