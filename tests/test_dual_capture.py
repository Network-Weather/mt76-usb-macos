# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""The two-radio capture's pure bookkeeping, offline. No adapter is required."""

import argparse

import pytest

from scripts import dual_capture as dual


def test_a_radio_argument_carries_its_address_channel_and_width():
    radio = dual.parse_radio("2:20=5GHz:132@80")
    assert radio.selector == "2:20"
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
        "2:20=5GHz:999",  # no such channel, and a 20 MHz channel is its own center
        "2:20=2.4GHz:15",  # one past the top of the band
        "2:20=6GHz:234",  # one past the top of the band
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

    by_port = dual.parse_radio("2:21=5GHz:132@80")
    assert by_port.usb_id is None

    # Neither is bound to an adapter until the inventory resolves it to one port.
    assert by_id.port is None
    assert by_port.port is None


def test_a_usb_id_selector_is_accepted_in_either_case_and_matched_in_one():
    # The inventory reports lowercase, so an uppercase selector that parses must also
    # match rather than being rejected later as an adapter that is not attached.
    assert dual.parse_radio("0E8D:7961=5GHz:132@80").usb_id == "0e8d:7961"
    assert dual.parse_radio("0E8D:7961=5GHz:132@80").selector == "0e8d:7961"


def test_a_radio_that_was_never_resolved_refuses_to_open_anything():
    radio = dual.parse_radio("0e8d:7961=5GHz:132@80")
    radio.run(dual.Timeline(None), duration=1.0, identify=False)
    assert "never resolved" in radio.error


@pytest.mark.parametrize("selector", ["alfa", "2", "0e8d:796", "2:", ":21", "0e8d-7961"])
def test_a_selector_that_is_neither_form_is_refused(selector):
    with pytest.raises(argparse.ArgumentTypeError):
        dual.parse_radio(f"{selector}=5GHz:132@80")


def test_a_width_above_the_chips_limit_is_a_radio_error_not_a_quiet_capture(monkeypatch):
    # An MT7921 tuned to 160 MHz returns no transfers and no error, so a run would report
    # zero frames and exit 0. The radio must refuse before the firmware download instead.
    class FakeDevice:
        CHIP = "mt7921"
        MAX_WIDTH_MHZ = 80

        def __enter__(self):
            raise AssertionError("the device must not be brought up at an unusable width")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(dual.m, "open_device_at", lambda port, **kwargs: FakeDevice())
    monkeypatch.setattr(
        dual.m, "load_firmware", lambda *a: pytest.fail("firmware must not be loaded")
    )

    radio = dual.parse_radio("0e8d:7961=6GHz:53@160")
    radio.resolve("2:20")
    radio.run(dual.Timeline(None), duration=1.0, identify=False)

    assert radio.error is not None
    assert "captures up to 80 MHz" in radio.error
    assert radio.chip == "mt7921"


def test_a_width_the_chip_supports_reaches_the_firmware_download(monkeypatch):
    class FakeDevice:
        CHIP = "mt7925"
        MAX_WIDTH_MHZ = 160

    reached = []
    monkeypatch.setattr(dual.m, "open_device_at", lambda port, **kwargs: FakeDevice())
    monkeypatch.setattr(dual.m, "firmware_dir", lambda: "firmware")

    def fake_load(chip, directory):
        reached.append(chip)
        raise RuntimeError("stop here, the rest needs USB")

    monkeypatch.setattr(dual.m, "load_firmware", fake_load)

    radio = dual.parse_radio("0846:9072=6GHz:53@160")
    radio.resolve("2:9")
    radio.run(dual.Timeline(None), duration=1.0, identify=False)

    assert reached == ["mt7925"]
    assert "stop here" in radio.error


def test_one_radios_failure_is_recorded_and_does_not_raise(monkeypatch):
    def explode(port, **kwargs):
        raise OSError("adapter went away")

    monkeypatch.setattr(dual.m, "open_device_at", explode)
    radio = dual.parse_radio("0e8d:7961=5GHz:132@80")
    radio.resolve("2:20")
    radio.run(dual.Timeline(None), duration=1.0, identify=False)

    assert radio.error == "OSError: adapter went away"
    assert radio.counts["frames"] == 0


def ready_radio(selector, ready_at, stopped_at):
    radio = dual.parse_radio(selector)
    radio.ready_at = ready_at
    radio.stopped_at = stopped_at
    return radio


def test_the_shared_window_is_when_every_radio_was_listening():
    # The MT7925 is ready about a second before the MT7921 on the reference pair, and
    # each stops one duration after its own start, so the windows are offset at both ends.
    radios = [
        ready_radio("0846:9072=6GHz:53@160", 1.83, 61.83),
        ready_radio("0e8d:7961=5GHz:132@80", 2.81, 62.81),
    ]
    window = dual.shared_window(radios)["shared_window"]

    assert window["from_s"] == 2.81
    assert window["to_s"] == 61.83
    assert window["seconds"] == 59.02
    assert window["startup_gap_s"] == 0.98


def test_a_radio_that_never_started_leaves_no_shared_window_and_is_counted():
    radios = [
        ready_radio("0846:9072=6GHz:53@160", 1.83, 61.83),
        dual.parse_radio("0e8d:7961=5GHz:132@80"),  # refused its width, never tuned
    ]
    result = dual.shared_window(radios)

    assert result["shared_window"] is None
    assert result["radios_that_never_started"] == 1


def test_windows_that_do_not_overlap_report_no_shared_seconds_not_a_negative():
    radios = [
        ready_radio("0846:9072=6GHz:53@160", 1.0, 3.0),
        ready_radio("0e8d:7961=5GHz:132@80", 5.0, 7.0),
    ]
    window = dual.shared_window(radios)["shared_window"]

    assert window["seconds"] == 0.0
    assert window["startup_gap_s"] == 4.0
