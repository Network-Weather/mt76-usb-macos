# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import mt7925_thermal_probe as p


def event(value=45, tail=b"private USB padding"):
    body = struct.pack("<4xHH4xI", 0, 12, value)
    raw = bytearray(44)
    struct.pack_into("<I", raw, 0, (p.m.PKT_TYPE_RX_EVENT << 27) | (44 + len(body)))
    raw[36:38] = bytes((0x35, 7))
    return bytes(raw) + body + tail


def test_temperature_adc_and_no_padding_export():
    assert p.request(0).hex() == "000000000000080000000000"
    assert p.request(1).hex() == "000000000000080000010000"
    assert p.summarize(event(), 7, 0)["reported_temperature_c"] == 45
    assert p.summarize(event(0xFFFFFFFB), 7, 0)["reported_temperature_c"] == -5
    result = p.summarize(event(68), 7, 1)
    assert result["sensor_result_raw_u32"] == 68
    assert "reported_temperature_c" not in result
    assert "private" not in repr(result)


@pytest.mark.parametrize("action", [True, -1, 2, 12, 0.0, "0"])
def test_no_other_actions(action):
    with pytest.raises(ValueError, match="only temperature"):
        p.request(action)


@pytest.mark.parametrize(
    ("offset", "value"), [(36, 1), (37, 8), (48, 5), (50, 8), (52, 1), (44, 1)]
)
def test_mismatched_or_malformed_reply_rejected(offset, value):
    raw = bytearray(event())
    raw[offset] = value
    with pytest.raises(ValueError, match=r"matching|unexpected"):
        p.summarize(raw, 7, 0)


def test_wrong_packet_and_truncated_event_rejected():
    raw = bytearray(event())
    struct.pack_into("<I", raw, 0, (2 << 27) | 60)
    with pytest.raises(ValueError, match="matching"):
        p.summarize(raw, 7, 0)
    with pytest.raises(ValueError, match="short"):
        p.summarize(bytes(40), 7, 0)
    with pytest.raises(ValueError, match="matching"):
        p.summarize(event()[:59], 7, 0)


@pytest.mark.parametrize(("chip", "option"), [(p.m.CHIP_MT7921, 7), (p.m.CHIP_MT7925, 7)])
def test_wrong_chip_or_set_framing_never_sends(chip, option):
    class Device:
        CHIP = chip

        def uni_option(self, *_):
            return option

        def mcu_uni(self, *_args, **_kwargs):
            pytest.fail("unexpected command")

    with pytest.raises(ValueError, match="QUERY_ACK"):
        p.query(Device(), 0)
