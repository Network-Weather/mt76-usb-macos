# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
from types import SimpleNamespace

import pytest

from research import noise_self_tx_probe as p


@pytest.mark.parametrize("padding", [0, 128])
def test_bounded_packet_preserves_zero_duration_and_no_ack(padding):
    dev = SimpleNamespace(CHIP=p.m.CHIP_MT7925)
    payload, wire = p.packet(dev, 7, b"12345678", padding)
    assert len(payload) == 65 + padding
    assert payload[2:4] == bytes(2)
    words = struct.unpack_from("<16I", wire, 4)
    assert words[0] & 65535 == 64 + len(payload)
    assert words[2] & (1 << 12)
    assert words[3] & 1
    assert words[5] & 255 == 3
    assert words[6] & (1 << 25)
    assert words[6] >> 22 & 7 == 0
    assert wire[68 : 68 + len(payload)] == payload


@pytest.mark.parametrize("padding", [-1, 1, 256, True])
def test_no_other_payload_size(padding):
    with pytest.raises(ValueError, match="fixed MT7925"):
        p.packet(SimpleNamespace(CHIP=p.m.CHIP_MT7925), 0, b"12345678", padding)


def test_no_old_transmitter_or_outside_sequence_bound():
    with pytest.raises(ValueError, match="fixed MT7925"):
        p.packet(SimpleNamespace(CHIP=p.m.CHIP_MT7921), 0, b"12345678", 0)
    with pytest.raises(ValueError, match="bounded sequence"):
        p.packet(SimpleNamespace(CHIP=p.m.CHIP_MT7925), 20, b"12345678", 0)


def test_collection_refuses_unbounded_packet_list_before_device_access():
    with pytest.raises(ValueError, match="exactly20"):
        p.acquire(None, None, [], True)
    with pytest.raises(ValueError, match="explicit phase"):
        p.acquire(None, None, [None] * 20, 1)


@pytest.mark.parametrize("transmit", [False, True])
def test_timeout_never_exceeds_transmit_cap(monkeypatch, transmit):
    ticks = iter(i / 1000 for i in range(10000))
    monkeypatch.setattr(p, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(p.noise, "activate", lambda _dev: 1)
    monkeypatch.setattr(p.m, "decoder_for", lambda _dev: lambda _raw: None)

    class Device:
        ep_in_pkt_rx = 0x84
        ep_in_cmd_resp = 0x85
        ep_out_ac_be = 1
        sent = 0

        def bulk_in(self, *_args, **_kwargs):
            return b""

        def bulk_out(self, *_args, **_kwargs):
            self.sent += 1

    tx, rx = Device(), Device()
    packets = [(bytes([i]), b"synthetic") for i in range(20)]
    row = p.acquire(tx, rx, packets, transmit)
    assert tx.sent == (20 if transmit else 0)
    assert row["submitted"] == tx.sent
    assert row["attempted_transfers"] <= 3072
    assert "event" not in row
