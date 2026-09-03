# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Descriptor-driven device selection (usb.c mt76u_set_endpoints), offline.

Layouts below are the two adapters recorded in docs/TESTING.md plus synthetic
variants that must fail closed. No adapter is required.
"""

import pytest

import mt7921u as m

BULK = 0x02
INTR = 0x03


def intf(number, cls, eps):
    return m.InterfaceDesc(number, *cls, tuple(m.EndpointDesc(a, t) for a, t in eps))


WIFI = (0xFF, 0xFF, 0xFF)
BLUETOOTH = (0xE0, 0x01, 0x01)

# ALFA AWUS036AXML (0e8d:7961): Bluetooth on interfaces 0-2, Wi-Fi on interface 3.
ALFA_WIFI_EPS = [
    (0x84, BULK),
    (0x85, BULK),
    (0x08, BULK),
    (0x04, BULK),
    (0x05, BULK),
    (0x06, BULK),
    (0x07, BULK),
    (0x09, BULK),
]
ALFA = [
    intf(0, BLUETOOTH, [(0x81, INTR), (0x82, BULK), (0x02, BULK)]),
    intf(1, BLUETOOTH, [(0x83, 0x01), (0x03, 0x01)]),
    intf(2, BLUETOOTH, [(0x8A, BULK), (0x0A, BULK)]),
    intf(3, WIFI, ALFA_WIFI_EPS),
]

# Netgear A9000 (0846:9072) as read with pyusb on 2026-09-03: one interface, the same
# eight bulk endpoints in the same order, plus a trailing interrupt endpoint.
A9000 = [intf(0, WIFI, [*ALFA_WIFI_EPS, (0x86, INTR)])]


def test_alfa_layout_selects_interface_3_positionally():
    number, in_eps, out_eps = m.select_wifi_interface(ALFA)
    assert number == 3
    assert in_eps == (0x84, 0x85)
    assert out_eps == (0x08, 0x04, 0x05, 0x06, 0x07, 0x09)


def test_a9000_layout_selects_interface_0_and_ignores_interrupt_endpoint():
    number, in_eps, out_eps = m.select_wifi_interface(A9000)
    assert number == 0
    assert in_eps == (0x84, 0x85)
    assert out_eps == (0x08, 0x04, 0x05, 0x06, 0x07, 0x09)


def test_endpoint_roles_follow_descriptor_order_not_address():
    # mt76 assigns roles by position. Reordered addresses must map differently.
    eps = [(0x8B, BULK), (0x8C, BULK)] + [(0x01 + i, BULK) for i in range(6)]
    number, in_eps, out_eps = m.select_wifi_interface([intf(0, WIFI, eps)])
    layout = m.UsbLayout(0x0E8D, 0x7961, m.CHIP_MT7921, number, in_eps, out_eps)
    assert layout.ep_in_pkt_rx == 0x8B
    assert layout.ep_in_cmd_resp == 0x8C
    assert layout.ep_out_inband_cmd == 0x01
    assert layout.ep_out_ac_be == 0x02
    assert layout.usb_id == "0e8d:7961"


def test_extra_bulk_endpoints_beyond_the_required_count_are_ignored():
    eps = [*ALFA_WIFI_EPS, (0x8D, BULK), (0x0B, BULK)]
    _, in_eps, out_eps = m.select_wifi_interface([intf(0, WIFI, eps)])
    assert in_eps == (0x84, 0x85)
    assert out_eps == (0x08, 0x04, 0x05, 0x06, 0x07, 0x09)


def test_no_vendor_interface_fails_closed_with_the_interfaces_seen():
    with pytest.raises(m.UnsupportedDevice) as exc:
        m.select_wifi_interface(ALFA[:3])
    assert "intf 0 class e0/01/01" in str(exc.value)
    assert "intf 2 class e0/01/01 bulk in/out 1/1" in str(exc.value)


def test_too_few_bulk_endpoints_fails_closed():
    short = [intf(0, WIFI, ALFA_WIFI_EPS[:-1])]  # 2 IN, 5 OUT
    with pytest.raises(m.UnsupportedDevice) as exc:
        m.select_wifi_interface(short)
    assert "bulk in/out 2/5" in str(exc.value)


def test_two_qualifying_interfaces_is_ambiguous():
    two = [intf(0, WIFI, ALFA_WIFI_EPS), intf(1, WIFI, ALFA_WIFI_EPS)]
    with pytest.raises(m.UnsupportedDevice) as exc:
        m.select_wifi_interface(two)
    assert "ambiguous" in str(exc.value)
    assert "interfaces 0, 1" in str(exc.value)


def test_supported_device_table_covers_both_chips():
    assert m.SUPPORTED_DEVICES[(0x0E8D, 0x7961)] == m.CHIP_MT7921
    assert m.SUPPORTED_DEVICES[(0x0846, 0x9072)] == m.CHIP_MT7925
    assert m.SUPPORTED_DEVICES[(0x0846, 0x9050)] == m.CHIP_MT7925
    assert m.SUPPORTED_DEVICES[(0x0E8D, 0x7925)] == m.CHIP_MT7925
    assert (0x0E8D, 0x6639) not in m.SUPPORTED_DEVICES  # MT7927: no blobs, no evidence


def test_parse_usb_id():
    assert m.parse_usb_id("0846:9072") == (0x0846, 0x9072)
    assert m.parse_usb_id("0E8D:7961") == (0x0E8D, 0x7961)
    with pytest.raises(ValueError, match="usb id must look like"):
        m.parse_usb_id("nope")


def test_unopened_device_object_uses_reference_endpoints():
    dev = m.Mt7921uDevice()
    assert dev.layout is None
    assert dev.ep_in_pkt_rx == m.EP_IN_PKT_RX
    assert dev.ep_in_cmd_resp == m.EP_IN_CMD_RESP
    assert dev.ep_out_inband_cmd == m.EP_OUT_INBAND_CMD
    assert dev.ep_out_ac_be == m.EP_OUT_AC_BE


def test_firmware_paths_and_pins_per_chip(tmp_path, monkeypatch):
    monkeypatch.delenv("MT76_FW_DIR", raising=False)
    monkeypatch.delenv("MT7921_FW_DIR", raising=False)
    patch, ram = m.firmware_paths(m.CHIP_MT7925, tmp_path)
    assert patch == tmp_path / "mt7925" / "WIFI_MT7925_PATCH_MCU_1_1_hdr.bin"
    assert ram == tmp_path / "mt7925" / "WIFI_RAM_CODE_MT7925_1_1.bin"
    patch, ram = m.firmware_paths(m.CHIP_MT7921, tmp_path)
    assert patch.name == "WIFI_MT7961_patch_mcu_1_2_hdr.bin"
    # Environment precedence: MT76_FW_DIR, then the older MT7921_FW_DIR, then the repo.
    assert m.firmware_dir() == m.REPO_ROOT / "firmware"
    monkeypatch.setenv("MT7921_FW_DIR", "/old")
    assert m.firmware_dir() == m.Path("/old")
    monkeypatch.setenv("MT76_FW_DIR", "/new")
    assert m.firmware_dir() == m.Path("/new")
    # Every pin is a 64-hex-digit SHA-256.
    for entry in m.FIRMWARE_FILES.values():
        for name, sha in entry:
            assert len(sha) == 64
            assert int(sha, 16) >= 0
            assert not name.startswith("/")


def test_load_firmware_verifies_pins(tmp_path):
    patch, ram = m.firmware_paths(m.CHIP_MT7921, tmp_path)
    with pytest.raises(FileNotFoundError):
        m.load_firmware(m.CHIP_MT7921, tmp_path)
    patch.write_bytes(b"not the pinned blob")
    ram.write_bytes(b"nor this")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        m.load_firmware(m.CHIP_MT7921, tmp_path)
    assert m.load_firmware(m.CHIP_MT7921, tmp_path, verify=False) == (
        b"not the pinned blob",
        b"nor this",
    )
