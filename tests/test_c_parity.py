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
    return lib


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
