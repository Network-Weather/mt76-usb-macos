# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""The two-radio capture's pure bookkeeping, offline. No adapter is required."""

import argparse

import pytest

from scripts import dual_capture as dual


def test_a_radio_argument_carries_its_address_channel_and_width():
    radio = dual.parse_radio("2:20=5GHz:132@80")
    assert radio.address == "2:20"
    assert radio.band == "5GHz"
    assert radio.channel == 132
    assert radio.width == 80
    assert radio.label == "5GHz:132@80"


def test_a_radio_argument_without_a_width_captures_twenty_megahertz():
    assert dual.parse_radio("2:9=6GHz:53").width == 20


@pytest.mark.parametrize(
    "text",
    [
        "5GHz:132",  # no address
        "2:20=",  # no target
        "2:20=7GHz:1",  # no such band
        "2:20=5GHz:abc",  # no such channel
        "2:20=5GHz:132@33",  # not a width the sniffer takes
        "2:20=2.4GHz:6@40",  # ambiguous: a 2.4 GHz 40 MHz channel may extend either way
        "2:20=6GHz:229@80",  # no 80 MHz block reaches channel 229
    ],
)
def test_an_unusable_radio_argument_is_refused(text):
    with pytest.raises(argparse.ArgumentTypeError):
        dual.parse_radio(text)


def test_without_a_client_every_frame_matches():
    timeline = dual.Timeline(None)
    assert timeline.matches_client({"02:00:00:00:00:aa"})
    assert timeline.matches_client(set())


def test_with_a_client_only_that_station_matches():
    timeline = dual.Timeline("02:00:00:00:00:01")
    assert timeline.matches_client({"02:00:00:00:00:01"})
    assert not timeline.matches_client({"02:00:00:00:00:aa"})


def test_a_link_address_learned_on_one_radio_is_matched_on_the_other():
    timeline = dual.Timeline("02:00:00:00:00:01")
    # The client's reassociation request, seen by the 5 GHz radio, names its links.
    learned = timeline.learn("5GHz:132@80", {"02:00:00:00:00:01", "02:00:00:00:00:11"})
    assert learned == ["02:00:00:00:00:11"]

    # The 6 GHz radio now recognizes the link address it never saw introduced.
    assert timeline.matches_client({"02:00:00:00:00:11"})
    assert timeline.learned[0]["radio"] == "5GHz:132@80"
    assert timeline.learned[0]["address"] == "02:00:00:00:00:11"


def test_addresses_from_a_station_that_is_not_the_client_are_never_folded_in():
    timeline = dual.Timeline("02:00:00:00:00:01")
    # An access point's own Multi-Link element, from a frame the AP transmitted.
    assert timeline.learn("5GHz:132@80", {"02:00:00:00:00:aa", "02:00:00:00:00:ab"}) == []
    assert not timeline.matches_client({"02:00:00:00:00:ab"})


def test_learning_is_inert_when_no_client_was_given():
    timeline = dual.Timeline(None)
    assert timeline.learn("5GHz:132@80", {"02:00:00:00:00:11"}) == []
    assert timeline.client_addresses == set()


def test_every_radio_stamps_against_one_clock():
    timeline = dual.Timeline(None)
    first = timeline.stamp()
    second = timeline.stamp()
    assert 0 <= first <= second


def test_events_from_both_radios_share_the_timeline():
    timeline = dual.Timeline(None)
    timeline.add({"at": 2.0, "radio": "6GHz:53@160", "event": "auth"})
    timeline.add({"at": 1.0, "radio": "5GHz:132@80", "event": "bss_transition_request"})

    ordered = sorted(timeline.events, key=lambda event: event["at"])
    assert [event["radio"] for event in ordered] == ["5GHz:132@80", "6GHz:53@160"]


def test_a_usb_id_selector_names_a_model_and_a_port_address_names_a_port():
    by_id = dual.parse_radio("0e8d:7961=5GHz:132@80")
    assert by_id.usb_id == "0e8d:7961"
    assert by_id.address is None

    by_port = dual.parse_radio("2:21=5GHz:132@80")
    assert by_port.usb_id is None
    assert by_port.address == "2:21"


@pytest.mark.parametrize("selector", ["alfa", "2", "0e8d:796", "2:", ":21", "0e8d-7961"])
def test_a_selector_that_is_neither_form_is_refused(selector):
    with pytest.raises(argparse.ArgumentTypeError):
        dual.parse_radio(f"{selector}=5GHz:132@80")
