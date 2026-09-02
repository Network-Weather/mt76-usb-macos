# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Offline tests for the roam watcher's pure bookkeeping."""

from scripts import roam_watch as rw

BSSID = "02:11:22:33:44:55"


def beacon(ssid="home", ds_channel=None, **extra) -> dict:
    p = {"kind": "Beacon", "ssid": ssid, "addr3": BSSID, **extra}
    if ds_channel is not None:
        p["ds_channel"] = ds_channel
    return p


def rxd(band="5GHz", channel=36, rssi=-60) -> dict:
    return {"band": band, "channel": channel, "rssi": rssi}


def test_channel_comes_from_the_frame_not_the_sweep_target():
    found = {}
    # Received while the radio sat on channel 40, but the descriptor says 36 and the
    # beacon carries no DS Parameter Set: the descriptor wins.
    rw.note_bssid(found, rxd(channel=36), beacon(), "home")
    assert found[BSSID]["channel"] == 36
    assert found[BSSID]["channel_source"] == "rxd"


def test_ds_parameter_set_beats_descriptor_and_is_not_overwritten():
    found = {}
    rw.note_bssid(found, rxd(band="2.4GHz", channel=1), beacon(ds_channel=3), "home")
    assert (found[BSSID]["band"], found[BSSID]["channel"]) == ("2.4GHz", 3)
    assert found[BSSID]["channel_source"] == "ds"
    # A later beacon without the IE, heard from an adjacent channel, must not regress it.
    rw.note_bssid(found, rxd(band="2.4GHz", channel=6), beacon(), "home")
    assert found[BSSID]["channel"] == 3


def test_later_ds_parameter_set_corrects_an_earlier_descriptor_guess():
    found = {}
    rw.note_bssid(found, rxd(channel=40), beacon(), "home")
    rw.note_bssid(found, rxd(channel=40), beacon(ds_channel=36), "home")
    assert found[BSSID]["channel"] == 36


def test_keeps_strongest_rssi_and_flags():
    found = {}
    rw.note_bssid(found, rxd(rssi=-70), beacon(), "home")
    rw.note_bssid(
        found,
        rxd(rssi=-55),
        beacon(
            bss_transition=True,
            rrm_capabilities={"neighbor_report": True},
            mobility_domain={"id": "a1b2"},
            bss_load={"stations": 4, "channel_util_pct": 12},
        ),
        "home",
    )
    e = found[BSSID]
    assert e["rssi"] == -55
    assert e["k_neighbor_report"]
    assert e["v_bss_transition"]
    assert e["r_mobility_domain"] == "a1b2"
    assert e["load"] == {"stations": 4, "channel_util_pct": 12}


def test_ignores_other_ssids_non_beacons_and_frames_without_channel():
    found = {}
    rw.note_bssid(found, rxd(), beacon(ssid="other"), "home")
    rw.note_bssid(found, rxd(), {"kind": "AssocReq", "ssid": "home", "addr3": BSSID}, "home")
    rw.note_bssid(found, {"rssi": -50}, beacon(), "home")
    assert found == {}
