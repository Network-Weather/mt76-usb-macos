# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import rdd_stop_probe as p


def event(chip, eid, body=b"", seq=7, ext=0):
    header = 44 if chip == p.m.CHIP_MT7925 else 36
    raw = bytearray(header)
    struct.pack_into("<I", raw, 0, p.m.PKT_TYPE_RX_EVENT << 27 | (header + len(body)))
    raw[header - 8 : header - 6] = bytes((eid, seq))
    raw[header - 4] = ext
    return bytes(raw) + body + b"private USB tail"


def test_only_stop_request():
    assert p.request(p.m.CHIP_MT7921) == bytes(8)
    assert p.request(p.m.CHIP_MT7925) == bytes.fromhex("0000000000000c000000000000000000")
    with pytest.raises(ValueError, match="pinned"):
        p.request("unknown")


@pytest.mark.parametrize(("chip", "cid"), [(p.m.CHIP_MT7921, 0x8F), (p.m.CHIP_MT7925, 0x19)])
def test_bounded_status(chip, cid):
    result = p.summarize(event(chip, 1, struct.pack("<II", cid, 0xC00000BB)), chip, 7)
    assert result["command_result_status"] == 0xC00000BB
    assert result["body_bytes"] == 8
    assert "private" not in repr(result)
    assert p.summarize(event(chip, 1, seq=8), chip, 7) is None
    assert p.summarize(bytes(20), chip, 7) is None


def test_legacy_not_found_and_no_arbitrary_payload():
    result = p.summarize(event(p.m.CHIP_MT7921, 0xFD, b"private"), p.m.CHIP_MT7921, 7)
    assert result["command_not_found_event"]
    assert "private" not in repr(result)


@pytest.mark.parametrize(
    ("chip", "eid", "ext"),
    [
        (p.m.CHIP_MT7921, 0xED, 0x3A),
        (p.m.CHIP_MT7921, 0x50, 0),
        (p.m.CHIP_MT7921, 0x60, 0),
        (p.m.CHIP_MT7925, 0x11, 0),
    ],
)
def test_unsolicited_candidate_metadata_only(chip, eid, ext):
    result = p.summarize(event(chip, eid, b"private", seq=0, ext=ext), chip, 7)
    assert result["candidate_rdd_event"]
    assert not result["sequence_matches"]
    assert "private" not in repr(result)
    assert p.summarize(event(chip, 2, seq=0), chip, 7) is None


def test_invalid_length_and_packet_type():
    chip = p.m.CHIP_MT7925
    raw = bytearray(event(chip, 1))
    struct.pack_into("<H", raw, 0, 65535)
    assert p.summarize(raw, chip, 7) is None
    struct.pack_into("<I", raw, 0, 44)
    assert p.summarize(raw, chip, 7) is None


def test_wrong_option_fails_before_send():
    class Device:
        CHIP = p.m.CHIP_MT7925

        def uni_option(self, cid, query):
            assert cid == 0x19
            assert query is False
            return 3

    with pytest.raises(ValueError, match="SET ACK7"):
        p.stop(Device())


def test_receive_start_exact_shape_and_success_gate(monkeypatch):
    from research import rdd_receive_probe as r

    assert r.start_request() == bytes.fromhex("0000000000000c000100000100000000")

    class Device:
        CHIP = p.m.CHIP_MT7925
        sent = False

        def uni_option(self, *_):
            return 7

        def mcu_uni(self, cid, payload, **kwargs):
            assert cid == 0x19
            assert payload == r.start_request()
            assert kwargs == {"query": False, "wait": False, "timeout": 1000}
            self.sent = True

    dev = Device()
    for events in ([], [{"command_result_status": 1}], [{"command_not_found_event": True}]):
        with pytest.raises(ValueError, match="successful STOP"):
            r.start(dev, {"events": events})
        assert not dev.sent
    monkeypatch.setattr(r, "collect", lambda _: {"collected": True})
    assert r.start(dev, {"events": [{"command_result_status": 0}]}) == {"collected": True}
    assert dev.sent


@pytest.mark.parametrize("chip", [p.m.CHIP_MT7921, "unknown"])
def test_receive_start_never_on_legacy(chip):
    from research import rdd_receive_probe as r

    class Device:
        CHIP = chip

    with pytest.raises(ValueError, match="MT7925"):
        r.start(Device(), {"events": [{"command_result_status": 0}]})


def test_new_chip_state_exact_byte_offsets_and_chip_guard():
    from research import rdd_receive_probe as r

    class Device:
        CHIP = p.m.CHIP_MT7925

        def rr(self, address):
            return {0x022303B0: 0x11223301, 0x02221CCC: 0xAABB00CC}[address]

    assert r.state(Device()) == {"host_enabled_byte": 1, "prerequisite_byte_02221ccd": 0}
    Device.CHIP = p.m.CHIP_MT7921
    with pytest.raises(ValueError, match="MT7925-only"):
        r.state(Device())
