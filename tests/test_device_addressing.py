# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Picking one adapter out of several, offline.

Two adapters of the same model share a USB id, so only the port they are attached to
tells them apart. These tests drive the selection with fake pyusb devices; no adapter is
required.
"""

import pytest

import mt7921u as m

ALFA = (0x0E8D, 0x7961)
A9000 = (0x0846, 0x9072)


class FakeUsbDevice:
    """The four attributes device selection reads off a pyusb device."""

    def __init__(self, vid_pid, bus, address):
        self.idVendor, self.idProduct = vid_pid
        self.bus = bus
        self.address = address


@pytest.fixture
def attached(monkeypatch):
    """Replace the USB bus with a list of fake devices, and clear the env selectors."""
    monkeypatch.delenv("MT76_USB_ID", raising=False)
    monkeypatch.delenv("MT76_USB_ADDR", raising=False)

    def install(devices):
        monkeypatch.setattr(m.usb.core, "find", lambda find_all: list(devices))

    return install


def test_an_address_names_the_port_not_the_device(attached):
    device = FakeUsbDevice(ALFA, bus=2, address=20)
    assert m.device_address(device) == "2:20"


def test_two_adapters_of_the_same_model_are_told_apart_by_address(attached):
    first = FakeUsbDevice(ALFA, bus=2, address=20)
    second = FakeUsbDevice(ALFA, bus=2, address=21)
    attached([first, second])

    # The USB id matches both, so it cannot choose between them.
    assert len(m.find_supported_devices(usb_id="0e8d:7961")) == 2
    assert m.find_supported_devices(address="2:21") == [second]
    assert m.find_supported_devices(usb_id="0e8d:7961", address="2:20") == [first]


def test_the_environment_supplies_either_selector(attached, monkeypatch):
    alfa = FakeUsbDevice(ALFA, bus=2, address=20)
    a9000 = FakeUsbDevice(A9000, bus=2, address=9)
    attached([alfa, a9000])

    monkeypatch.setenv("MT76_USB_ID", "0846:9072")
    assert m.find_supported_devices() == [a9000]
    monkeypatch.delenv("MT76_USB_ID")
    monkeypatch.setenv("MT76_USB_ADDR", "2:20")
    assert m.find_supported_devices() == [alfa]


def test_an_ambiguous_open_is_still_refused_and_now_says_where_each_adapter_is(attached):
    attached([FakeUsbDevice(ALFA, bus=2, address=20), FakeUsbDevice(A9000, bus=2, address=9)])

    with pytest.raises(m.UnsupportedDevice) as raised:
        m.open_device()
    message = str(raised.value)
    assert "2 supported devices attached" in message
    assert "MT76_USB_ID" in message
    assert "MT76_USB_ADDR" in message
    assert "2:9" in message
    assert "2:20" in message


def test_an_address_that_matches_nothing_says_what_it_looked_for(attached):
    attached([FakeUsbDevice(ALFA, bus=2, address=20)])

    with pytest.raises(m.UnsupportedDevice) as raised:
        m.open_device(address="9:99")
    assert "9:99" in str(raised.value)


def test_the_inventory_reports_where_each_adapter_is_and_what_it_is(attached):
    attached([FakeUsbDevice(A9000, bus=2, address=9), FakeUsbDevice(ALFA, bus=2, address=20)])

    assert m.describe_supported_devices() == [
        {"address": "2:9", "usb_id": "0846:9072", "chip": "mt7925"},
        {"address": "2:20", "usb_id": "0e8d:7961", "chip": "mt7921"},
    ]


def test_an_unsupported_adapter_is_never_listed_or_selectable(attached):
    attached([FakeUsbDevice((0x1234, 0x5678), bus=2, address=5)])

    assert m.describe_supported_devices() == []
    assert m.find_supported_devices(address="2:5") == []


def test_a_selected_device_keeps_its_address_so_it_reopens_the_same_port(attached):
    attached([FakeUsbDevice(A9000, bus=2, address=9), FakeUsbDevice(ALFA, bus=2, address=20)])

    device = m.open_device(address="2:20")
    assert device.address == "2:20"
    assert device.usb_id == "0e8d:7961"
    assert device.CHIP == "mt7921"
