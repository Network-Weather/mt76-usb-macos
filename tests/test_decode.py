# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Network Weather, Inc.
"""Synthetic decode proofs for 802.11k/v/r, PMF, and mesh/backhaul parsing.

These exercise pure frame-decode logic in rxd.py against hardcoded frame
bytes. No hardware, no firmware, and no USB dependency: rxd imports cleanly on
its own, so this suite runs anywhere pytest does.
"""
import struct

import rxd

AP = bytes.fromhex("001122334455")
STA = bytes.fromhex("66778899aabb")
TARGET = bytes.fromhex("aabbccddeeff")


def ie(eid: int, value: bytes) -> bytes:
    return bytes((eid, len(value))) + value


def mgmt(subtype: int, body: bytes, *, protected: bool = False) -> bytes:
    fc = subtype << 4
    if protected:
        fc |= 1 << 14
    return struct.pack("<HH", fc, 0) + STA + AP + AP + b"\0\0" + body


def rsn(*, capabilities: int, akm_types: tuple[int, ...]) -> bytes:
    suite = b"\x00\x0f\xac"
    value = (
        struct.pack("<H", 1)
        + suite
        + b"\x04"
        + struct.pack("<H", 1)
        + suite
        + b"\x04"
        + struct.pack("<H", len(akm_types))
        + b"".join(suite + bytes((kind,)) for kind in akm_types)
        + struct.pack("<H", capabilities)
    )
    return ie(rxd.EID_RSN, value)


def neighbor_report() -> bytes:
    value = (
        TARGET
        + struct.pack("<I", 0x11223344)
        + bytes((128, 149, 9))
        + bytes((3, 1, 255))
        + bytes((6, 3, 1, 155, 0))
    )
    return ie(rxd.EID_NEIGHBOR_REPORT, value)


def test_rsn_distinguishes_pmf_policy_and_ft_akm():
    optional = rxd.parse_ies(rsn(capabilities=0x0080, akm_types=(2, 9)))
    required = rxd.parse_ies(rsn(capabilities=0x00C0, akm_types=(8,)))

    assert optional["rsn"]["pmf"] == "optional"
    assert optional["rsn"]["ft_akm"]
    assert "FT-SAE" in optional["rsn"]["akm_suites"]
    assert required["rsn"]["pmf"] == "required"
    assert not required["rsn"]["ft_akm"]

    disabled = rxd.parse_ies(rsn(capabilities=0, akm_types=(2,)))
    assert disabled["rsn"]["pmf"] == "disabled"


def test_rrm_and_btm_capabilities_from_advertisements():
    extended = b"\0\0\x08"
    parsed = rxd.parse_ies(
        ie(rxd.EID_RRM_ENABLED_CAPABILITIES, b"\x73\x02\0\0\0")
        + ie(rxd.EID_EXT_CAPABILITY, extended)
    )

    assert parsed["rrm_capabilities"]["neighbor_report"]
    assert parsed["rrm_capabilities"]["beacon_active"]
    assert parsed["bss_transition"]


def test_btm_request_decodes_policy_and_candidates():
    body = bytes((10, 7, 3, 0x27)) + struct.pack("<H", 25) + b"\x05"
    parsed = rxd.parse_80211(mgmt(13, body + neighbor_report()))
    action = parsed["action"]

    assert action["name"] == "btm-request"
    assert action["preferred_candidates"]
    assert action["disassociation_imminent"]
    assert action["link_removal_imminent"]
    assert action["neighbor_reports"][0]["channel"] == 149
    assert action["neighbor_reports"][0]["preference"] == 255


def test_btm_response_decodes_accepted_target():
    body = bytes((10, 8, 3, 0, 0)) + TARGET
    parsed = rxd.parse_80211(mgmt(13, body))

    assert parsed["action"]["status_name"] == "accept"
    assert parsed["action"]["target_bssid"] == rxd.mac(TARGET)


def test_neighbor_report_response_and_link_measurement():
    response = rxd.parse_80211(mgmt(13, bytes((5, 5, 9)) + neighbor_report()))
    link = rxd.parse_80211(
        mgmt(13, bytes((5, 3, 4, 35, 2, 0xF6, 12, 1, 2, 140, 45)))
    )

    assert response["action"]["name"] == "neighbor-report-response"
    assert response["action"]["neighbor_reports"][0]["bssid"] == rxd.mac(TARGET)
    assert link["action"]["tx_power_dbm"] == -10
    assert link["action"]["link_margin_db"] == 12
    assert link["action"]["rcpi"] == 140


def test_ft_auth_reassoc_and_action_paths():
    mdie = ie(rxd.EID_MOBILITY_DOMAIN, b"\x34\x12\x01")
    ftie = ie(rxd.EID_FAST_BSS_TRANSITION, b"\0\0")
    auth = rxd.parse_80211(mgmt(11, struct.pack("<HHH", 2, 1, 0) + mdie))
    reassoc = rxd.parse_80211(mgmt(2, struct.pack("<HH", 0, 10) + AP + mdie + ftie))
    action = rxd.parse_80211(mgmt(13, bytes((6, 1)) + STA + TARGET + mdie + ftie))

    assert rxd.management_event(auth)[0] == "ft_auth"
    assert rxd.management_event(reassoc)[0] == "ft_reassoc_req"
    assert action["action"]["name"] == "ft-request"
    assert action["action"]["mobility_domain"]["id"] == "1234"


def test_protected_action_body_is_never_guessed():
    parsed = rxd.parse_80211(mgmt(13, bytes((10, 7, 99, 0xFF)), protected=True))

    assert parsed["action"] == {"protected": True}
    assert rxd.management_event(parsed) == ("protected_action", {"protected": True})


def test_multi_ap_and_standard_mesh_are_positive_evidence():
    multi_ap_value = (
        rxd.WFA_OUI
        + bytes((rxd.MULTI_AP_OUI_TYPE, rxd.MULTI_AP_EXTENSION, 1, 0xE0))
        + bytes((rxd.MULTI_AP_PROFILE, 1, 2))
    )
    mesh_config = bytes((1, 1, 0, 1, 0, 0x05, 0x09))
    parsed = rxd.parse_ies(
        ie(rxd.EID_VENDOR_SPECIFIC, multi_ap_value)
        + ie(rxd.EID_MESH_ID, b"example-mesh")
        + ie(rxd.EID_MESH_CONFIG, mesh_config)
    )

    assert parsed["multi_ap"]["backhaul_sta"]
    assert parsed["multi_ap"]["backhaul_bss"]
    assert parsed["multi_ap"]["fronthaul_bss"]
    assert parsed["multi_ap"]["profiles"] == [2]
    assert parsed["mesh"]["id"] == "example-mesh"
    assert parsed["mesh"]["connected_to_gate"]
    assert parsed["mesh"]["peerings"] == 2


def test_four_address_data_exposes_wireless_bridge_endpoints():
    fc = (rxd.FTYPE_DATA << 2) | (1 << 8) | (1 << 9)
    frame = struct.pack("<HH", fc, 0) + AP + TARGET + STA + b"\0\0" + AP
    parsed = rxd.parse_80211(frame)

    assert parsed["four_address"]
    assert parsed["addr1"] == rxd.mac(AP)
    assert parsed["addr2"] == rxd.mac(TARGET)
    assert parsed["addr4"] == rxd.mac(AP)


def test_qos_mesh_control_is_only_a_candidate_without_mesh_context():
    fc = (8 << 4) | (rxd.FTYPE_DATA << 2) | (1 << 9)
    header = struct.pack("<HH", fc, 0) + AP + TARGET + STA + b"\0\0"
    parsed = rxd.parse_80211(header + struct.pack("<H", 0x0100) + b"\0" * 6)

    assert parsed["mesh_control_candidate"]
    assert not parsed["four_address"]


def test_client_to_ap_qos_bit_never_means_mesh_control():
    fc = (8 << 4) | (rxd.FTYPE_DATA << 2) | (1 << 8)
    header = struct.pack("<HH", fc, 0) + AP + TARGET + STA + b"\0\0"
    parsed = rxd.parse_80211(header + struct.pack("<H", 0x0100) + b"\0" * 6)

    assert not parsed["mesh_control_candidate"]
