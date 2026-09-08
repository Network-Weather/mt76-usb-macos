# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Retained-state diagnostic boundaries, without USB or firmware."""

import json
import struct

import pytest

from research import efuse_reapply_probe as probe


def reply(body):
    header = bytearray(probe.m.MCU_RXD_LEN)
    struct.pack_into("<I", header, 0, 7 << 27 | len(header) + len(body))
    return bytes(header) + body


class Device:
    CHIP = "mt7921"
    MCU_RXD_LEN = probe.m.MCU_RXD_LEN
    msg_seq = 7
    mcu_wait_dropped_frames = 0
    mcu_wait_stale_events = 0

    def __init__(self, body=None):
        self.raw = reply(body if body is not None else struct.pack("<II", 0x21, 0))
        self.calls = []
        self.closed = False
        self.registers = {
            probe.m.MT_CONN_ON_MISC: 3,
            probe.m.MT_WFDMA_HOST_CONFIG: 0x7D40,
            probe.m.MT_SWDEF_MODE: 0x820F3000,
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def rr(self, address):
        return self.registers[address]

    def mcu_cmd_word(self, command, payload):
        self.calls.append((command, payload))
        return self.raw

    def set_monitor_mode(self):
        self.calls.append("monitor")

    def set_sniffer(self, enabled):
        self.calls.append(("sniffer", enabled))

    def alive(self):
        return True


def test_reapply_exact_factory_load_and_zero_result(capsys):
    dev = Device()
    probe.reapply(dev)
    assert dev.calls == [(probe.m.MCU_EXT_CMD(0x21), b"\x00\x01\x00\x00")]
    result = json.loads(capsys.readouterr().out)
    assert result["matches_zero_result"]
    assert result["body_bytes"] == 8
    assert result["sequence"] == 7


@pytest.mark.parametrize("body", [b"", b"private contents", struct.pack("<II", 0x21, 1)])
def test_unknown_reply_not_exported_or_called_zero(body, capsys):
    probe.reapply(Device(body))
    result = json.loads(capsys.readouterr().out)
    assert not result["matches_zero_result"]
    assert "result_words_raw" not in result
    assert "private contents" not in json.dumps(result)


@pytest.mark.parametrize("size", [0, 35, 65535])
def test_truncated_declared_reply_refused(size):
    dev = Device()
    dev.raw = struct.pack("<H", size) + dev.raw[2:]
    with pytest.raises(RuntimeError, match="length"):
        probe.reapply(dev)


@pytest.mark.parametrize("action", ["efuse", "sham", "monitor"])
def test_bounded_actions_no_reset_and_close(action, monkeypatch):
    dev = Device()
    monkeypatch.setattr(probe.m, "open_device", lambda _id: dev)
    events = []
    monkeypatch.setattr(probe, "emit", lambda name, **fields: events.append((name, fields)))
    monkeypatch.setattr(probe, "receive", lambda *_: {"counts": {}})
    sweeps = []
    monkeypatch.setattr(
        probe, "sweep", lambda _dev, phase, seconds: sweeps.append((phase, seconds))
    )
    monkeypatch.setattr(probe.time, "sleep", lambda *_: None)
    assert (
        probe.main(["--usb-id", "0e8d:7961", "--action", action, "--acknowledge-retained-state"])
        == 0
    )
    assert sweeps == [("before", 3), ("after", 3)]
    assert dev.closed
    assert dev.evt_ep4
    assert events[0][1]["swdef_mode_readback"] == 0x820F3000
    if action == "sham":
        assert not dev.calls
    elif action == "monitor":
        assert dev.calls == ["monitor", ("sniffer", True)]
    else:
        assert len(dev.calls) == 1


@pytest.mark.parametrize(
    ("address", "value"),
    [
        (probe.m.MT_CONN_ON_MISC, 0),
        (probe.m.MT_CONN_ON_MISC, 0xFFFFFFFF),
        (probe.m.MT_WFDMA_HOST_CONFIG, 0),
    ],
)
def test_invalid_retained_state_does_not_mutate(address, value, monkeypatch):
    dev = Device()
    dev.registers[address] = value
    monkeypatch.setattr(probe.m, "open_device", lambda _id: dev)
    assert (
        probe.main(["--usb-id", "0e8d:7961", "--action", "efuse", "--acknowledge-retained-state"])
        == 1
    )
    assert dev.closed
    assert not dev.calls


@pytest.mark.parametrize(
    "arguments",
    [
        ["--usb-id", "0e8d:7961", "--action", "efuse"],
        ["--usb-id", "0846:9072", "--action", "efuse", "--acknowledge-retained-state"],
        ["--usb-id", "0846:9072", "--action", "monitor", "--acknowledge-retained-state"],
    ],
)
def test_cli_refuses_before_open(arguments, monkeypatch):
    def unexpected(_id):
        pytest.fail("opened device for disallowed invocation")

    monkeypatch.setattr(probe.m, "open_device", unexpected)
    with pytest.raises(SystemExit) as error:
        probe.main(arguments)
    assert error.value.code == 2
