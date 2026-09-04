# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

from research.delivery_evidence import DeliveryWindow, qos_key

A, B = bytes.fromhex("020000000001"), bytes.fromhex("020000000002")


def data(seq, tid=5):
    return (
        struct.pack("<HH", 0x0188, 0) + B + A + B + struct.pack("<HH", seq << 4, tid) + b"payload"
    )


def ba(start, bitmap, tid=5):
    return (
        struct.pack("<HH", 0x94, 0)
        + A
        + B
        + struct.pack("<HHQ", (tid << 12) | 4, start << 4, bitmap)
    )


def test_direction_tid_wrap_and_unsent_positions():
    w = DeliveryWindow(100000)
    w.observe(b"", 0)
    w.observe(data(4095), 110000)
    w.observe(data(0), 120000)
    w.observe(data(1, tid=3), 120000)
    result = w.observe(ba(4095, 0b101), 130000)
    assert result["seen"] == {4095, 0}
    assert result["acked"] == {4095, 1}
    assert w.observe(ba(4095, 0b101), 240000)["seen"] == set()


def test_warmup_and_retry_history_expiry():
    w = DeliveryWindow(100000)
    w.observe(data(20), 0)
    assert w.observe(ba(20, 1), 1)["status"] == "warming_up"
    w.observe(data(20), 90000)
    assert w.observe(ba(20, 1), 110000)["seen"] == {20}
    assert w.observe(ba(20, 1), 200001)["seen"] == set()


def test_skip_null_multicast_and_fragmented_data():
    assert qos_key(data(7)) == (A, B, 5, 7)
    frame = bytearray(data(7))
    frame[0] = 0xC8
    assert qos_key(frame) is None
    frame = bytearray(data(7))
    frame[4] |= 1
    assert qos_key(frame) is None
    frame = bytearray(data(7))
    frame[22] |= 1
    assert qos_key(frame) is None
