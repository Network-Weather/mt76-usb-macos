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


def test_he_dcm_and_ru_rates():
    # HE MCS 0 with DCM in 20 MHz: 4.3 Mbps
    assert rxd.phy_rate_mbps(rxd.MT_PHY_TYPE_HE_SU, 0, 1, 20, 0, dcm=True) == 4.3
    # HE-ER-SU MCS 0 on 106-tone RU: 3.8 Mbps
    assert rxd.phy_rate_mbps(rxd.MT_PHY_TYPE_HE_EXT_SU, 0, 1, 40, 0, ru_tones=106) == 3.8
    # HE-ER-SU MCS 0 on full 40 MHz (484-tone): 17.2 Mbps
    assert rxd.phy_rate_mbps(rxd.MT_PHY_TYPE_HE_EXT_SU, 0, 1, 40, 0, ru_tones=484) == 17.2
    # HE-MU MCS 5 on 52-tone RU: 14.1 Mbps
    assert rxd.phy_rate_mbps(rxd.MT_PHY_TYPE_HE_MU, 5, 1, 20, 0, ru_tones=52) == 14.1


def test_decode_rxv_phy_telemetry():
    # STBC halves NSS but preserves NSTS
    rxv_stbc = (8 << 24) | (1 << 22) | (1 << 15) | (2 << 12) | (1 << 7) | 7
    dec = rxd.decode_rxv(rxv_stbc, 0)
    assert dec["stbc"] is True
    assert dec["nss"] == 1
    assert dec["nsts"] == 2
    assert dec["rate_mbps"] == 340.3

    # HE-MU 52-tone RU allocation (ru=40)
    rxv0_mu = (11 << 24) | (8 << 28) | (0 << 15) | (0 << 12) | (0 << 7) | 5
    rxv1_mu = 2
    dec_mu = rxd.decode_rxv(rxv0_mu, rxv1_mu)
    assert dec_mu["ru_alloc"] == 40
    assert dec_mu["ru_tones"] == 52
    assert dec_mu["ru_offset"] == 3

    # HE-ER-SU 40 MHz with 106-tone flag (bit 5)
    rxv_er106 = (9 << 24) | (1 << 5) | (0 << 15) | (1 << 12) | (0 << 7) | 0
    dec_er106 = rxd.decode_rxv(rxv_er106, 0)
    assert dec_er106["ru_tones"] == 106
    assert dec_er106["rate_mbps"] == 3.8

    # HE-ER-SU 40 MHz without 106-tone flag -> full 40 MHz
    rxv_er40 = (9 << 24) | (0 << 15) | (1 << 12) | (0 << 7) | 0
    dec_er40 = rxd.decode_rxv(rxv_er40, 0)
    assert dec_er40["bw_mhz"] == 40
    assert dec_er40["ru_tones"] == 484
    assert dec_er40["rate_mbps"] == 17.2


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
