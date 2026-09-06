# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
import sys

import pytest

from research import tx_airtime_probe as p


def test_length_reversals_and_data_symbol_difference():
    sizes = [len(p.frame(i * 4, b"nonce123", "length")) for i in range(5)]
    assert sizes == [65, 193, 65, 193, 65]
    assert p.payload_symbols_us(65) == 48
    assert p.payload_symbols_us(193) == 124
    assert 4 * (p.payload_symbols_us(193) - p.payload_symbols_us(65)) == 304


def test_width_plan_has_fixed_payload_and_known_descriptor_widths():
    dev = p.m.device_class_for(p.m.CHIP_MT7925)()
    assert p.WIDTH_PLAN == (20, 40, 20, 40, 20)
    for i, width in enumerate(p.WIDTH_PLAN):
        payload = p.frame(i * 4, b"nonce123", "width")
        assert len(payload) == 65
        txd = p.p.descriptor(dev, payload, i * 4, 0x488, fixed_bw=True, width_mhz=width)
        words = struct.unpack("<16I", txd)
        assert (words[6] >> 22) & 15 == (8 if width == 20 else 9)
        assert words[3] & 1
        assert words[3] & (1 << 28)
        assert payload[4:10] == b"\xff" * 6
        assert payload[2:4] == bytes(2)


@pytest.mark.parametrize("length", [64, 66, 192, 194, True, 65.0])
def test_model_refuses_uncontrolled_sizes(length):
    with pytest.raises(ValueError, match="only the two controlled"):
        p.payload_symbols_us(length)


@pytest.mark.parametrize(
    ("sequence", "nonce", "suite"),
    [
        (20, b"nonce123", "width"),
        (-1, b"nonce123", "length"),
        (0, b"short", "width"),
        (0, b"nonce123", "other"),
    ],
)
def test_frame_guards(sequence, nonce, suite):
    with pytest.raises(ValueError, match=r"bounded|eight-byte"):
        p.frame(sequence, nonce, suite)


@pytest.mark.parametrize(
    "flags", [[], ["--acknowledge-consuming-counters"], ["--acknowledge-experimental-transmit"]]
)
def test_both_acknowledgments_required_before_usb(monkeypatch, flags):
    monkeypatch.setattr(sys, "argv", ["probe", *flags])
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("unexpected USB"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2


def test_only_source_mapped_counters_selected():
    assert p.OFFSETS == (22, 23, 24, 25, 28, 31, 85, 86, 87)
