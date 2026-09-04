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


def test_he_indexes_start_at_group3_and_legacy_is_not_he():
    g5 = [0] * 24
    g5[1] = 4
    g5[5] = (37 << 10) | (5 << 17)
    g5[9] = 9 << 8
    v = {"g3": (0,) * 4, "g5": tuple(g5)}
    assert he_fields(v, 8) == {"bss_color": 37, "uplink": 1, "spatial_reuse": 9, "txop": 5}
    assert he_fields(v, 1) is None
    assert he_fields({"g3": (0, 0)}, 8) is None
