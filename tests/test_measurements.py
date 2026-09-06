# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Named counter contract and strict wire fixtures; no hardware required."""

import struct

import pytest

import mt76_measurements as mm
import mt7921u as m


def entry(offset, value, length=8):
    return struct.pack("<HHIQ", 0, length, offset, value)


@pytest.mark.parametrize("chip", [m.CHIP_MT7921, m.CHIP_MT7925])
def test_profile_is_finite_and_does_not_invent_accumulator_width(chip):
    descriptors = mm.counter_descriptors(chip)
    assert len(descriptors) == (4 if chip == m.CHIP_MT7921 else 10)
    assert 94 not in {d.offset for d in descriptors}
    assert all(d.accumulator_bits is None for d in descriptors)
    assert all(d.tick_ns is None for d in descriptors if d.unit == mm.CounterUnit.DURATION_TICKS)
    cca = next(d for d in descriptors if d.counter == mm.Counter.PRIMARY_CCA)
    assert cca.offset == (11 if chip == m.CHIP_MT7921 else 17)


@pytest.mark.parametrize("chip", ["unknown", None])
def test_unknown_profile_is_not_a_zero_measurement(chip):
    with pytest.raises(ValueError, match="unsupported chip"):
        mm.counter_descriptors(chip)


@pytest.mark.parametrize("offsets", [(), (1, 1), (True,), (-1,), (512,), tuple(range(17))])
def test_request_refuses_invalid_offsets(offsets):
    with pytest.raises(ValueError, match="invalid chip/offset"):
        mm.build_mib_request(m.CHIP_MT7925, offsets)


@pytest.mark.parametrize("band", [-1, 2, True, 0.0])
def test_request_refuses_invalid_band(band):
    with pytest.raises(ValueError, match="band index"):
        mm.build_mib_request(m.CHIP_MT7925, (17,), band)


def test_uni_complete_final_entry_and_order():
    body = bytes(12) + entry(17, 0x100000001, 16) + entry(2, 9)
    assert mm.parse_mib_reply(m.CHIP_MT7925, body, (2, 17)) == (9, 0x100000001)


@pytest.mark.parametrize(
    "body", [b"", entry(17, 9)[:-1], entry(17, 9, 7), entry(2, 9), entry(17, 9) * 2]
)
def test_uni_bad_reply_is_not_partial_output(body):
    with pytest.raises(ValueError, match="UNI MIB"):
        mm.parse_mib_reply(m.CHIP_MT7925, body, (17,))


def test_ext_is_32_bit_at_measured_offset():
    body = bytes(28) + struct.pack("<I", 0xFFFFFFFF) + bytes(4)
    assert mm.parse_mib_reply(m.CHIP_MT7921, body, (11,)) == (0xFFFFFFFF,)
    with pytest.raises(ValueError, match="short EXT"):
        mm.parse_mib_reply(m.CHIP_MT7921, body[:31], (11,))


class FakeDevice:
    def __init__(self, chip):
        self.CHIP = chip
        self.mcu_wait_dropped_frames = 0
        self.calls = []
        self.fail_at = None
        self.msg_seq = 9

    def _query(self, command, payload, timeout, query=False):
        self.calls.append((command, payload, timeout, query))
        if len(self.calls) == self.fail_at:
            raise m.McuError("synthetic failure")
        self.mcu_wait_dropped_frames += 1
        if self.CHIP == m.CHIP_MT7921:
            body = bytes(28) + struct.pack("<I", 100 + struct.unpack_from("<I", payload, 4)[0])
        else:
            body = b"".join(
                entry(o, 100 + o)
                for o in (
                    struct.unpack_from("<I", payload, a)[0] for a in range(8, len(payload), 8)
                )
            )
        return event(self.CHIP, body)

    mcu_cmd_word = _query
    mcu_uni = _query

    def reply_body(self, reply):
        return reply


def event(chip, body):
    header = bytearray(44 if chip == m.CHIP_MT7925 else 36)
    struct.pack_into("<I", header, 0, len(header) + len(body) | 7 << 27)
    header[37 if chip == m.CHIP_MT7925 else 29] = 9
    return bytes(header) + body


@pytest.mark.parametrize("chip", [m.CHIP_MT7921, m.CHIP_MT7925])
def test_event_parser_checks_dma_sequence_type_and_padding(chip):
    body = entry(17, 77) if chip == m.CHIP_MT7925 else bytes(28) + struct.pack("<I", 77)
    raw = event(chip, body)
    assert mm.parse_mib_event(chip, raw + bytes(8), 9, (17,)) == (77,)
    assert mm.parse_mib_event(chip, raw, 9, iter((17,))) == (77,)
    bad_type = bytearray(raw)
    bad_type[3] = 2 << 3
    bad_length = bytearray(raw)
    bad_length[0] = 1
    for bad, seq in [(raw[:-1], 9), (raw, 8), (bad_type, 9), (bad_length, 9)]:
        with pytest.raises(ValueError, match="MIB event"):
            mm.parse_mib_event(chip, bad, seq, (17,))


@pytest.mark.parametrize("chip", [m.CHIP_MT7921, m.CHIP_MT7925])
def test_named_read_batches_new_chip_and_serializes_old(chip):
    dev = FakeDevice(chip)
    descriptors = mm.counter_descriptors(chip)
    sample = mm.read_counters(dev, (d.counter for d in descriptors))
    assert sample.opened_us <= sample.closed_us
    assert [r.raw for r in sample.readings] == [100 + d.offset for d in descriptors]
    assert len(dev.calls) == (4 if chip == m.CHIP_MT7921 else 1)
    assert sample.legacy_dropped_frames == len(dev.calls)
    assert all(c[2] == 700 for c in dev.calls)


@pytest.mark.parametrize(
    "names", [(), (mm.Counter.RX_FCS_ERROR,), (mm.Counter.PRIMARY_CCA,) * 2, (4,), ("primary_cca",)]
)
def test_named_validation_happens_before_any_io(names):
    dev = FakeDevice(m.CHIP_MT7921)
    with pytest.raises(ValueError, match=r"Counter names|not supported|duplicate counter"):
        mm.read_counters(dev, names)
    assert not dev.calls


def test_partial_serial_failure_is_not_a_sample():
    dev = FakeDevice(m.CHIP_MT7921)
    dev.fail_at = 2
    with pytest.raises(m.McuError):
        mm.read_counters(dev, (mm.Counter.RX_MPDU, mm.Counter.PRIMARY_CCA))
    assert len(dev.calls) == 2
