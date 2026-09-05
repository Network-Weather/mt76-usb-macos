# SPDX-License-Identifier: BSD-3-Clause-Clear
from types import SimpleNamespace

import pytest

from research.lpon_clock import LPON_COUNTER, read_counter


@pytest.mark.parametrize("chip", ["mt7921", "mt7925"])
def test_read_only_one_exact_counter_address(chip):
    reads = []

    def rr(address):
        reads.append(address)
        return 1234

    result = read_counter(SimpleNamespace(CHIP=chip, rr=rr))
    assert reads == [LPON_COUNTER]
    assert result["value_raw"] == 1234
    assert result["host_before_seconds"] <= result["host_after_seconds"]


@pytest.mark.parametrize("value", [None, True, -1, 0xFFFFFFFF, 1 << 32])
def test_invalid_counter_words_are_not_clock_samples(value):
    with pytest.raises(ValueError, match="word"):
        read_counter(SimpleNamespace(CHIP="mt7925", rr=lambda _: value))


def test_unknown_chip_does_not_read_bus():
    with pytest.raises(ValueError, match="known"):
        read_counter(SimpleNamespace(CHIP="other"))


def test_zero_is_valid_raw_but_not_claimed_as_an_advancing_clock():
    assert read_counter(SimpleNamespace(CHIP="mt7921", rr=lambda _: 0))["value_raw"] == 0


@pytest.mark.parametrize("case", ["own", "ambient", "bad_fcs", "missing"])
def test_packet_brackets_never_serialize_ambient_frames(monkeypatch, case):
    from research import lpon_packet_clock_probe as p

    frame = bytes(24)
    decoded = {"pkt_type": 2, "frame": frame, "timestamp": 123}
    if case == "ambient":
        decoded["frame"] = b"x" + frame[1:]
    elif case == "bad_fcs":
        decoded["fcs_err"] = True
    elif case == "missing":
        decoded = None
    monkeypatch.setattr(p.m, "decoder_for", lambda _: lambda raw: decoded)

    def original(reader, expected):
        assert reader.rx_read() == b"private USB record"
        return {}

    monkeypatch.setattr(p, "original_capture", original)
    dev = SimpleNamespace(CHIP="mt7921", rr=lambda _: 456, rx_read=lambda: b"private USB record")
    out = p.capture(dev, {0: frame})["lpon_packet_clock_brackets"]
    if case == "own":
        assert out[0]["packet_clocks"] == [{"kind": "RXD", "sequence": 0, "timestamp_raw": 123}]
        assert "private" not in str(out)
    else:
        assert out == []


def test_status_brackets_retain_only_own_pid_and_sequence(monkeypatch):
    from research import lpon_packet_clock_probe as p

    monkeypatch.setattr(p.m, "decoder_for", lambda _: lambda raw: {"pkt_type": 0})
    statuses = [
        {"pid": 3, "sequence": 0, "timestamp_raw": 100},
        {"pid": 4, "sequence": 0, "timestamp_raw": 101},
        {"pid": 3, "sequence": 12, "timestamp_raw": 102},
    ]
    monkeypatch.setattr(p.c3, "tx_status", lambda *a, **k: statuses)

    def original(reader, expected):
        reader.rx_read()
        return {}

    monkeypatch.setattr(p, "original_capture", original)
    dev = SimpleNamespace(CHIP="mt7925", rr=lambda _: 456, rx_read=lambda: b"private")
    out = p.capture(dev, {0: bytes(24)})["lpon_packet_clock_brackets"]
    assert out[0]["packet_clocks"] == [{"kind": "TXS", "sequence": 0, "timestamp_raw": 100}]
