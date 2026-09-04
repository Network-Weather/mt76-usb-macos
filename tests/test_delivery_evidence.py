# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

from research.delivery_evidence import DeliveryWindow, compare, qos_key

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


def test_four_address_qos_offset_and_ack_policy():
    frame = bytearray(data(7))
    frame[1] = 3
    frame[24:24] = A
    assert qos_key(frame) == (A, B, 5, 7)
    frame[30] |= 0x20  # No-ACK policy: no BlockAck expectation.
    assert qos_key(frame) is None
    frame[30] = 5 | 0x60
    assert qos_key(frame) == (A, B, 5, 7)


def test_pair_comparison_gates_and_visibility_categories():
    first = {i: [(i * 100000, i / 10)] for i in range(30)}
    second = {i: [(i * 100000 + 700, i / 10)] for i in range(30)}
    a = {"good": [(1000000, {1, 2, 3, 4}, {1, 2})]}
    b = {"good": [(1000700, {1, 2, 3, 4}, {1, 3})]}
    a["late"] = [(1000000, {1}, {1})]
    b["late"] = [(1001700, {1}, {1})]
    a["repeated"] = [(1000000, {1}, {1})] * 2
    b["repeated"] = [(1000700, {1}, {1})]
    counts = compare([({}, first, a), ({}, second, b)])["counts"]
    assert counts["shared_ba_events"] == 1
    assert counts["ba_outside_100us_gate"] == 1
    assert counts["repeated_ba_fingerprints_excluded"] == 1
    for key in (
        "ack_bits_data_seen_by_both",
        "ack_bits_data_seen_only_mt7921",
        "ack_bits_data_seen_only_mt7925",
        "ack_bits_data_seen_by_neither_recently",
    ):
        assert counts[key] == 1
    result = compare([({}, {}, {}), ({}, {}, {})])
    assert result["comparison"] == "no_usable_clock_fit"
