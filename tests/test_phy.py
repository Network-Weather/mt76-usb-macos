# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Offline tests for rate, airtime, and aggregation calculations."""

import pytest

import rxd

SYNTHETIC_TRANSMITTER_A = "synthetic-transmitter-a"
SYNTHETIC_TRANSMITTER_B = "synthetic-transmitter-b"


@pytest.mark.parametrize(
    ("chfreq", "expected"),
    [
        (1, ("2.4GHz", 1)),
        (149, ("5GHz", 149)),
        (194, ("6GHz", 53)),
    ],
)
def test_descriptor_channel_encoding(chfreq, expected):
    assert rxd.status_freq(chfreq) == expected


def test_rcpi_to_rssi():
    assert rxd.to_rssi(120) == -50
    assert rxd.to_rssi(220) == 0


@pytest.mark.parametrize(
    ("mode", "mcs", "nss", "bw", "gi", "expected"),
    [
        (rxd.MT_PHY_TYPE_CCK, 0, 1, 20, 0, 1.0),
        (rxd.MT_PHY_TYPE_OFDM, 11, 1, 20, 0, 6.0),
        (rxd.MT_PHY_TYPE_HT, 7, 1, 20, 1, 72.2),
        (rxd.MT_PHY_TYPE_VHT, 9, 2, 80, 1, 866.7),
        (rxd.MT_PHY_TYPE_HE_SU, 11, 2, 80, 0, 1201.0),
    ],
)
def test_phy_rate_known_points(mode, mcs, nss, bw, gi, expected):
    assert rxd.phy_rate_mbps(mode, mcs, nss, bw, gi) == expected


def test_unknown_rate_returns_none():
    assert rxd.phy_rate_mbps(99, 0, 1, 20, 0) is None
    assert rxd.phy_rate_mbps(rxd.MT_PHY_TYPE_VHT, 12, 1, 20, 0) is None


def test_airtime_has_one_preamble_plus_payload():
    assert rxd.airtime_us(1500, rxd.MT_PHY_TYPE_OFDM, 6) == 2020.0
    assert rxd.airtime_us(1500, rxd.MT_PHY_TYPE_OFDM, None) is None


def test_aggregation_tracker_groups_contiguous_ampdu_frames():
    tracker = rxd.AggregationTracker()
    base = {
        "non_ampdu": False,
        "phy": {"mode": rxd.MT_PHY_TYPE_HE_SU, "rate_mbps": 100.0},
    }

    assert tracker.feed({**base, "timestamp": 1000}, 100, SYNTHETIC_TRANSMITTER_A) == []
    assert tracker.feed({**base, "timestamp": 1010}, 100, SYNTHETIC_TRANSMITTER_A) == []
    [aggregate] = tracker.flush()

    assert aggregate.is_ampdu
    assert aggregate.n == 2
    assert aggregate.bytes == 200
    assert aggregate.airtime_us() < sum(
        rxd.airtime_us(100, rxd.MT_PHY_TYPE_HE_SU, 100.0) for _ in range(2)
    )


def test_aggregation_tracker_splits_transmitters():
    tracker = rxd.AggregationTracker()
    data = {
        "non_ampdu": False,
        "timestamp": 1000,
        "phy": {"mode": rxd.MT_PHY_TYPE_HE_SU, "rate_mbps": 100.0},
    }

    assert tracker.feed(data, 100, SYNTHETIC_TRANSMITTER_A) == []
    [first] = tracker.feed({**data, "timestamp": 1001}, 100, SYNTHETIC_TRANSMITTER_B)

    assert first.n == 1
    assert tracker.flush()[0].n == 1
