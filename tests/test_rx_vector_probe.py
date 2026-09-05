# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research.rx_vector_probe import he_fields, vectors


@pytest.mark.parametrize(
    ("chip", "fixed", "shift", "g2", "g3", "g5"),
    [("mt7921", 24, 11, 8, 8, 72), ("mt7925", 32, 16, 16, 16, 96)],
)
def test_group_boundaries_and_dma_length(chip, fixed, shift, g2, g3, g5):
    prefix = bytearray(fixed + 16 + 16 + g2)
    struct.pack_into("<I", prefix, 4, 31 << shift)
    raw = prefix + b"\x33" * g3 + b"\x55" * g5
    struct.pack_into("<H", raw, 0, len(raw))
    decoded = vectors(raw + b"payload should not be parsed", chip)
    assert decoded["g3"] == (0x33333333,) * (g3 // 4)
    assert decoded["g5"] == (0x55555555,) * (g5 // 4)
    struct.pack_into("<H", raw, 0, len(raw) - 1)
    assert vectors(raw + b"padding must not satisfy bounds", chip)["error"] == "short_g5"


def test_connac3_he_indexes_start_at_group3():
    g5 = [0] * 24
    g5[1] = 4
    g5[5] = (37 << 10) | (5 << 17)
    g5[9] = 9 << 8
    v = {"g3": (0,) * 4, "g5": tuple(g5)}
    assert he_fields(v, 8) == {"bss_color": 37, "uplink": 1, "spatial_reuse": 9, "txop": 5}
    assert he_fields(v, 1) is None
    assert he_fields({"g3": (0, 0)}, 8) is None


def test_connac2_he_indexes_are_group5_relative_not_shifted_rcpi_origin():
    g5 = [0] * 18
    g5[0] = 1 << 31
    g5[9] = 9 << 8
    g5[12] = 37 | (127 << 6)
    g5[6] = 0xFFFFFFFF  # RCPI origin is deliberately unrelated.
    v = {"g3": (0,) * 2, "g5": tuple(g5)}
    for mode in (8, 9, 10, 11):
        assert he_fields(v, mode) == {"bss_color": 37, "uplink": 1, "spatial_reuse": 9, "txop": 127}
    assert he_fields(v, 1) is None
    assert he_fields(v, 13) is None


@pytest.mark.parametrize(("g3", "g5"), [(2, 17), (2, 24), (4, 18), (4, 23), (0, 18)])
def test_he_rejects_truncated_or_cross_chip_vector_shapes(g3, g5):
    assert he_fields({"g3": (0,) * g3, "g5": (0,) * g5}, 8) is None
