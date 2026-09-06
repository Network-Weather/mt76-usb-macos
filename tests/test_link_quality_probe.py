# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import link_quality_probe as p


def fixture():
    body = bytearray([0xA5] * 40)
    struct.pack_into("<HH", body, 4, 1, 36)
    for i in range(4):
        body[8 + i * 8 + 5] = 0
    return body


def test_unready_bytes_are_never_exposed_as_measurements():
    out = p.parse(fixture())
    assert out["rows"] == [
        {"slot": i, "ready": False, "medium_busy_available": False} for i in range(4)
    ]


def test_only_ready_row_has_signal_and_speed_but_never_busy_measurement():
    body = fixture()
    struct.pack_into("<bbHBB", body, 16, -73, 0, 144, 0, 1)
    out = p.parse(body)["rows"][1]
    assert out["rssi_encoding_signed8"] == -73
    assert out["link_speed_raw_u16"] == 144
    assert out["medium_busy_is_zero"]
    assert not out["medium_busy_available"]
    body[21] = 2
    assert not p.parse(body)["rows"][1]["ready"]


@pytest.mark.parametrize("data", [bytes(7), bytes(39), bytes(40), bytes(41)])
def test_wrong_shape_rejected(data):
    with pytest.raises(ValueError, match="four-row"):
        p.parse(data)


def test_exact_read_only_request():
    assert p.request() == struct.pack("<4xHH", 1, 4)
