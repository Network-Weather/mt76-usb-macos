# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import wideband_signal_probe as p


def test_bytes_are_candidates_not_calibrated_labels():
    assert p.fields(0x807F00FF) == {
        "word": "0x807f00ff",
        "bytes_low_to_high": [255, 0, 127, 128],
        "signed8_candidates": [-1, 0, 127, -128],
        "firmware_instantaneous_fields": {"inst_ib_raw_s8": -128, "inst_wb_raw_s8": 127},
    }


@pytest.mark.parametrize("word", [-1, 0xFFFFFFFF, True, None])
def test_invalid_mmio_rejected(word):
    with pytest.raises(ValueError, match=r"read|word|mapped"):
        p.fields(word)


def test_sample_reads_only_one_exact_old_chip_register():
    class Device:
        CHIP = p.m.CHIP_MT7921

        def rr(self, address):
            assert address == 0x830003E0
            return 123

    assert p.sample(Device())["word"] == "0x7b"
    dev = Device()
    dev.CHIP = p.m.CHIP_MT7925
    with pytest.raises(ValueError, match="MT7961"):
        p.sample(dev)


@pytest.mark.parametrize("offset", [1, -16, True, "-8"])
def test_power_configuration_is_bounded(offset):
    with pytest.raises(ValueError, match="negative-four/eight"):
        p.prepared(None, 0, b"12345678", offset)


def test_negative_offset_preserves_all_other_descriptor_bits(monkeypatch):
    raw = bytearray(72)
    struct.pack_into("<I", raw, 12, 0x1234567)
    monkeypatch.setattr(p, "packet", lambda *_: (b"own", bytes(raw)))
    payload, wire = p.prepared(None, 0, b"12345678", -8)
    assert payload == b"own"
    assert struct.unpack_from("<I", wire, 12)[0] == 0xE1234567
    assert wire[:12] == raw[:12]
    assert wire[16:] == raw[16:]


def test_collection_rejects_other_packet_counts():
    with pytest.raises(ValueError, match="four packets"):
        p.acquire(None, None, {})
