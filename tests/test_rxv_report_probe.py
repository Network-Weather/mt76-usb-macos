# SPDX-License-Identifier: BSD-3-Clause-Clear
import itertools
import sys

import pytest

from research import rxv_report_probe as p


def test_only_rx_report_bit_changes():
    off = p.request(False)
    on = p.request(True)
    assert off == bytes.fromhex("000000000100080000000000")
    assert on == bytes.fromhex("000000000100080001000000")
    assert on[9] == 0  # TX-vector reporting never enabled.


def test_traced_register_reads_only_and_extracts_rx_tx():
    class Device:
        CHIP = p.m.CHIP_MT7925

        def rr(self, address):
            assert address == 0x820E3014
            return 0x80

    assert p.report_register(Device()) == {
        "register": "0x820e3014",
        "raw": "0x80",
        "rx_bit7": 1,
        "tx_bit8": 0,
    }


def test_report_register_rejects_other_chip_before_read():
    class Device:
        CHIP = p.m.CHIP_MT7921

    with pytest.raises(ValueError, match="MT7925-only"):
        p.report_register(Device())


@pytest.mark.parametrize("word", [0xFFFFFFFF, -1, True])
def test_report_register_rejects_invalid_read(word):
    class Device:
        CHIP = p.m.CHIP_MT7925

        def rr(self, _):
            return word

    with pytest.raises(ValueError, match="invalid report"):
        p.report_register(Device())


@pytest.mark.parametrize("value", [0, 1, 2, None, "True"])
def test_no_arbitrary_enable_values(value):
    with pytest.raises(ValueError, match="boolean"):
        p.request(value)


def test_opt_in_required_before_usb(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["rxv_report", "--chip", "mt7925"])
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("USB opened"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("both", [False, True])
def test_only_descriptor_resolved_in_endpoints_are_read(monkeypatch, both):
    class Device:
        ep_in_pkt_rx = 0x84
        ep_in_cmd_resp = 0x85

        def __init__(self):
            self.reads = []

        def bulk_in(self, endpoint, size, timeout):
            self.reads.append(endpoint)
            assert size == 4096
            assert timeout == (20 if both else 50)
            return bytes(4)

    clock = itertools.count(step=0.1)
    monkeypatch.setattr(p.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(p.m, "decoder_for", lambda _: lambda _raw: None)
    dev = Device()
    result = p.receive(dev, both)
    allowed = (0x84, 0x85) if both else (0x84,)
    assert dev.reads == [allowed[i % len(allowed)] for i in range(len(dev.reads))]
    assert result["transfers"] == len(dev.reads)
    assert set(result["endpoint_transfers"]) == {f"{ep:02x}" for ep in allowed}
