# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
from types import SimpleNamespace

import pytest

import mt7921u as m
from research import phy_tx_probe as p
from research.rx_stat_query import request


@pytest.mark.parametrize(("name", "code"), p.RATES + p.STREAM_RATES)
def test_inline_connac2_vs_table_connac3(name, code):
    frame = p.c3.controlled_frame(7)
    c2 = SimpleNamespace(CHIP=m.CHIP_MT7921)
    c2._build_txwi = lambda frame, seq, pid: bytes(32)
    data = p.descriptor(c2, frame, 7, code)
    assert struct.unpack_from("<I", data, 24)[0] == (code << 16) | m.MT_TXD6_FIXED_BW
    c3 = SimpleNamespace(CHIP=m.CHIP_MT7925)
    data = p.descriptor(c3, frame, 7, code)
    assert struct.unpack_from("<I", data, 24)[0] == 0x12001C
    changed = p.descriptor(c3, frame, 7, code, fixed_bw=True)
    assert struct.unpack_from("<I", changed, 24)[0] == 0x212001C
    assert data[:24] == changed[:24]
    assert data[28:] == changed[28:]


def test_rate_allowlist():
    dev = SimpleNamespace(CHIP=m.CHIP_MT7925)
    with pytest.raises(ValueError, match="outside bounded experiment"):
        p.program_rate(dev, 0xFFFF)
    with pytest.raises(ValueError, match="outside bounded experiment"):
        p.descriptor(dev, b"", 0, 0xFFFF)


def test_stream_suite_encodes_nss_minus_one_and_stays_bounded():
    assert len(p.STREAM_RATES) == 6
    assert dict(p.STREAM_RATES)["ht8_2ss"] == 0x488
    assert dict(p.STREAM_RATES)["vht0_2ss"] == 0x500
    assert dict(p.STREAM_RATES)["he0_2ss"] == 0x600
    assert p.STREAM_RATES[0][1] == p.STREAM_RATES[-1][1] == 0x4B


@pytest.mark.parametrize("category", [0, 3, 4, 5, 6])
def test_receive_query_shape(category):
    assert request(category) == bytes((category, 0, 0, 0))


@pytest.mark.parametrize(("category", "selector"), [(1, 0), (2, 0), (7, 0), (4, 2), (5, 1), (6, 1)])
def test_receive_query_rejects_nonqueries(category, selector):
    with pytest.raises(ValueError, match=r"query|categories"):
        request(category, selector)


def test_capture_only_exact_own_frames_and_valid_fcs(monkeypatch):
    stop = p.threading.Event()
    frame = p.c3.controlled_frame(0)
    samples = iter(
        [
            {"pkt_type": 2, "frame": frame, "phy": {"mode_name": "HT", "mcs": 0}},
            {"pkt_type": 2, "frame": frame, "phy": {"mode_name": "HT", "mcs": 0}},
            {"pkt_type": 2, "frame": frame, "fcs_err": True},
            {"pkt_type": 2, "frame": frame + b"different"},
        ]
    )

    def decode(raw):
        try:
            return next(samples)
        except StopIteration:
            stop.set()
            return None

    monkeypatch.setattr(m, "decoder_for", lambda dev: decode)
    dev = SimpleNamespace(CHIP=m.CHIP_MT7921, rx_read=lambda **kwargs: b"")
    out = p.capture(dev, {0: frame}, 1, p.threading.Event(), stop)
    assert out["phases"][0]["unique_exact_frames"] == 1
    assert out["phases"][0]["phy"][0]["count"] == 2
    assert out["counts"]["controlled_fcs_errors"] == 1
