# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

import mt7921u as m
from research.dual_radio_probe import fixed_rate_txwi
from research.tx_power_probe import power_txwi, signed8


def test_negative_code_only_changes_documented_field():
    dev = object.__new__(m.Mt7921uDevice)
    frame = m.build_probe_request(bytes.fromhex("020000000001"), b"test")
    baseline = fixed_rate_txwi(dev, frame, 3, "ofdm6", True)
    for code in (0, -8, -16, -32):
        changed = power_txwi(dev, frame, 3, code)
        assert baseline[:8] == changed[:8]
        assert baseline[12:] == changed[12:]
        delta = struct.unpack_from("<I", baseline, 8)[0] ^ struct.unpack_from("<I", changed, 8)[0]
        assert delta & ~(63 << 24) == 0
        assert struct.unpack_from("<I", changed, 8)[0] >> 24 & 63 == code & 63
    with pytest.raises(ValueError, match="attenuation"):
        power_txwi(dev, frame, 3, 1)


def test_signed_byte_conversion_masks_other_fields():
    assert signed8(0x1234FF) == -1
    assert signed8(0x80) == -128
    assert signed8(0x7F) == 127
