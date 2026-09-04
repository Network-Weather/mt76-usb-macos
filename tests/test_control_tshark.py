# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Optional independent decoder cross-check using synthetic control frames only."""

import shutil
import struct
import subprocess

import pytest

from research.control_frames import parse_control

TSHARK = shutil.which("tshark")


@pytest.mark.skipif(TSHARK is None, reason="optional tshark cross-check")
@pytest.mark.parametrize(("selector", "size"), [(0, 8), (4, 32), (8, 64), (10, 128)])
def test_compressed_blockack_against_tshark(selector, size):
    bits = 13 | (1 << (size * 8 - 1))
    frame = (
        struct.pack("<HH", 0x94, 123)
        + bytes.fromhex("020000000001020000000002")
        + struct.pack("<HH", 0x5004, (100 << 4) | selector)
        + bits.to_bytes(size, "little")
    )
    # DLT_IEEE802_11, no radiotap or FCS. All bytes are synthetic.
    pcap = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 105)
    pcap += struct.pack("<IIII", 100, 0, len(frame), len(frame)) + frame
    command = [TSHARK, "-r", "-", "-T", "fields"]
    for field in (
        "wlan.ba.control.ba_type",
        "wlan.fixed.ssc.sequence",
        "wlan.ba.bm",
        "_ws.malformed",
    ):
        command.extend(("-e", field))
    response = subprocess.run(command, input=pcap, capture_output=True, check=True, timeout=10)  # noqa: S603 -- known executable, fixed arguments, synthetic stdin
    ba_type, sequence, bitmap_text, malformed = response.stdout.decode().splitlines()[0].split("\t")
    decoded = parse_control(frame)
    bitmap = bytes.fromhex(bitmap_text.replace(":", ""))
    assert int(ba_type, 0) == decoded["ba_type"]
    assert int(sequence) == decoded["start_sequence"]
    assert len(bitmap) * 8 == decoded["bitmap_bits"]
    assert int.from_bytes(bitmap, "little").bit_count() == decoded["acknowledged"]
    assert not malformed
