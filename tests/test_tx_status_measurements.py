# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Installed TX-status contract: no hardware, delivery or clock-alignment inference."""

import struct

import pytest

import mt76_measurements as mm


def packet(chip, formats=(0,), value=0xFFFFFFFF):
    prefix, stride = (16, 48) if chip == "mt7925" else (8, 32)
    records = b"".join(
        struct.pack("<6I", (value & ~(3 << 23)) | fmt << 23, value, value, value, value, value)
        + bytes(stride - 24)
        for fmt in formats
    )
    return struct.pack("<I", prefix + len(records)) + bytes(prefix - 4) + records


@pytest.mark.parametrize("chip", ["mt7921", "mt7925"])
def test_raw_values_presence_and_scale_are_separate(chip):
    for fmt, status in enumerate(mm.parse_tx_status(chip, packet(chip, (0, 1, 2, 3)))):
        assert status.format == fmt
        assert status.power_raw == 255
        assert status.power_signed == -1
        assert status.sequence == 4095
        assert status.pid == 255
        assert status.rate_raw == 16383
        assert status.ack_error_bits == 7
        assert status.error_bits_16_22 == 127
        assert status.timestamp_raw == (0xFFFFFFFF if chip == "mt7925" else None)
        assert status.tx_delay_raw == (65535 if chip == "mt7925" else None)
        assert status.bandwidth_raw == (7 if chip == "mt7925" else None)
        assert status.rate_stbc == (True if chip == "mt7925" else None)
        fmt0 = chip == "mt7925" and fmt == 0
        assert status.tx_count == (31 if fmt0 else None)
        assert status.front_time_raw == (0x1FFFFFF if fmt0 else None)
        assert status.timestamp_tick_ns == (1000 if fmt0 else None)
        assert status.front_time_tick_ns == (32000 if fmt0 else None)
        assert status.tx_delay_tick_ns == (32000 if fmt0 else None)


@pytest.mark.parametrize("chip", ["mt7921", "mt7925"])
def test_every_truncation_and_usb_padding(chip):
    raw = packet(chip, (0, 1))
    for end in range(len(raw)):
        with pytest.raises(ValueError, match="TXS"):
            mm.parse_tx_status(chip, raw[:end])
    assert mm.parse_tx_status(chip, raw + b"private USB padding") == mm.parse_tx_status(chip, raw)
    with pytest.raises(ValueError, match="capacity"):
        mm.parse_tx_status(chip, raw, 1)
    assert mm.parse_tx_status(chip, packet(chip, ()), 0) == ()


@pytest.mark.parametrize("capacity", [-1, True, 1.0, 2048])
def test_invalid_capacity(capacity):
    with pytest.raises(ValueError, match="capacity"):
        mm.parse_tx_status("mt7925", packet("mt7925"), capacity)


def test_unknown_chip():
    with pytest.raises(ValueError, match="unsupported"):
        mm.parse_tx_status("unknown", packet("mt7925"))
