# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Narrow CSI profile fixtures; synthetic transmitter, no captured coefficients."""

import struct

import pytest

import mt76_csi as csi


def report_fields():
    fields = {tag: bytes(4) for tag in (0, 1, 2, 3, 4, 5, 8, 9, 12, 18, 20, 21)}
    fields.update(
        {
            0: struct.pack("<I", 22),
            2: struct.pack("<I", 0xFFFFFFBA),
            3: struct.pack("<I", 23),
            5: struct.pack("<I", 64),
            6: struct.pack("<64h", *([-32768, 32767] * 32)),
            7: struct.pack("<64h", *range(-32, 32)),
            10: bytes.fromhex("0200000000010000"),
            12: struct.pack("<I", 11 << 16 | 1),
            25: struct.pack("<I", 0xFFFFFFFF),
        }
    )
    return dict(sorted(fields.items()))


def event(body, eid=0x4A, sequence=0):
    raw = bytearray(44)
    struct.pack_into("<I", raw, 0, len(body) + 44 | 7 << 27)
    raw[36:38] = bytes((eid, sequence))
    return bytes(raw) + body


def report(fields=None, tail=bytes(36)):
    if fields is None:
        fields = report_fields()
    body = (
        b"".join(struct.pack("<II", tag, len(data)) + data for tag, data in fields.items()) + tail
    )
    return event(struct.pack("<4xHH", 0, len(body) + 4) + body)


def malformed_reports():
    original = report()
    yield b""
    for end in range(len(original)):
        yield original[:end]
        declared = bytearray(original)
        struct.pack_into("<H", declared, 0, end)
        yield bytes(declared)
    for tag, value in (
        (0, 21),
        (1, 6),
        (4, 1),
        (5, 13),
        (8, 1),
        (12, 0),
        (18, 2),
        (18, 65536),
        (20, 1),
        (21, 1),
    ):
        yield report(report_fields() | {tag: struct.pack("<I", value)})
    for tag in report_fields():
        fields = report_fields()
        del fields[tag]
        yield report(fields)
        yield report(report_fields() | {tag: b""})
    for ta in (bytes(8), bytes.fromhex("0100000000010000")):
        yield report(report_fields() | {10: ta})
    for tail in (bytes(4), bytes(8), bytes(32), bytes(40), bytes(35) + b"x"):
        yield report(tail=tail)
    for offset in (3, 36, 37):
        changed = bytearray(original)
        changed[offset] ^= 8
        yield bytes(changed)
    yield event(struct.pack("<4xHH", 0, 20) + struct.pack("<II", 0, 0) * 2)


def test_narrow_report_and_private_repr():
    sample = csi.parse_beacon_csi("mt7925", report())
    assert (sample.version, sample.data_count, sample.rx_index, sample.tx_index) == (22, 64, 0, 0)
    assert sample.rssi_raw_s8 == -70
    assert sample.snr_raw == 23
    assert sample.mcu_gpt_raw == 0xFFFFFFFF
    assert sample.i == (-32768, 32767) * 32
    assert sample.q == tuple(range(-32, 32))
    assert sample.transmitter == bytes.fromhex("020000000001")
    assert "transmitter=" not in repr(sample)
    assert "i=" not in repr(sample)
    assert "q=" not in repr(sample)
    assert csi.parse_beacon_csi("mt7925", report() + b"private padding") == sample
    assert csi.parse_beacon_csi("mt7925", report(tail=b"")) == sample


def test_reject_outside_profile_without_partial_report():
    for raw in malformed_reports():
        with pytest.raises(ValueError, match="CSI"):
            csi.parse_beacon_csi("mt7925", raw)
    with pytest.raises(ValueError, match="CSI"):
        csi.parse_beacon_csi("mt7921", report())


@pytest.mark.parametrize("action", list(csi.CsiAction))
def test_control_wire_matches_research(action):
    from research import csi_control_probe as p
    from research.csi_filter_probe import filter_request

    kwargs = {}
    if action in (csi.CsiAction.STOP, csi.CsiAction.START):
        expected = p.request("mt7925", action == csi.CsiAction.START)
    elif action == csi.CsiAction.BEACON_SELECTOR:
        expected = p.beacon_selector_request(0)
    elif action == csi.CsiAction.RECEIVER_COUNT:
        kwargs["receivers"] = 1
        expected = p.chain_request(0, 1)
    else:
        kwargs["transmitter"] = bytes.fromhex("020000000001")
        expected = filter_request(action == csi.CsiAction.ADD_TRANSMITTER, kwargs["transmitter"])
    assert csi.build_csi_request("mt7925", action, **kwargs) == expected
    with pytest.raises(ValueError, match="MT7925"):
        csi.build_csi_request("mt7921", action, **kwargs)


@pytest.mark.parametrize("status", [0, 1, 0xC00000BB, 0xFFFFFFFF])
def test_ack_status_is_not_silently_success(status):
    raw = event(struct.pack("<II", 0x4A, status), 1, 9)
    assert csi.parse_csi_ack("mt7925", raw, 9) == status
    for bad in (raw[:-1], raw[:44], event(struct.pack("<II", 0x35, status), 1, 9)):
        with pytest.raises(ValueError, match="CSI"):
            csi.parse_csi_ack("mt7925", bad, 9)
