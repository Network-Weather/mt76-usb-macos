# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Identical bounded routing bytes through Python and C; native lifecycle replay."""

import ctypes
import random
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from mt76_session import packet_kind

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native IOKit transport")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    directory = tmp_path_factory.mktemp("c-session")
    output = directory / "session.dylib"
    sources = ["mt76_session.c", "mt7921_mcu.c", "mt7921_dev.c", "mt7921_usb.c", "mt7921_chip.c"]
    subprocess.run(  # noqa: S603 -- fixed local compiler and sources
        [
            "/usr/bin/clang",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-dynamiclib",
            "-DMT_SESSION_NO_MAIN",
            "-I",
            str(ROOT / "c"),
            str(ROOT / "c/test_session.c"),
            *(str(ROOT / "c" / name) for name in sources),
            "-framework",
            "IOKit",
            "-framework",
            "CoreFoundation",
            "-pthread",
            "-o",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    lib = ctypes.CDLL(str(output))
    lib.mt_session_packet_kind.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_int]
    lib.mt_session_packet_kind.restype = ctypes.c_int
    lib.session_replay_test.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.session_replay_test.restype = ctypes.c_int
    return lib


@pytest.mark.parametrize("chip", [0, 1])
@pytest.mark.parametrize("mode", range(7))
def test_native_session_faults_and_replay(native, chip, mode):
    assert native.session_replay_test(chip, mode) == 0


@pytest.mark.parametrize("chip", [0, 1])
def test_same_packet_routing_for_every_type_flag_and_boundary(native, chip):
    names = ["malformed", "frame", "reply", "status"]
    for kind in range(32):
        for flag in range(16):
            raw = struct.pack("<I", 64 | kind << 27 | flag << 16) + bytes(60)
            for length in (0, 3, 4, 31, 32, 35, 36, 43, 44, 63, 64):
                sample = raw[:length]
                actual = names[native.mt_session_packet_kind(sample, len(sample), chip)]
                assert actual == packet_kind(sample, "mt7925" if chip else "mt7921")
    rng = random.Random(76)  # noqa: S311 -- deterministic malformed descriptor corpus
    for _ in range(1000):
        raw = rng.randbytes(rng.randrange(0, 128))
        actual = names[native.mt_session_packet_kind(raw, len(raw), chip)]
        assert actual == packet_kind(raw, "mt7925" if chip else "mt7921")


@pytest.fixture(scope="module")
def native_probe(tmp_path_factory):
    output = tmp_path_factory.mktemp("session-cli") / "probe"
    sources = [
        "mt76_session_probe.c",
        "mt76_session.c",
        "mt7921_mcu.c",
        "mt7921_dev.c",
        "mt7921_usb.c",
        "mt7921_chip.c",
        "mt7921_radio.c",
        "mt7921_rxd.c",
        "mt7921_rxd_connac3.c",
    ]
    subprocess.run(  # noqa: S603 -- fixed compiler and local source list
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
            "-pthread",
            "-o",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    return output


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--usb-id", "ffff:ffff"],
        ["--usb-id", "0e8d:7961", "--seconds", "0"],
        ["--usb-id", "0e8d:7961", "--hop-seconds", "-1"],
        ["--usb-id", "0e8d:7961", "--mib-seconds", "99999"],
        ["--usb-id", "0e8d:7961", "--named-counters", "--band", "6GHz"],
    ],
)
def test_native_probe_invalid_arguments_refuse_before_usb(native_probe, args):
    result = subprocess.run([str(native_probe), *args], capture_output=True, timeout=5)  # noqa: S603 -- local CLI refusal test
    assert result.returncode == 2
    assert not result.stdout
