# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
import sys

import pytest

from research import legacy_noise_hist_probe as p


@pytest.mark.parametrize(
    ("address", "bits"), [(p.CONTROL, 5), (p.RESET, 1 << 29), (p.OPTIONS, 0x30000)]
)
@pytest.mark.parametrize("current", [0, 0xDEADBEEF, 0x7FFFFFFF])
def test_masked_writes_preserve_other_bits(address, bits, current):
    result = p.masked_value(address, current, bits)
    assert result & p.MASKS[address] == bits
    assert result & ~p.MASKS[address] == current & ~p.MASKS[address]


@pytest.mark.parametrize(
    ("address", "current", "bits"),
    [
        (0x83088600, 0, 0),
        (p.CONTROL, 0xFFFFFFFF, 0),
        (p.CONTROL, -1, 0),
        (p.CONTROL, True, 0),
        (p.CONTROL, 0, 8),
        (p.OPTIONS, 0, 1),
        (p.RESET, 0, -1),
    ],
)
def test_refuses_other_addresses_unmapped_values_or_masks(address, current, bits):
    with pytest.raises(ValueError, match="fixed registers"):
        p.masked_value(address, current, bits)


def test_only_eleven_source_bounded_bin_reads():
    class Device:
        CHIP = p.m.CHIP_MT7921

        def __init__(self):
            self.reads = []

        def rr(self, address):
            self.reads.append(address)
            return address

    dev = Device()
    assert p.bins(dev) == list(range(0x83088600, 0x8308862C, 4))
    assert tuple(dev.reads) == p.BIN_REGISTERS
    dev.CHIP = "other"
    with pytest.raises(ValueError, match="MT7961"):
        p.bins(dev)


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--stimulus"],
        ["--enable-histogram", "--stimulus"],
        ["--enable-histogram", "--channel", "37"],
        [
            "--enable-histogram",
            "--stimulus",
            "--acknowledge-experimental-transmit",
            "--channel",
            "1",
        ],
    ],
)
def test_opt_in_before_usb(monkeypatch, flags):
    monkeypatch.setattr(sys, "argv", ["legacy_noise_hist", *flags])
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("USB opened"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2


def test_reset_pulse_preserves_other_bits():
    class Device:
        word = 0x81005555

        def __init__(self):
            self.writes = []

        def rr(self, address):
            assert address == p.RESET
            return self.word

        def wr(self, address, word):
            assert address == p.RESET
            self.writes.append(word)
            self.word = word

    dev = Device()
    p.reset(dev)
    assert dev.writes == [0x81005555, 0xA1005555, 0x81005555]


def test_cca_crosscheck_uses_only_established_primary_offset():
    class Device:
        def mcu_cmd_word(self, command, request, timeout):
            assert command == p.m.MCU_EXT_CMD(0x5A)
            assert request == struct.pack("<IIQ", 0, 11, 0)
            assert timeout == 1000
            return bytes(28) + struct.pack("<I", 123)

        def reply_body(self, raw):
            return raw

    value, opened, closed = p.cca_sample(Device())
    assert value == 123
    assert opened <= closed
