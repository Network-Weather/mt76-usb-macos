# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
from types import SimpleNamespace

import pytest

import mt7921u as m
from research import csi_control_probe as p


@pytest.mark.parametrize("start", [False, True])
def test_source_defined_stop_start_requests(start):
    assert p.request(m.CHIP_MT7925, start) == struct.pack("<4xHH", int(start), 4)
    assert p.request(m.CHIP_MT7921, start) == bytes([0, int(start)]) + bytes(46)


@pytest.mark.parametrize("start", [0, 1, 2, None, "start"])
def test_no_arbitrary_control_modes(start):
    with pytest.raises(ValueError, match="boolean stop/start"):
        p.request(m.CHIP_MT7925, start)


def event(chip, eid, body, seq=0):
    header, offset = (44, 36) if chip == m.CHIP_MT7925 else (36, 28)
    raw = bytearray(header + len(body))
    struct.pack_into("<I", raw, 0, len(raw) | (m.PKT_TYPE_RX_EVENT << 27))
    raw[offset : offset + 2] = bytes([eid, seq])
    raw[header:] = body
    return raw


@pytest.mark.parametrize("chip", [m.CHIP_MT7921, m.CHIP_MT7925])
def test_unsolicited_csi_shape_never_emits_data(chip):
    eid = 0x4A if chip == m.CHIP_MT7925 else 0x3C
    data = b"private_data_1234"
    body = struct.pack("<4xHH", 0, 4 + len(data)) + data
    out = p.event_shape(event(chip, eid, body), chip, 9)
    assert out["candidate_csi_event"]
    assert "private" not in str(out)
    if chip == m.CHIP_MT7925:
        assert out["valid_outer_tlv"]


def test_filters_normal_frames_stale_sequences_and_truncation():
    raw = event(m.CHIP_MT7925, 0x4A, bytes(8), 2)
    assert p.event_shape(raw, m.CHIP_MT7925, 3) is None
    raw[37] = 0
    assert p.event_shape(raw[:-1], m.CHIP_MT7925, 3) is None
    word = struct.unpack_from("<I", raw)[0]
    word |= m.PKT_FLAG_NORMAL_MCU << m.RXD0_PKT_FLAG_SHIFT
    struct.pack_into("<I", raw, 0, word)
    assert p.event_shape(raw, m.CHIP_MT7925, 3) is None


def test_matched_result_status():
    raw = event(m.CHIP_MT7925, 1, struct.pack("<II", 0x4A, 0xC00000BB), 7)
    assert p.event_shape(raw, m.CHIP_MT7925, 7)["command_result_status"] == 0xC00000BB
    assert p.event_shape(raw, m.CHIP_MT7925, 8) is None


def test_second_source_defined_band_only_changes_band_byte():
    for chip in (m.CHIP_MT7921, m.CHIP_MT7925):
        assert p.request(chip, True, 1) == b"\x01" + p.request(chip, True)[1:]
        with pytest.raises(ValueError, match="band must"):
            p.request(chip, True, 2)


def test_legacy_command_not_found_is_not_csi():
    raw = event(m.CHIP_MT7921, 0xFD, b"", 4)
    out = p.event_shape(raw, m.CHIP_MT7921, 4)
    assert out["command_not_found_event"]
    assert "candidate_csi_event" not in out


@pytest.mark.parametrize("chains", [1, 2])
def test_bounded_chain_layout(chains):
    assert p.chain_request(1, chains) == struct.pack("<B3xHHB3x", 1, 3, 8, chains)


@pytest.mark.parametrize("chains", [0, 3, 16, True])
def test_reject_unbounded_or_ambiguous_chain_count(chains):
    with pytest.raises(ValueError, match="one or two"):
        p.chain_request(0, chains)


def test_fixed_configuration_snapshot_never_reads_sample_or_mac_buffers():
    addresses = []
    data = bytes(range(28))

    def read(address):
        addresses.append(address)
        return struct.unpack_from("<I", data, address - 0x02239760)[0]

    rows = p.control_snapshot(SimpleNamespace(CHIP=m.CHIP_MT7925, rr=read))
    assert addresses == list(range(0x02239760, 0x0223977C, 4))
    assert rows[0]["frame_selection_raw"] == [6, 7, 8, 9]
    assert rows[1]["address"] == "0x223976e"
    assert rows[1]["mode_raw"] == 14
    assert rows[1]["auxiliary_raw"] == [24, 25, 26, 27]
    with pytest.raises(ValueError, match="MT7925 only"):
        p.control_snapshot(SimpleNamespace(CHIP=m.CHIP_MT7921))


def test_hardware_snapshot_reads_only_rom_derived_band_registers():
    addresses = []

    def read(address):
        addresses.append(address)
        return 0x20000001 if address == 0x820E5060 else 1

    rows = p.hardware_snapshot(SimpleNamespace(CHIP=m.CHIP_MT7925, rr=read))
    assert addresses == [0x820E5060, 0x820F5060]
    assert [row["enable_bit29"] for row in rows] == [True, False]
    assert rows[0]["value"] == "0x20000001"
    with pytest.raises(ValueError, match="MT7925 only"):
        p.hardware_snapshot(SimpleNamespace(CHIP=m.CHIP_MT7921))


def test_candidate_beacon_selector_has_exact_packed_vendor_layout():
    for band in (0, 1):
        data = p.beacon_selector_request(band)
        assert len(data) == 15
        assert struct.unpack("<B3xHHBI2x", data) == (band, 2, 11, 0, 0x20)
    with pytest.raises(ValueError, match="band must"):
        p.beacon_selector_request(2)


def test_receive_width_control_preserves_primary36_geometry():
    assert [p.receive_center(w) for w in (20, 80, 160)] == [36, 42, 50]
    for invalid in (True, 40, 320, "80"):
        with pytest.raises(ValueError, match="receive widths"):
            p.receive_center(invalid)


def test_only_named_bounded_frame_selectors():
    for selector in (0x25, 0x2D):
        assert struct.unpack("<B3xHHBI2x", p.frame_selector_request(0, selector)) == (
            0,
            2,
            11,
            0,
            selector,
        )
    assert struct.unpack("<B3xHHBI2x", p.frame_selector_request(0, 0x02)) == (0, 2, 11, 0, 0x02)
    assert struct.unpack("<B3xHHBI2x", p.frame_selector_request(0, 0x22)) == (0, 2, 11, 0, 0x22)
    assert p.frame_selector_request(1, 0x20) == p.beacon_selector_request(1)
    for invalid in (True, 0, 0x21, 0x3F, 0xFF):
        with pytest.raises(ValueError, match="selector candidates"):
            p.frame_selector_request(0, invalid)


def test_second_passive_primary_is_bounded():
    assert p.receive_center(20, 149) == 149
    assert p.receive_center(80, 149) == 155
    with pytest.raises(ValueError, match="primary149"):
        p.receive_center(160, 149)
    for invalid in (True, 0, 37, 165, "36"):
        with pytest.raises(ValueError, match="primary36/149"):
            p.receive_center(20, invalid)


def test_normal_frame_shape_contains_only_type_and_phy():
    decoded = {
        "frame": b"\x88\x00PRIVATE_PAYLOAD",
        "fcs_err": False,
        "phy": {"mode": 8, "bw_mhz": 80, "nss": 2},
    }
    assert p.frame_shape(decoded) == {
        "fc_type_subtype": 0x88,
        "phy_mode_raw": 8,
        "bw_mhz": 80,
        "nss": 2,
    }
    assert p.frame_shape({**decoded, "fcs_err": True}) is None
    assert p.frame_shape({"frame": b"x"}) is None
    assert p.frame_shape(None) is None
