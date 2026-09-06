# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Same synthetic wire bytes through the Python reference and compiled native C.

No dongle, firmware, ambient traffic, or test-time generated expectation from C.
The fixture library is built in pytest's temporary directory, never into the repo.
"""

import ctypes as ct
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import mt76_measurements as mm
import mt7921u as m
import rxd
import rxd_connac3
from research.rx_vector_probe import vectors

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native IOKit C build")


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    out = tmp_path_factory.mktemp("c-parity") / "parity.dylib"
    sources = [
        "mt7921_rxd.c",
        "mt7921_rxd_connac3.c",
        "mt7921_chip.c",
        "mt7921_dev.c",
        "mt7921_mcu.c",
        "mt7921_usb.c",
        "mt7921_radio.c",
    ]
    subprocess.run(  # noqa: S603 -- fixed local source list, no external input
        [
            "/usr/bin/clang",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-dynamiclib",
            "-I",
            str(ROOT / "c"),
            str(ROOT / "tests/c_parity_bridge.c"),
            *(str(ROOT / "c" / name) for name in sources),
            "-framework",
            "IOKit",
            "-framework",
            "CoreFoundation",
            "-o",
            str(out),
        ],
        check=True,
        capture_output=True,
        env=os.environ,
    )
    lib = ct.CDLL(str(out))
    lib.parity_rx.argtypes = [ct.c_char_p, ct.c_uint, ct.c_int, ct.POINTER(ct.c_uint)]
    lib.parity_rx.restype = ct.c_int
    lib.mt_mib_request.argtypes = [
        ct.c_int,
        ct.c_uint8,
        ct.POINTER(ct.c_uint32),
        ct.c_size_t,
        ct.c_void_p,
        ct.c_size_t,
    ]
    lib.mt_mib_parse.argtypes = [
        ct.c_int,
        ct.c_char_p,
        ct.c_size_t,
        ct.POINTER(ct.c_uint32),
        ct.c_size_t,
        ct.POINTER(ct.c_uint64),
    ]
    lib.mt_mib_delta.argtypes = [
        ct.c_uint64,
        ct.c_uint64,
        ct.c_uint,
        ct.c_uint64,
        ct.POINTER(ct.c_uint64),
    ]
    lib.mt_mib_delta.restype = ct.c_bool
    lib.mt_probe_txwi.argtypes = [
        ct.c_int,
        ct.c_char_p,
        ct.c_size_t,
        ct.c_uint,
        ct.c_int,
        ct.c_int,
        ct.c_void_p,
    ]
    lib.parity_txs.argtypes = [ct.c_int, ct.c_char_p, ct.c_uint, ct.POINTER(ct.c_int)]
    return lib


class CounterDescriptor(ct.Structure):
    _fields_ = [
        ("name", ct.c_char_p),
        ("counter", ct.c_int),
        ("offset", ct.c_uint32),
        ("unit", ct.c_int),
        ("wire_bits", ct.c_uint),
        ("hardware_bits", ct.c_uint),
        ("accumulator_bits", ct.c_uint),
        ("tick_ns", ct.c_uint),
        ("hardware_saturates", ct.c_bool),
    ]


@pytest.mark.parametrize("chip", [0, 1])
def test_named_counter_descriptors_and_requests_match_python(native, chip):
    name = m.CHIP_MT7925 if chip else m.CHIP_MT7921
    native.mt_counter_descriptor.argtypes = [ct.c_int, ct.c_int]
    native.mt_counter_descriptor.restype = ct.POINTER(CounterDescriptor)
    expected = {d.counter: d for d in mm.counter_descriptors(name)}
    for counter in mm.Counter:
        pointer = native.mt_counter_descriptor(chip, counter)
        if counter not in expected:
            assert not pointer
            continue
        actual, descriptor = pointer.contents, expected[counter]
        assert actual.name.decode() == descriptor.name
        for field in (
            "counter",
            "offset",
            "unit",
            "wire_bits",
            "hardware_bits",
            "accumulator_bits",
            "tick_ns",
            "hardware_saturates",
        ):
            assert getattr(actual, field) == (getattr(descriptor, field) or 0)
        offsets = (ct.c_uint32 * 1)(descriptor.offset)
        output = ct.create_string_buffer(132)
        length = native.mt_mib_request(chip, 0, offsets, 1, output, len(output))
        assert output.raw[:length] == mm.build_mib_request(name, (descriptor.offset,))
    assert not native.mt_counter_descriptor(42, mm.Counter.PRIMARY_CCA)


@pytest.mark.parametrize("chip", [0, 1])
@pytest.mark.parametrize("mode", range(7))
def test_named_counter_read_faults(native, chip, mode):
    native.parity_counter_read.argtypes = [ct.c_int, ct.c_int]
    assert native.parity_counter_read(chip, mode) == 0


@pytest.mark.parametrize("chip", [0, 1])
def test_production_mib_parsers_share_valid_and_malformed_bytes(native, chip):
    name = m.CHIP_MT7925 if chip else m.CHIP_MT7921
    offsets = (2, 17) if chip else (11,)
    values = (0xFFFFFFFF, 0x100000002) if chip else (0xFFFFFFFF,)
    body = (
        bytes(12)
        + b"".join(struct.pack("<HHIQ", 0, 8, o, v) for o, v in zip(offsets, values, strict=True))
        if chip
        else bytes(28) + struct.pack("<I", values[0])
    )
    offset_array = (ct.c_uint32 * len(offsets))(*offsets)
    for raw in [body, body + body] + [body[:i] for i in range(len(body))]:
        out = (ct.c_uint64 * len(offsets))(*([99] * len(offsets)))
        result = native.mt_mib_parse(chip, raw, len(raw), offset_array, len(offsets), out)
        try:
            parsed = mm.parse_mib_reply(name, raw, offsets)
        except ValueError:
            assert result == -1
            assert tuple(out) == (99,) * len(offsets)
        else:
            assert result == 0
            assert tuple(out) == parsed


def rx_fixture(c3, mask, timestamp=0xFFFFFFFE):
    fixed = 32 if c3 else 24
    groups = bytearray()
    for bit, size in (
        (8, 16),
        (1, 16),
        (2, 16 if c3 else 8),
        (4, 16 if c3 else 8),
        (16, 96 if c3 else 72),
    ):
        if not mask & bit:
            continue
        group = bytearray(size)
        if bit == 2:
            struct.pack_into("<I", group, 0, timestamp)
        if bit in (4, 16):
            for i in range(size // 4):
                struct.pack_into("<I", group, i * 4, 0x10203040 + i)
        groups.extend(group)
    # Synthetic empty probe request, no identifier or payload.
    frame = b"\x40\x00" + bytes(22)
    raw = bytearray(fixed) + groups + frame
    struct.pack_into("<II", raw, 0, len(raw) | (2 << 27), mask << (16 if c3 else 11))
    return bytes(raw)


@pytest.mark.parametrize("c3", [False, True])
@pytest.mark.parametrize("mask", range(32))
def test_rx_shared_bytes(native, c3, mask):
    raw = rx_fixture(c3, mask)
    output = (ct.c_uint * 35)()
    chip = 1 if c3 else 0
    result = native.parity_rx(raw, len(raw), chip, output)
    reference = vectors(raw, m.CHIP_MT7925 if c3 else m.CHIP_MT7921)
    if mask & 16 and not mask & 4:
        assert result == -1
        assert reference["error"] == "g5_without_g3"
        return
    assert result == 0
    decoded = (rxd_connac3.decode if c3 else rxd.decode)(raw)
    assert output[0] == bool(mask & 2)
    assert output[1] == decoded.get("timestamp", 0)
    assert output[2] == mask
    assert list(output[7 : 7 + output[3]]) == list(reference.get("g3", ()))
    assert list(output[11 : 11 + output[4]]) == list(reference.get("g5", ()))
    assert raw[output[5] : output[5] + output[6]] == decoded["frame"]


@pytest.mark.parametrize("c3", [False, True])
def test_rx_bounds_and_absence(native, c3):
    raw = rx_fixture(c3, 31)
    output = (ct.c_uint * 35)()
    chip = 1 if c3 else 0
    for end in range(len(raw) - 24):
        assert native.parity_rx(raw, end, chip, output) == -1
        declared = bytearray(raw)
        struct.pack_into("<H", declared, 0, end)
        assert native.parity_rx(bytes(declared), len(raw), chip, output) == -1
    for timestamp in (0, 1, 0xFFFFFFFF):
        fixture = rx_fixture(c3, 2, timestamp)
        assert native.parity_rx(fixture, len(fixture), chip, output) == 0
        assert tuple(output[:2]) == (1, timestamp)
    fixture = rx_fixture(c3, 0)
    assert native.parity_rx(fixture, len(fixture), chip, output) == 0
    assert tuple(output[:2]) == (0, 0)


@pytest.mark.parametrize("chip", [0, 1])
def test_mib_shared_bytes(native, chip):
    from research import mt7925_mib_characterize as mib
    from scripts import mcu_stats

    offsets = (ct.c_uint32 * 2)(19, 20) if chip else (ct.c_uint32 * 1)(11)
    output = ct.create_string_buffer(256)
    count = len(offsets)
    result = native.mt_mib_request(chip, 0, offsets, count, output, len(output))
    reference = (
        mib.build_request(0, tuple(offsets)) if chip else mcu_stats.build_mib_request(0, [11])
    )
    assert output.raw[:result] == reference
    body = (
        bytes(12) + struct.pack("<HHIQHHIQ", 0, 8, 19, 0x100000002, 0, 16, 20, 500)
        if chip
        else bytes(28) + struct.pack("<I", 0xFFFFFFFE) + bytes(8)
    )
    values = (ct.c_uint64 * count)()
    assert native.mt_mib_parse(chip, body, len(body), offsets, count, values) == 0
    assert list(values) == (
        [mib.parse_counter(body, o) for o in offsets]
        if chip
        else [mcu_stats.parse_mt7921_value(body)]
    )
    # Missing/truncated entries never become zeros or partial success.
    for length in range(len(body) if chip else 32):
        values[0] = 123
        assert native.mt_mib_parse(chip, body, length, offsets, count, values) == -1
        assert values[0] == 123
    if chip:
        duplicate = body + body[12:28]
        assert native.mt_mib_parse(chip, duplicate, len(duplicate), offsets, count, values) == -1
        for tag, length, offset in ((1, 8, 19), (0, 7, 19), (0, 8, 21)):
            bad = struct.pack("<HHIQ", tag, length, offset, 33)
            assert native.mt_mib_parse(chip, bad, len(bad), offsets, 1, values) == -1
    assert native.mt_mib_request(chip, 0, offsets, count, output, 1) == -1
    assert native.mt_mib_request(chip, 2, offsets, count, output, 256) == -1
    assert native.mt_mib_request(chip, 0, offsets, 0, output, 256) == -1
    duplicate = (ct.c_uint32 * 2)(11, 11)
    assert native.mt_mib_request(chip, 0, duplicate, 2, output, 256) == -1


def test_mib_wrap_reset(native):
    value = ct.c_uint64()
    assert native.mt_mib_delta(0xFFFFFFF0, 16, 32, 100, ct.byref(value))
    assert value.value == 32
    assert native.mt_mib_delta(0xFFFFFFFFFFFFFFF0, 16, 64, 100, ct.byref(value))
    assert value.value == 32
    assert not native.mt_mib_delta(10000, 10, 32, 100, ct.byref(value))
    assert not native.mt_mib_delta(1, 10000, 64, 100, ct.byref(value))
    assert not native.mt_mib_delta(0x100000000, 1, 32, 100, ct.byref(value))


@pytest.mark.parametrize("fail", range(7))
@pytest.mark.parametrize("enabled", [0, 1])
def test_g5_restores_after_fault(native, fail, enabled):
    assert native.parity_g5_fault(fail, enabled) == 0


@pytest.mark.parametrize("chip", [0, 1])
@pytest.mark.parametrize("mode", range(4))
def test_mcu_stale_timeout_error_and_truncation(native, chip, mode):
    assert native.parity_mcu_fault(chip, mode) == 0


@pytest.mark.parametrize(
    ("chip", "rate", "powers"),
    [(0, 0, (0,)), (0, 1, (0, -8, -16)), (1, 1, (0, -8, -16, -32)), (1, 2, (0, -8, -16, -32))],
)
def test_tx_shared_bytes(native, chip, rate, powers):
    from types import SimpleNamespace

    from research.dual_radio_probe import fixed_rate_txwi
    from research.mt7925_tx_probe import build_txwi
    from research.tx_power_probe import power_txwi

    dev = SimpleNamespace(_build_txwi=lambda f, s, p: m.Mt7921uDevice._build_txwi(None, f, s, p))
    for seq in (0, 17, 4095):
        for power in powers:
            for multicast in (True, False):
                frame = bytearray(
                    m.build_probe_request(bytes.fromhex("020000000001"), b"test", seq)
                )
                frame[4] = 255 if multicast else 2
                frame = bytes(frame)
                out = ct.create_string_buffer(64)
                assert native.mt_probe_txwi(chip, frame, len(frame), seq, rate, power, out) == 64
                if chip:
                    reference = build_txwi(
                        frame, seq, power, disable_mat=True, rate="ofdm6" if rate == 1 else "ofdm54"
                    )
                elif rate:
                    reference = power_txwi(dev, frame, seq, power)
                else:
                    reference = fixed_rate_txwi(dev, frame, seq, "cck1", True)
                assert out.raw == reference


def test_tx_invalid_inputs(native):
    frame = b"\x40\x00" + bytes(22)
    out = ct.create_string_buffer(b"x" * 64, 64)
    for chip, rate, power in (
        (0, 2, 0),
        (0, 1, -32),
        (1, 0, 0),
        (1, 1, 1),
        (1, 1, -33),
        (2, 1, 0),
        (0, 0, -8),
    ):
        assert native.mt_probe_txwi(chip, frame, len(frame), 0, rate, power, out) == -1
        assert out.raw == b"x" * 64
    for bad in (b"", frame[:23], b"\xc0" + frame[1:], frame + bytes(513)):
        assert native.mt_probe_txwi(1, bad, len(bad), 0, 1, 0, out) == -1
    assert native.mt_probe_txwi(1, frame, len(frame), 4096, 1, 0, out) == -1


@pytest.mark.parametrize("chip", [0, 1])
@pytest.mark.parametrize("fmt", range(4))
def test_txs_shared_bytes(native, chip, fmt):
    from research.dual_radio_probe import tx_status_records
    from research.mt7925_tx_probe import tx_status

    prefix, size = (16, 48) if chip else (8, 32)
    record = [0x4B | (fmt << 23) | (3 << 16), 17 << 20 | 250, 0, 3 << 24, 0, 7 << 25]
    raw = struct.pack("<I", prefix + size) + bytes(prefix - 4)
    raw += struct.pack("<6I", *record) + bytes(size - 24)
    values = (ct.c_int * 160)()
    assert native.parity_txs(chip, raw, len(raw), values) == 1
    reference = (tx_status if chip else tx_status_records)(raw)[0]
    assert values[0] == reference["format"]
    assert values[1] == reference["rate_raw" if chip else "rate"]
    assert values[2] == reference["power_raw" if chip else "tx_power_raw"]
    assert list(values[3:8]) == [-6, 17, 3, 3, 3]
    assert values[8] == (chip == 1 and fmt == 0)
    assert values[9] == (7 if values[8] else 0)
    for end in range(len(raw)):
        assert native.parity_txs(chip, raw, end, values) == -1
    assert native.parity_txs(chip, raw + bytes(8), len(raw) + 8, values) == 1
    bad = bytearray(raw)
    bad[3] = 2 << 3
    assert native.parity_txs(chip, bytes(bad), len(bad), values) == -1
    bad = bytearray(raw)
    bad[0] -= 1
    assert native.parity_txs(chip, bytes(bad), len(bad), values) == -1


@pytest.mark.parametrize("rate", [1, 2])
@pytest.mark.parametrize("mode", range(6))
def test_rate_table_write_and_faults(native, rate, mode):
    words = (ct.c_uint * 9)()
    result = native.parity_rate_table(rate, mode, words)
    assert (result == 0) == (mode == 0)
    if mode == 0:
        from research.mt7925_tx_probe import set_ofdm_rate

        class Device:
            CHIP = m.CHIP_MT7925

            def __init__(self):
                self.writes = []

            def wr(self, address, value):
                self.writes.extend((address, value))

            def rr(self, address):
                return 0

        dev = Device()
        set_ofdm_rate(dev, "ofdm6" if rate == 1 else "ofdm54")
        assert list(words[:6]) == dev.writes
    if mode == 5:
        assert tuple(words[6:]) == (3, 100, 100)


@pytest.fixture(scope="module")
def native_probe(tmp_path_factory):
    out = tmp_path_factory.mktemp("c-probe") / "probe"
    sources = [
        "mt76_radio_probe.c",
        "mt7921_radio.c",
        "mt7921_dev.c",
        "mt7921_mcu.c",
        "mt7921_usb.c",
        "mt7921_chip.c",
        "mt7921_rxd.c",
        "mt7921_rxd_connac3.c",
    ]
    subprocess.run(  # noqa: S603 -- fixed compiler and local source files
        [
            "/usr/bin/clang",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            *(str(ROOT / "c" / name) for name in sources),
            "-framework",
            "IOKit",
            "-framework",
            "CoreFoundation",
            "-o",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out


@pytest.mark.parametrize(
    "extra",
    [
        ["--transmit", "1"],
        ["--transmit", "61", "--acknowledge-experimental-transmit"],
        ["--transmit", "1", "--rate", "cck1", "--acknowledge-experimental-transmit"],
        ["--transmit", "1", "--power-code", "-1", "--acknowledge-experimental-transmit"],
        ["--transmit", "1", "--power-code", "1", "--acknowledge-experimental-transmit"],
        ["--transmit", "20", "--seconds", "1", "--acknowledge-experimental-transmit"],
        [
            "--transmit",
            "1",
            "--band",
            "6GHz",
            "--channel",
            "37",
            "--acknowledge-experimental-transmit",
        ],
        ["--g5-cycle"],
        ["--seconds", "NaN"],
        ["--seconds", "0"],
        ["--channel", "37"],
        ["--channel", "36junk"],
        ["--power-code", "-8"],
        ["--unknown"],
    ],
)
def test_cli_rejects_before_usb(native_probe, extra):
    result = subprocess.run(  # noqa: S603 -- compiled local test executable, no shell
        [str(native_probe), "--usb-id", "0846:9072", "--fw", "/nonexistent-test-firmware", *extra],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert "Missing/unpinned" not in result.stderr
    assert not result.stdout


def test_passive_cli_needs_firmware_not_tx_ack(native_probe):
    result = subprocess.run(  # noqa: S603 -- compiled local test executable, no shell
        [str(native_probe), "--usb-id", "0846:9072", "--fw", "/nonexistent-test-firmware"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert "Missing/unpinned" in result.stderr


@pytest.mark.parametrize("mode", range(3))
def test_vendor_timeout_and_short_read(native, mode):
    assert native.parity_vendor_timeout(mode) == 0
