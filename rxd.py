# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Network Weather, Inc.
# Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear).
# See NOTICE.md and RELATED_WORK.md for source lineage and peer implementations.
"""Decode connac2 RX descriptors and the 802.11 frames behind them.

Transcribed from mt7921_mac_fill_rx (mt7921/mac.c) and the MT_RXD* field
definitions in mt76_connac2_mac.h. BSD-3-Clause-Clear, same as the driver.
"""

from __future__ import annotations

import struct

# mt76_connac2_mac.h
MT_RXD0_LENGTH = (0, 0xFFFF)
MT_RXD0_PKT_FLAG = (16, 0xF)
MT_RXD0_PKT_TYPE = (27, 0x1F)

MT_RXD1_NORMAL_WLAN_IDX = (0, 0x3FF)
MT_RXD1_NORMAL_GROUP_1 = 1 << 11
MT_RXD1_NORMAL_GROUP_2 = 1 << 12
MT_RXD1_NORMAL_GROUP_3 = 1 << 13
MT_RXD1_NORMAL_GROUP_4 = 1 << 14
MT_RXD1_NORMAL_GROUP_5 = 1 << 15
MT_RXD1_NORMAL_SEC_MODE = (16, 0x1F)
MT_RXD1_NORMAL_ICV_ERR = 1 << 25
MT_RXD1_NORMAL_FCS_ERR = 1 << 27
MT_RXD1_NORMAL_BAND_IDX = 1 << 28

MT_RXD2_NORMAL_HDR_OFFSET = (14, 0x3)
MT_RXD2_NORMAL_HDR_TRANS = 1 << 13
MT_RXD2_NORMAL_AMSDU_ERR = 1 << 23
MT_RXD2_NORMAL_MAX_LEN_ERROR = 1 << 24
MT_RXD2_NORMAL_NON_AMPDU = 1 << 30
MT_RXD2_NORMAL_FRAG = 1 << 27

# rxd[4] payload format: 0 = single MPDU, 3 = first A-MSDU subframe,
# 2 = middle, 1 = last. Note the encodings are not a simple counter.
MT_RXD4_NORMAL_PAYLOAD_FORMAT = (0, 0x3)
AMSDU_NONE, AMSDU_LAST, AMSDU_MID, AMSDU_FIRST = 0, 1, 2, 3
AMSDU_NAMES = {0: "single", 1: "last", 2: "mid", 3: "first"}

MT_RXD3_NORMAL_CH_FREQ = (8, 0xFF)
MT_RXD3_NORMAL_ADDR_TYPE = (16, 0x3)

# P-RXV / C-RXV RCPI bytes
MT_PRXV_RCPI = ((0, 0xFF), (8, 0xFF), (16, 0xFF), (24, 0xFF))

# rx_pkt_type (mt76_connac2_mac.h)
PKT_TYPE_TXS = 0
PKT_TYPE_TXRXV = 1
PKT_TYPE_NORMAL = 2
PKT_TYPE_RX_DUP_RFB = 3
PKT_TYPE_RX_TMR = 4
PKT_TYPE_RETRIEVE = 5
PKT_TYPE_TXRX_NOTIFY = 6
PKT_TYPE_RX_EVENT = 7
PKT_TYPE_NORMAL_MCU = 17

PKT_TYPE_NAMES = {
    0: "TXS",
    1: "TXRXV",
    2: "NORMAL",
    3: "RX_DUP_RFB",
    4: "RX_TMR",
    5: "RETRIEVE",
    6: "TXRX_NOTIFY",
    7: "RX_EVENT",
    17: "NORMAL_MCU",
}


def fget(val: int, field) -> int:
    shift, mask = field
    return (val >> shift) & mask


def to_rssi(rcpi_byte: int) -> int:
    """to_rssi() in mt7921/mt7921.h."""
    return (rcpi_byte - 220) // 2


def status_freq(chfreq: int):
    """mt792x_get_status_freq_info."""
    if chfreq > 180:
        return "6GHz", (chfreq - 181) * 4 + 1
    if chfreq > 14:
        return "5GHz", chfreq
    return "2.4GHz", chfreq


def decode(buf: bytes) -> dict | None:
    """Decode one RX transfer. Returns None if it is not a normal 802.11 frame."""
    if len(buf) < 24:
        return None
    rxd = list(struct.unpack_from("<6I", buf, 0))
    rxd0, rxd1, rxd2, rxd3 = rxd[0], rxd[1], rxd[2], rxd[3]

    ptype = fget(rxd0, MT_RXD0_PKT_TYPE)
    pflag = fget(rxd0, MT_RXD0_PKT_FLAG)
    if ptype == PKT_TYPE_RX_EVENT and pflag == 0x1:
        ptype = PKT_TYPE_NORMAL_MCU

    out = {
        "pkt_type": ptype,
        "pkt_type_name": PKT_TYPE_NAMES.get(ptype, f"0x{ptype:02x}"),
        "dma_len": fget(rxd0, MT_RXD0_LENGTH),
        "len": len(buf),
        "fcs_err": bool(rxd1 & MT_RXD1_NORMAL_FCS_ERR),
        "icv_err": bool(rxd1 & MT_RXD1_NORMAL_ICV_ERR),
        "sec_mode": fget(rxd1, MT_RXD1_NORMAL_SEC_MODE),
        "wlan_idx": fget(rxd1, MT_RXD1_NORMAL_WLAN_IDX),
        "non_ampdu": bool(rxd2 & MT_RXD2_NORMAL_NON_AMPDU),
        "frag": bool(rxd2 & MT_RXD2_NORMAL_FRAG),
        "amsdu": fget(rxd[4], MT_RXD4_NORMAL_PAYLOAD_FORMAT),
    }
    if ptype not in (PKT_TYPE_NORMAL, PKT_TYPE_NORMAL_MCU):
        return out
    if rxd2 & (MT_RXD2_NORMAL_AMSDU_ERR | MT_RXD2_NORMAL_MAX_LEN_ERROR):
        out["error"] = "amsdu/maxlen"
        return out

    chfreq = fget(rxd3, MT_RXD3_NORMAL_CH_FREQ)
    band, chan = status_freq(chfreq)
    out["band"], out["channel"] = band, chan
    remove_pad = fget(rxd2, MT_RXD2_NORMAL_HDR_OFFSET)

    # Walk the optional groups in the order mt7921_mac_fill_rx does.
    off = 24
    rxv_group3 = rxv_group5 = None
    if rxd1 & MT_RXD1_NORMAL_GROUP_4:
        if off + 16 > len(buf):
            return out
        v0 = struct.unpack_from("<I", buf, off)[0]
        out["fc_rxd"] = v0 & 0xFFFF  # MT_RXD6_FRAME_CONTROL
        off += 16
    if rxd1 & MT_RXD1_NORMAL_GROUP_1:
        off += 16
    if rxd1 & MT_RXD1_NORMAL_GROUP_2:
        if off + 8 <= len(buf):
            out["timestamp"] = struct.unpack_from("<I", buf, off)[0]
        off += 8
    if rxd1 & MT_RXD1_NORMAL_GROUP_3:
        if off + 8 <= len(buf):
            rxv_group3 = struct.unpack_from("<2I", buf, off)
        off += 8
        if rxd1 & MT_RXD1_NORMAL_GROUP_5:
            off += 24
            if off + 4 <= len(buf):
                rxv_group5 = struct.unpack_from("<I", buf, off)[0]
            off += 48

    # Monitor mode reads RCPI from group 5 when present, else group 3's v1.
    rcpi_word = rxv_group5 if rxv_group5 is not None else (rxv_group3[1] if rxv_group3 else None)
    if rcpi_word is not None:
        chains = [to_rssi(fget(rcpi_word, f)) for f in MT_PRXV_RCPI]
        out["chain_signal"] = chains
        valid = [c for c in chains if c < 0]
        out["rssi"] = max(valid) if valid else None

    if rxv_group3 is not None:
        out["phy"] = decode_rxv(rxv_group3[0], rxv_group3[1])

    hdr_gap = off + 2 * remove_pad
    out["hdr_gap"] = hdr_gap
    # The record ends at dma_len, not at the end of the USB transfer: mt76's
    # own mt76u_get_rx_entry_len returns exactly this field under
    # MT_DRV_RX_DMA_HDR. Running to the end of the transfer instead appends 6
    # or 7 bytes of padding, which is invisible on data and control frames but
    # makes every management frame's IE chain overrun.
    end = min(out["dma_len"], len(buf)) if out["dma_len"] else len(buf)
    if hdr_gap < end:
        out["frame"] = buf[hdr_gap:end]
    return out


# ---------------------------------------------------------------------------
# 802.11 parsing, enough to identify a frame and read a beacon's SSID
# ---------------------------------------------------------------------------

FTYPE_MGMT, FTYPE_CTRL, FTYPE_DATA = 0, 1, 2
DATA_ADDR_T2 = 2  # From-DS only, matching Wireshark's shifted FLAG_FROM_DS.
DATA_ADDR_T4 = 3  # To-DS plus From-DS.
QOS_MESH_CONTROL_PRESENT = 0x0100
MESH_FLAGS_ADDRESS_EXTENSION = 0x03

MGMT_SUBTYPES = {
    0: "AssocReq",
    1: "AssocResp",
    2: "ReassocReq",
    3: "ReassocResp",
    4: "ProbeReq",
    5: "ProbeResp",
    6: "TimingAd",
    8: "Beacon",
    9: "ATIM",
    10: "Disassoc",
    11: "Auth",
    12: "Deauth",
    13: "Action",
    14: "ActionNoAck",
}
CTRL_SUBTYPES = {
    2: "Trigger",
    4: "BeamformReport",
    5: "VHT-NDPA",
    7: "CtrlWrapper",
    8: "BlockAckReq",
    9: "BlockAck",
    10: "PS-Poll",
    11: "RTS",
    12: "CTS",
    13: "ACK",
    14: "CF-End",
    15: "CF-End+CF-Ack",
}
DATA_SUBTYPES = {
    0: "Data",
    4: "Null",
    8: "QoSData",
    12: "QoSNull",
}

# Information-element and management constants verified against Linux
# include/linux/ieee80211.h and Wireshark packet-ieee80211.{c,h}, 2026-08-28.
EID_RSN = 48
EID_NEIGHBOR_REPORT = 52
EID_MOBILITY_DOMAIN = 54
EID_FAST_BSS_TRANSITION = 55
EID_RRM_ENABLED_CAPABILITIES = 70
EID_MESH_CONFIG = 113
EID_MESH_ID = 114
EID_PEER_MGMT = 117
EID_EXT_CAPABILITY = 127
EID_MEASURE_REQUEST = 38
EID_MEASURE_REPORT = 39
EID_VENDOR_SPECIFIC = 221

AUTH_ALGORITHMS = {
    0: "open",
    1: "shared-key",
    2: "fast-transition",
    3: "sae",
    4: "fils-sk",
    5: "fils-sk-pfs",
    6: "fils-pk",
    8: "ieee8021x",
}

ACTION_CATEGORIES = {
    5: "radio-measurement",
    6: "fast-transition",
    10: "wnm",
    13: "mesh",
    15: "self-protected",
}
RRM_ACTIONS = {
    0: "measurement-request",
    1: "measurement-report",
    2: "link-measurement-request",
    3: "link-measurement-report",
    4: "neighbor-report-request",
    5: "neighbor-report-response",
}
WNM_ACTIONS = {6: "btm-query", 7: "btm-request", 8: "btm-response"}
FT_ACTIONS = {1: "ft-request", 2: "ft-response", 3: "ft-confirm", 4: "ft-ack"}
MESH_ACTIONS = {
    0: "mesh-link-metric-report",
    1: "hwmp-path-selection",
    2: "mesh-gate-announcement",
    3: "mesh-congestion-control",
    4: "mcca-setup-request",
    5: "mcca-setup-reply",
    6: "mcca-advertisement-request",
    7: "mcca-advertisement",
    8: "mcca-teardown",
    9: "tbtt-adjustment-request",
    10: "tbtt-adjustment-response",
}
SELF_PROTECTED_ACTIONS = {
    1: "mesh-peering-open",
    2: "mesh-peering-confirm",
    3: "mesh-peering-close",
}
MEASUREMENT_TYPES = {
    0: "basic",
    1: "cca",
    2: "rpi-histogram",
    3: "channel-load",
    4: "noise-histogram",
    5: "beacon",
    6: "frame",
    7: "station-statistics",
    8: "lci",
    9: "transmit-stream",
    10: "multicast-diagnostics",
    11: "civic-location",
    12: "location-identifier",
    13: "directional-channel-quality",
    14: "directional-measurement",
    15: "directional-statistics",
    16: "ftm-range",
    255: "measurement-pause",
}

BTM_STATUS = {
    0: "accept",
    1: "reject-unspecified",
    2: "reject-insufficient-beacon",
    3: "reject-insufficient-capacity",
    4: "reject-bss-terminated",
    5: "reject-delay-requested",
    6: "reject-candidate-list-provided",
    7: "reject-no-suitable-candidates",
    8: "reject-leaving-ess",
}

REASON_NAMES = {
    1: "unspecified",
    2: "prev-auth-invalid",
    3: "deauth-leaving",
    4: "inactivity",
    5: "ap-busy",
    6: "class2-from-nonauth",
    7: "class3-from-nonassoc",
    8: "disassoc-leaving",
    9: "assoc-not-auth",
    13: "invalid-ie",
    14: "mic-failure",
    15: "4way-timeout",
    16: "group-key-timeout",
    17: "ie-mismatch",
    18: "invalid-group-cipher",
    19: "invalid-pairwise-cipher",
    20: "invalid-akmp",
    23: "ieee8021x-failed",
    24: "cipher-rejected",
    34: "low-ack",
    71: "poor-rssi",
}
STATUS_NAMES = {
    0: "success",
    1: "unspecified-failure",
    17: "ap-cannot-handle-more-sta",
    27: "assoc-denied-no-ht",
    30: "assoc-rejected-temporarily",
    31: "robust-mgmt-policy-violation",
    37: "request-declined",
    82: "assoc-denied-no-he",
}

FT_AKM_TYPES = {3, 4, 9, 13, 16, 17, 19, 25}
AKM_NAMES = {
    1: "802.1X",
    2: "PSK",
    3: "FT-802.1X",
    4: "FT-PSK",
    5: "802.1X-SHA256",
    6: "PSK-SHA256",
    8: "SAE",
    9: "FT-SAE",
    13: "FT-802.1X-SHA384",
    16: "FT-FILS-SHA256",
    17: "FT-FILS-SHA384",
    18: "OWE",
    19: "FT-PSK-SHA384",
    25: "FT-SAE-GROUP-DEPEND",
}

WFA_OUI = b"\x50\x6f\x9a"
MULTI_AP_OUI_TYPE = 0x1B
MULTI_AP_EXTENSION = 0x06
MULTI_AP_PROFILE = 0x07
MULTI_AP_FRONTHAUL_BSS = 1 << 5
MULTI_AP_BACKHAUL_BSS = 1 << 6
MULTI_AP_BACKHAUL_STA = 1 << 7


def mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def _decode_text(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.hex()


def _suite_name(suite: bytes) -> str:
    if len(suite) != 4:
        return suite.hex()
    if suite[:3] == b"\x00\x0f\xac":
        return AKM_NAMES.get(suite[3], f"00:0f:ac:{suite[3]}")
    return ":".join(f"{x:02x}" for x in suite)


def parse_rsn(value: bytes) -> dict:
    """Decode the RSN fields needed for FT and PMF conclusions."""
    out = {"truncated": False, "akm_suites": [], "ft_akm": False}
    if len(value) < 8:
        out["truncated"] = True
        return out

    out["version"] = struct.unpack_from("<H", value, 0)[0]
    offset = 6  # version plus group cipher suite
    pairwise_count = struct.unpack_from("<H", value, offset)[0]
    offset += 2 + pairwise_count * 4
    if offset + 2 > len(value):
        out["truncated"] = True
        return out
    akm_count = struct.unpack_from("<H", value, offset)[0]
    offset += 2
    if offset + akm_count * 4 > len(value):
        out["truncated"] = True
        return out
    suites = [value[offset + i * 4 : offset + (i + 1) * 4] for i in range(akm_count)]
    out["akm_suites"] = [_suite_name(suite) for suite in suites]
    out["ft_akm"] = any(
        suite[:3] == b"\x00\x0f\xac" and suite[3] in FT_AKM_TYPES for suite in suites
    )
    offset += akm_count * 4

    capabilities = None
    if offset + 2 <= len(value):
        capabilities = struct.unpack_from("<H", value, offset)[0]
    out["capabilities"] = capabilities
    out["pmf_capable"] = bool(capabilities is not None and capabilities & 0x0080)
    out["pmf_required"] = bool(capabilities is not None and capabilities & 0x0040)
    if out["pmf_required"]:
        out["pmf"] = "required"
    elif out["pmf_capable"]:
        out["pmf"] = "optional"
    elif capabilities is not None:
        out["pmf"] = "disabled"
    else:
        out["pmf"] = "unadvertised-or-truncated"
    return out


def parse_rrm_capabilities(value: bytes) -> dict:
    """Decode the homeowner-relevant bits of the five-byte 11k capability IE."""
    names = {
        0: "link_measurement",
        1: "neighbor_report",
        4: "beacon_passive",
        5: "beacon_active",
        6: "beacon_table",
        8: "frame_measurement",
        9: "channel_load",
        10: "noise_histogram",
        11: "station_statistics",
        16: "ap_channel_report",
        29: "rcpi",
        30: "rsni",
    }
    bits = int.from_bytes(value[:5].ljust(5, b"\0"), "little")
    return {
        "valid_length": len(value) == 5,
        **{name: bool(bits & (1 << bit)) for bit, name in names.items()},
    }


def parse_mobility_domain(value: bytes) -> dict:
    if len(value) < 3:
        return {"truncated": True}
    capability = value[2]
    return {
        "truncated": False,
        "id": f"{struct.unpack_from('<H', value, 0)[0]:04x}",
        "ft_over_ds": bool(capability & 0x01),
        "resource_request": bool(capability & 0x02),
    }


def parse_neighbor_report(value: bytes) -> dict:
    if len(value) < 13:
        return {"truncated": True, "length": len(value)}
    report = {
        "truncated": False,
        "bssid": mac(value[:6]),
        "bssid_info": struct.unpack_from("<I", value, 6)[0],
        "operating_class": value[10],
        "channel": value[11],
        "phy_type": value[12],
    }
    offset = 13
    while offset + 2 <= len(value):
        sub_id, sub_len = value[offset], value[offset + 1]
        offset += 2
        if offset + sub_len > len(value):
            report["subelements_truncated"] = True
            break
        sub = value[offset : offset + sub_len]
        if sub_id == 3 and sub_len >= 1:
            report["preference"] = sub[0]
        elif sub_id == 6 and sub_len >= 3:
            report["wide_bandwidth"] = {
                "width_code": sub[0],
                "center_segment_0": sub[1],
                "center_segment_1": sub[2],
            }
        offset += sub_len
    return report


def parse_neighbor_reports(ie_list: list[tuple[int, bytes]]) -> list[dict]:
    return [parse_neighbor_report(value) for eid, value in ie_list if eid == EID_NEIGHBOR_REPORT]


def parse_measurements(ie_list: list[tuple[int, bytes]]) -> list[dict]:
    out = []
    for eid, value in ie_list:
        if eid not in (EID_MEASURE_REQUEST, EID_MEASURE_REPORT) or len(value) < 3:
            continue
        measure_type = value[2]
        out.append(
            {
                "direction": "request" if eid == EID_MEASURE_REQUEST else "report",
                "token": value[0],
                "mode": value[1],
                "type": measure_type,
                "type_name": MEASUREMENT_TYPES.get(measure_type, "unknown"),
            }
        )
    return out


def parse_multi_ap(ie_list: list[tuple[int, bytes]]) -> dict | None:
    """Decode the Wi-Fi Alliance EasyMesh/Multi-AP vendor element."""
    capabilities = 0
    profiles = set()
    found = False
    truncated = False
    for eid, value in ie_list:
        if (
            eid != EID_VENDOR_SPECIFIC
            or len(value) < 4
            or value[:3] != WFA_OUI
            or value[3] != MULTI_AP_OUI_TYPE
        ):
            continue
        found = True
        offset = 4
        while offset + 2 <= len(value):
            sub_id, sub_len = value[offset], value[offset + 1]
            offset += 2
            if offset + sub_len > len(value):
                truncated = True
                break
            sub = value[offset : offset + sub_len]
            if sub_id == MULTI_AP_EXTENSION and sub_len >= 1:
                capabilities |= sub[0]
            elif sub_id == MULTI_AP_PROFILE and sub_len >= 1:
                profiles.add(sub[0])
            offset += sub_len
    if not found:
        return None
    return {
        "backhaul_sta": bool(capabilities & MULTI_AP_BACKHAUL_STA),
        "backhaul_bss": bool(capabilities & MULTI_AP_BACKHAUL_BSS),
        "fronthaul_bss": bool(capabilities & MULTI_AP_FRONTHAUL_BSS),
        "profiles": sorted(profiles),
        "truncated": truncated,
    }


def parse_mesh(ies: dict[int, bytes]) -> dict | None:
    if EID_MESH_ID not in ies and EID_MESH_CONFIG not in ies:
        return None
    out = {"standard": "802.11s"}
    if EID_MESH_ID in ies:
        out["id"] = _decode_text(ies[EID_MESH_ID])
    config = ies.get(EID_MESH_CONFIG)
    if config is not None:
        out["config_valid_length"] = len(config) == 7
        if len(config) >= 7:
            formation, capability = config[5], config[6]
            out.update(
                {
                    "path_protocol": config[0],
                    "path_metric": config[1],
                    "congestion_control": config[2],
                    "sync_method": config[3],
                    "auth_protocol": config[4],
                    "connected_to_gate": bool(formation & 0x01),
                    "peerings": (formation >> 1) & 0x3F,
                    "accepting_peerings": bool(capability & 0x01),
                    "forwarding": bool(capability & 0x08),
                }
            )
    return out


def _ies_from(value: bytes) -> dict:
    return parse_ies(value) if value else {"ies": {}, "ie_list": []}


def parse_action(frame: bytes, protected: bool) -> dict:
    """Decode roam and mesh action bodies, never interpreting protected bytes."""
    if protected:
        return {"protected": True}
    if len(frame) < 26:
        return {"protected": False, "truncated": True}

    body = frame[24:]
    category, code = body[0], body[1]
    out = {
        "protected": False,
        "category": category,
        "category_name": ACTION_CATEGORIES.get(category, "other"),
        "code": code,
    }

    if category == 5:
        out["name"] = RRM_ACTIONS.get(code, "rrm-unknown")
        if len(body) >= 3:
            out["dialog_token"] = body[2]
        ie_offset = None
        if code == 0 and len(body) >= 5:
            out["repetitions"] = struct.unpack_from(">H", body, 3)[0]
            ie_offset = 5
        elif code in (1, 4, 5):
            ie_offset = 3
        elif code == 2 and len(body) >= 5:
            out["tx_power_dbm"] = struct.unpack_from("b", body, 3)[0]
            out["max_tx_power_dbm"] = struct.unpack_from("b", body, 4)[0]
        elif code == 3 and len(body) >= 11:
            out.update(
                {
                    "tx_power_dbm": struct.unpack_from("b", body, 5)[0],
                    "link_margin_db": struct.unpack_from("b", body, 6)[0],
                    "rx_antenna": body[7],
                    "tx_antenna": body[8],
                    "rcpi": body[9],
                    "rsni": body[10],
                }
            )
        if ie_offset is not None and len(body) >= ie_offset:
            decoded = _ies_from(body[ie_offset:])
            out["neighbor_reports"] = parse_neighbor_reports(decoded["ie_list"])
            out["measurements"] = parse_measurements(decoded["ie_list"])

    elif category == 10:
        out["name"] = WNM_ACTIONS.get(code, "wnm-unknown")
        if len(body) >= 3:
            out["dialog_token"] = body[2]
        if code == 6 and len(body) >= 4:
            out["query_reason"] = body[3]
            decoded = _ies_from(body[4:])
            out["neighbor_reports"] = parse_neighbor_reports(decoded["ie_list"])
        elif code == 7 and len(body) >= 7:
            mode = body[3]
            out.update(
                {
                    "request_mode": mode,
                    "preferred_candidates": bool(mode & 0x01),
                    "abridged": bool(mode & 0x02),
                    "disassociation_imminent": bool(mode & 0x04),
                    "bss_termination_included": bool(mode & 0x08),
                    "ess_disassociation_imminent": bool(mode & 0x10),
                    "link_removal_imminent": bool(mode & 0x20),
                    "disassociation_timer": struct.unpack_from("<H", body, 4)[0],
                    "validity_interval": body[6],
                }
            )
            offset = 7
            if mode & 0x08 and len(body) >= offset + 12:
                offset += 12
            if mode & 0x10 and len(body) > offset:
                url_len = body[offset]
                offset += 1
                if len(body) >= offset + url_len:
                    out["session_url"] = _decode_text(body[offset : offset + url_len])
                    offset += url_len
            decoded = _ies_from(body[offset:])
            out["neighbor_reports"] = parse_neighbor_reports(decoded["ie_list"])
        elif code == 8 and len(body) >= 5:
            status = body[3]
            out.update(
                {
                    "status": status,
                    "status_name": BTM_STATUS.get(status, "unknown"),
                    "termination_delay": body[4],
                }
            )
            offset = 5
            if status == 0 and len(body) >= 11:
                out["target_bssid"] = mac(body[5:11])
                offset = 11
            decoded = _ies_from(body[offset:])
            out["neighbor_reports"] = parse_neighbor_reports(decoded["ie_list"])

    elif category == 6:
        out["name"] = FT_ACTIONS.get(code, "ft-unknown")
        if len(body) >= 14:
            out["station"] = mac(body[2:8])
            out["target_ap"] = mac(body[8:14])
            offset = 14
            if code in (2, 4) and len(body) >= 16:
                out["status"] = struct.unpack_from("<H", body, 14)[0]
                offset = 16
            decoded = _ies_from(body[offset:])
            if decoded.get("mobility_domain"):
                out["mobility_domain"] = decoded["mobility_domain"]
            out["ft_ie"] = EID_FAST_BSS_TRANSITION in decoded.get("ies", {})

    elif category == 13:
        out["name"] = MESH_ACTIONS.get(code, "mesh-unknown")
    elif category == 15:
        out["name"] = SELF_PROTECTED_ACTIONS.get(code, "self-protected-unknown")
    else:
        out["name"] = "action-unknown"
    return out


def parse_80211(frame: bytes) -> dict:
    """Frame type, addresses, management evidence, and advertised IEs."""
    if len(frame) < 10:
        return {"type": "short", "len": len(frame)}
    fc = struct.unpack_from("<H", frame, 0)[0]
    ftype = (fc >> 2) & 0x3
    subtype = (fc >> 4) & 0xF
    out = {
        "fc": fc,
        "ftype": ftype,
        "subtype": subtype,
        "len": len(frame),
        "to_ds": bool(fc & (1 << 8)),
        "from_ds": bool(fc & (1 << 9)),
        "more_fragments": bool(fc & (1 << 10)),
        "retry": bool(fc & (1 << 11)),
        "protected": bool(fc & (1 << 14)),
    }

    if ftype == FTYPE_MGMT:
        out["kind"] = MGMT_SUBTYPES.get(subtype, f"Mgmt{subtype}")
    elif ftype == FTYPE_CTRL:
        out["kind"] = CTRL_SUBTYPES.get(subtype, f"Ctrl{subtype}")
    else:
        out["kind"] = DATA_SUBTYPES.get(subtype, f"Data{subtype}")

    if ftype == FTYPE_CTRL:
        if len(frame) >= 10:
            out["addr1"] = mac(frame[4:10])
        return out

    if len(frame) >= 22:
        out["addr1"] = mac(frame[4:10])
        out["addr2"] = mac(frame[10:16])
        out["addr3"] = mac(frame[16:22])

    if ftype == FTYPE_DATA and out["to_ds"] and out["from_ds"]:
        out["four_address"] = True
        if len(frame) >= 30:
            out["addr4"] = mac(frame[24:30])
    elif ftype == FTYPE_DATA:
        out["four_address"] = False

    if ftype == FTYPE_DATA and subtype & 0x08:
        qos_offset = 30 if out.get("four_address") else 24
        if len(frame) >= qos_offset + 2:
            qos_control = struct.unpack_from("<H", frame, qos_offset)[0]
            out["qos_control"] = qos_control
            # Bit 8 means Mesh Control Present only for a mesh STA in a mesh
            # BSS. In an infrastructure BSS the same overloaded field can be
            # TXOP, AP power-save, or queue state. Wireshark therefore calls
            # this heuristic and also validates the following Mesh Flags byte.
            # Keep it a candidate here; Dwell requires independent 802.11s
            # beacon/action evidence before reporting a standard mesh link.
            if len(frame) >= qos_offset + 3:
                mesh_flags = frame[qos_offset + 2]
                address_selector = (fc >> 8) & 0x03
                address_extension = mesh_flags & MESH_FLAGS_ADDRESS_EXTENSION
                out["mesh_control_candidate"] = bool(
                    address_selector in (DATA_ADDR_T2, DATA_ADDR_T4)
                    and qos_control & QOS_MESH_CONTROL_PRESENT
                    and not (mesh_flags & ~MESH_FLAGS_ADDRESS_EXTENSION)
                    and address_extension != MESH_FLAGS_ADDRESS_EXTENSION
                )

    if ftype == FTYPE_MGMT and subtype in (5, 8) and len(frame) > 36:
        # Beacon / Probe Response: 24-byte header, then 12 bytes of fixed
        # parameters (timestamp, beacon interval, capability), then IEs.
        out["tsf"] = struct.unpack_from("<Q", frame, 24)[0]
        bi, cap = struct.unpack_from("<HH", frame, 32)
        out["beacon_interval_tu"] = bi
        out["beacon_interval_ms"] = round(bi * 1024 / 1000, 1)
        out["capability"] = cap
        out["privacy"] = bool(cap & 0x0010)
        out.update(parse_ies(frame[36:]))
    elif ftype == FTYPE_MGMT and subtype in (0, 2, 4):
        # Client-originated management frames expose the station's own
        # capabilities. Association Request has 4 fixed bytes after the MAC
        # header, Reassociation Request has 10, and Probe Request has none.
        # Parsing these lets a passive survey distinguish a legacy client from
        # a modern client using a constrained link. It does not prove which AP
        # a scanning Probe Request will eventually choose.
        ie_offset = {0: 28, 2: 34, 4: 24}[subtype]
        if len(frame) >= ie_offset:
            out.update(parse_ies(frame[ie_offset:]))
    elif ftype == FTYPE_MGMT and subtype in (1, 3):
        if len(frame) >= 30:
            capability, status, aid = struct.unpack_from("<HHH", frame, 24)
            out.update(
                {
                    "capability": capability,
                    "status": status,
                    "status_name": STATUS_NAMES.get(status, "unknown"),
                    "aid": aid & 0x3FFF,
                }
            )
            out.update(parse_ies(frame[30:]))
    elif ftype == FTYPE_MGMT and subtype == 11:
        if len(frame) >= 30:
            algorithm, sequence, status = struct.unpack_from("<HHH", frame, 24)
            out.update(
                {
                    "auth_algorithm": algorithm,
                    "auth_algorithm_name": AUTH_ALGORITHMS.get(algorithm, "unknown"),
                    "auth_sequence": sequence,
                    "status": status,
                    "status_name": STATUS_NAMES.get(status, "unknown"),
                }
            )
            out.update(parse_ies(frame[30:]))
    elif ftype == FTYPE_MGMT and subtype in (10, 12):
        if len(frame) >= 26:
            reason = struct.unpack_from("<H", frame, 24)[0]
            out["reason"] = reason
            out["reason_name"] = REASON_NAMES.get(reason, "unknown")
    elif ftype == FTYPE_MGMT and subtype in (13, 14):
        out["action"] = parse_action(frame, out["protected"])
    return out


def parse_ies(body: bytes) -> dict:
    """Walk the IE chain.

    Element IDs repeat: 255 (element extension) appears once per HE/EHT/MLO
    sub-element and 221 (vendor specific) once per vendor. Keying a dict by
    element ID therefore loses all but the last of each, which silently
    under-reports capabilities. `ies` keeps first-wins for the singleton
    elements callers expect; `ie_list` keeps every instance in order, and
    `ext_ids` is the set of element-255 extension ids present.
    """
    out = {"ies": {}, "ie_list": [], "ext_ids": set(), "vendor_ouis": set()}
    i = 0
    while i + 2 <= len(body):
        eid, elen = body[i], body[i + 1]
        i += 2
        if i + elen > len(body):
            break
        val = body[i : i + elen]
        out["ie_list"].append((eid, val))
        if eid == 255 and val:
            out["ext_ids"].add(val[0])
        elif eid == 221 and len(val) >= 3:
            out["vendor_ouis"].add(val[:3].hex())
        out["ies"].setdefault(eid, val)
        if eid == 0:  # SSID
            try:
                out["ssid"] = val.decode("utf-8")
            except UnicodeDecodeError:
                out["ssid"] = repr(val)
            if not val:
                out["ssid"] = "<hidden>"
        elif eid == 3 and elen >= 1:  # DS Parameter Set
            out["ds_channel"] = val[0]
        elif eid == 11 and elen >= 5:  # BSS Load
            sta_count, ch_util = struct.unpack("<HB", val[:3])
            out["bss_load"] = {
                "stations": sta_count,
                "channel_util_pct": round(ch_util * 100 / 255),
            }
        i += elen

    ies = out["ies"]
    if EID_RSN in ies:
        out["rsn"] = parse_rsn(ies[EID_RSN])
    if EID_RRM_ENABLED_CAPABILITIES in ies:
        out["rrm_capabilities"] = parse_rrm_capabilities(ies[EID_RRM_ENABLED_CAPABILITIES])
    if EID_EXT_CAPABILITY in ies:
        extended = ies[EID_EXT_CAPABILITY]
        out["bss_transition"] = len(extended) >= 3 and bool(extended[2] & 0x08)
    if EID_MOBILITY_DOMAIN in ies:
        out["mobility_domain"] = parse_mobility_domain(ies[EID_MOBILITY_DOMAIN])
    out["ft_ie"] = EID_FAST_BSS_TRANSITION in ies
    multi_ap = parse_multi_ap(out["ie_list"])
    if multi_ap is not None:
        out["multi_ap"] = multi_ap
    mesh = parse_mesh(ies)
    if mesh is not None:
        out["mesh"] = mesh
    return out


def management_event(parsed: dict) -> tuple[str, dict] | None:
    """Return normalized roaming or mesh evidence from a parsed frame."""
    if parsed.get("ftype") != FTYPE_MGMT:
        return None
    subtype = parsed.get("subtype")
    if subtype in (10, 12):
        return (
            "deauth" if subtype == 12 else "disassoc",
            {
                "reason": parsed.get("reason"),
                "reason_name": parsed.get("reason_name", "unknown"),
                "protected": parsed.get("protected", False),
            },
        )
    if subtype in (0, 2):
        name = "assoc_req" if subtype == 0 else "reassoc_req"
        if parsed.get("mobility_domain") or parsed.get("ft_ie"):
            name = f"ft_{name}"
        return name, _roam_ie_detail(parsed)
    if subtype in (1, 3):
        name = "assoc_resp" if subtype == 1 else "reassoc_resp"
        if parsed.get("mobility_domain") or parsed.get("ft_ie"):
            name = f"ft_{name}"
        return (
            name,
            {
                "status": parsed.get("status"),
                "status_name": parsed.get("status_name", "unknown"),
                "aid": parsed.get("aid"),
                **_roam_ie_detail(parsed),
            },
        )
    if subtype == 11:
        name = "ft_auth" if parsed.get("auth_algorithm") == 2 else "auth"
        return (
            name,
            {
                "algorithm": parsed.get("auth_algorithm"),
                "algorithm_name": parsed.get("auth_algorithm_name"),
                "sequence": parsed.get("auth_sequence"),
                "status": parsed.get("status"),
                "status_name": parsed.get("status_name"),
                **_roam_ie_detail(parsed),
            },
        )
    if subtype in (13, 14):
        action = parsed.get("action", {})
        if action.get("protected"):
            return "protected_action", {"protected": True}
        name = action.get("name")
        if name and name != "action-unknown":
            return name.replace("-", "_"), {
                key: value for key, value in action.items() if key != "name"
            }
    return None


def _roam_ie_detail(parsed: dict) -> dict:
    keys = (
        "mobility_domain",
        "ft_ie",
        "rsn",
        "rrm_capabilities",
        "bss_transition",
        "multi_ap",
        "mesh",
    )
    return {key: parsed[key] for key in keys if key in parsed}


# ---------------------------------------------------------------------------
# PHY rate decode (mt76_connac2_mac_fill_rx_rate) and airtime
#
# Airtime is the quantity a survey actually cares about: a channel is busy in
# microseconds, not in frames. That needs the PHY rate of every frame, which
# lives in the P-RXV group, not in the 802.11 header.
# ---------------------------------------------------------------------------

MT_PRXV_TX_RATE = (0, 0x7F)
MT_PRXV_TX_DCM = 1 << 4
MT_PRXV_TX_ER_SU_106T = 1 << 5
MT_PRXV_NSTS = (7, 0x7)
MT_PRXV_HT_AD_CODE = 1 << 11
MT_PRXV_FRAME_MODE = (12, 0x7)
MT_PRXV_HT_SGI = (15, 0x3)
MT_PRXV_HT_STBC = (22, 0x3)
MT_PRXV_TX_MODE = (24, 0xF)

(
    MT_PHY_TYPE_CCK,
    MT_PHY_TYPE_OFDM,
    MT_PHY_TYPE_HT,
    MT_PHY_TYPE_HT_GF,
    MT_PHY_TYPE_VHT,
) = (0, 1, 2, 3, 4)
MT_PHY_TYPE_HE_SU, MT_PHY_TYPE_HE_EXT_SU, MT_PHY_TYPE_HE_TB, MT_PHY_TYPE_HE_MU = (
    8,
    9,
    10,
    11,
)
MT_PHY_TYPE_EHT_SU, MT_PHY_TYPE_EHT_TRIG, MT_PHY_TYPE_EHT_MU = 13, 14, 15

PHY_MODE_NAMES = {
    0: "CCK",
    1: "OFDM",
    2: "HT",
    3: "HT-GF",
    4: "VHT",
    8: "HE-SU",
    9: "HE-ER-SU",
    10: "HE-TB",
    11: "HE-MU",
    13: "EHT-SU",
    14: "EHT-TRIG",
    15: "EHT-MU",
}

# mt76_rates: hw_value -> Mbps. CCK first, then OFDM.
CCK_HW_TO_MBPS = {0: 1.0, 1: 2.0, 2: 5.5, 3: 11.0}
OFDM_HW_TO_MBPS = {
    11: 6.0,
    15: 9.0,
    10: 12.0,
    14: 18.0,
    9: 24.0,
    13: 36.0,
    8: 48.0,
    12: 54.0,
}

BW_MHZ = {0: 20, 1: 40, 2: 80, 3: 160}

# MCS index -> (bits per subcarrier per stream, coding rate)
MCS_PARAMS = {
    0: (1, 1 / 2),
    1: (2, 1 / 2),
    2: (2, 3 / 4),
    3: (4, 1 / 2),
    4: (4, 3 / 4),
    5: (6, 2 / 3),
    6: (6, 3 / 4),
    7: (6, 5 / 6),
    8: (8, 3 / 4),
    9: (8, 5 / 6),
    10: (10, 3 / 4),
    11: (10, 5 / 6),
}

# Data subcarriers per bandwidth
NSD_HT_VHT = {20: 52, 40: 108, 80: 234, 160: 468}
NSD_HE = {20: 234, 40: 468, 80: 980, 160: 1960}

# Symbol duration in microseconds, including guard interval
TSYM_HT_VHT = {0: 4.0, 1: 3.6}  # long GI, short GI
TSYM_HE = {0: 13.6, 1: 14.4, 2: 16.0, 3: 16.0}  # 0.8 / 1.6 / 3.2 us GI


def phy_rate_mbps(mode, mcs, nss, bw_mhz, gi, dcm=False):
    """PHY data rate from the standard formula, not a lookup table."""
    if mode == MT_PHY_TYPE_CCK:
        return CCK_HW_TO_MBPS.get(mcs & ~0x4)  # bit 2 is short preamble
    if mode == MT_PHY_TYPE_OFDM:
        return OFDM_HW_TO_MBPS.get(mcs)
    if mode in (MT_PHY_TYPE_HT, MT_PHY_TYPE_HT_GF):
        # HT MCS 0..31 encodes stream count in the high bits
        streams = (mcs // 8) + 1
        m = mcs % 8
        if m not in MCS_PARAMS:
            return None
        bits, coding = MCS_PARAMS[m]
        nsd = NSD_HT_VHT.get(bw_mhz)
        tsym = TSYM_HT_VHT.get(1 if gi else 0, 4.0)
        return nsd and round(nsd * bits * coding * streams / tsym, 1)
    if mode == MT_PHY_TYPE_VHT:
        if mcs not in MCS_PARAMS:
            return None
        bits, coding = MCS_PARAMS[mcs]
        nsd = NSD_HT_VHT.get(bw_mhz)
        tsym = TSYM_HT_VHT.get(1 if gi else 0, 4.0)
        return nsd and round(nsd * bits * coding * nss / tsym, 1)
    if mode in (
        MT_PHY_TYPE_HE_SU,
        MT_PHY_TYPE_HE_EXT_SU,
        MT_PHY_TYPE_HE_TB,
        MT_PHY_TYPE_HE_MU,
    ):
        if mcs not in MCS_PARAMS:
            return None
        bits, coding = MCS_PARAMS[mcs]
        if dcm:
            bits = max(1, bits // 2)
        nsd = NSD_HE.get(bw_mhz)
        tsym = TSYM_HE.get(gi, 13.6)
        return nsd and round(nsd * bits * coding * nss / tsym, 1)
    return None


# Preamble and per-frame overhead in microseconds. Approximate but stable:
# these dominate short frames, which dominate frame counts.
PREAMBLE_US = {
    MT_PHY_TYPE_CCK: 192,  # long preamble DSSS
    MT_PHY_TYPE_OFDM: 20,
    MT_PHY_TYPE_HT: 36,
    MT_PHY_TYPE_HT_GF: 24,
    MT_PHY_TYPE_VHT: 40,
    MT_PHY_TYPE_HE_SU: 52,
    MT_PHY_TYPE_HE_EXT_SU: 52,
    MT_PHY_TYPE_HE_TB: 52,
    MT_PHY_TYPE_HE_MU: 60,
}
SIFS_US = 16
SLOT_US = 9


def airtime_us(frame_len, mode, rate_mbps):
    """Rough on-air duration of one frame, preamble plus payload."""
    if not rate_mbps:
        return None
    pre = PREAMBLE_US.get(mode, 20)
    return round(pre + (frame_len * 8) / rate_mbps, 1)


def decode_rxv(rxv0, rxv2=0):
    """Decode the P-RXV rate words into something reportable."""
    idx = fget(rxv0, MT_PRXV_TX_RATE)
    nsts = fget(rxv0, MT_PRXV_NSTS)
    stbc = fget(rxv0, MT_PRXV_HT_STBC)
    gi = fget(rxv0, MT_PRXV_HT_SGI)
    mode = fget(rxv0, MT_PRXV_TX_MODE)
    bw = fget(rxv0, MT_PRXV_FRAME_MODE)
    dcm = bool(idx & MT_PRXV_TX_DCM)
    ldpc = bool(rxv0 & MT_PRXV_HT_AD_CODE)

    nss = nsts + 1
    if stbc and nss > 1:
        nss >>= 1

    mcs = idx
    if mode in (
        MT_PHY_TYPE_VHT,
        MT_PHY_TYPE_HE_SU,
        MT_PHY_TYPE_HE_EXT_SU,
        MT_PHY_TYPE_HE_TB,
        MT_PHY_TYPE_HE_MU,
    ):
        mcs = idx & 0xF

    bw_mhz = BW_MHZ.get(bw)
    rate = phy_rate_mbps(mode, mcs, nss, bw_mhz, gi, dcm)
    return {
        "mode": mode,
        "mode_name": PHY_MODE_NAMES.get(mode, f"mode{mode}"),
        "mcs": mcs,
        "nss": nss,
        "bw_mhz": bw_mhz,
        "gi": gi,
        "stbc": bool(stbc),
        "ldpc": ldpc,
        "dcm": dcm,
        "rate_mbps": rate,
    }


# ---------------------------------------------------------------------------
# Aggregation-aware airtime
#
# Hardware de-aggregates an A-MPDU before handing it up, so each subframe
# arrives as its own transfer. Charging every subframe a full preamble is the
# single largest error in naive airtime accounting: a 40-subframe A-MPDU on a
# busy 5 GHz channel gets billed 40 preambles instead of one.
#
# The driver groups subframes by the RXD group-2 timestamp, which all members
# of one A-MPDU share (mt7921_mac_fill_rx). We do the same, then bill the
# aggregate once: one preamble, then every subframe's bytes plus its 4-byte
# MPDU delimiter, each padded to a 4-byte boundary.
# ---------------------------------------------------------------------------

MPDU_DELIMITER_BYTES = 4


def _mpdu_bytes_on_air(frame_len):
    """One MPDU inside an A-MPDU: delimiter, payload, pad to 4 bytes."""
    n = MPDU_DELIMITER_BYTES + frame_len
    return n + (-n % 4)


class Aggregate:
    """One A-MPDU, or a single non-aggregated frame."""

    __slots__ = ("frames", "is_ampdu", "mode", "rate_mbps", "timestamp")

    def __init__(self, timestamp, mode, rate_mbps, is_ampdu):
        self.timestamp = timestamp
        self.frames = []
        self.mode = mode
        self.rate_mbps = rate_mbps
        self.is_ampdu = is_ampdu

    def add(self, frame_len):
        self.frames.append(frame_len)

    @property
    def n(self):
        return len(self.frames)

    @property
    def bytes(self):
        return sum(self.frames)

    def airtime_us(self):
        if not self.rate_mbps:
            return None
        pre = PREAMBLE_US.get(self.mode, 20)
        if not self.is_ampdu:
            return round(pre + (self.bytes * 8) / self.rate_mbps, 2)
        on_air = sum(_mpdu_bytes_on_air(f) for f in self.frames)
        return round(pre + (on_air * 8) / self.rate_mbps, 2)


class AggregationTracker:
    """Groups received frames into aggregates as they stream in.

    mt7921_mac_fill_rx groups A-MPDU subframes by equality of the RXD group-2
    timestamp, on the stated assumption that "all subframes of an A-MPDU have
    the same timestamp". **That is not true on mt7921 USB.** Measured on a
    loaded 80 MHz channel, every subframe carries its own timestamp,
    incrementing by roughly its own on-air duration:

        2376006  len=173   dt=8      <- one A-MPDU,
        2376014  len=171   dt=8         six subframes,
        2376022  len=173   dt=8         six distinct timestamps
        2376030  len=174   dt=8
        2376049  len=979   dt=19
        2376062  len=955   dt=13

    So we group on physics instead. Subframes of an A-MPDU are contiguous on
    air from one transmitter, so a frame continues the current aggregate when
    it comes from the same address, is itself flagged as aggregated, and
    arrives no later than the previous subframe's own airtime plus a small
    slack. Anything else starts a new one. Inter-aggregate gaps measured here
    are 1000 us and up against sub-30 us within, so the boundary is not
    delicate.
    """

    #: Extra microseconds allowed on top of the previous subframe's airtime,
    #: covering timestamp granularity and MPDU delimiter overhead.
    SLACK_US = 24

    def __init__(self, slack_us=None):
        self.current = None
        self.completed = 0
        self.slack_us = self.SLACK_US if slack_us is None else slack_us
        self._last_ts = None
        self._last_addr = None
        self._last_airtime = 0.0

    def feed(self, d, frame_len, addr2=None):
        phy = d.get("phy") or {}
        rate = phy.get("rate_mbps")
        mode = phy.get("mode")
        ts = d.get("timestamp")
        is_ampdu = not d.get("non_ampdu", True)

        own_airtime = 0.0
        if rate:
            own_airtime = (_mpdu_bytes_on_air(frame_len) * 8) / rate

        out = []
        if not is_ampdu or ts is None:
            out.extend(self._close())
            single = Aggregate(ts, mode, rate, False)
            single.add(frame_len)
            self.completed += 1
            out.append(single)
            self._reset_last(ts, addr2, own_airtime)
            return out

        contiguous = (
            self.current is not None
            and addr2 is not None
            and addr2 == self._last_addr
            and self._last_ts is not None
            and 0 <= (ts - self._last_ts) <= self._last_airtime + self.slack_us
        )
        if contiguous:
            self.current.add(frame_len)
        else:
            out.extend(self._close())
            self.current = Aggregate(ts, mode, rate, True)
            self.current.add(frame_len)
        self._reset_last(ts, addr2, own_airtime)
        return out

    def _reset_last(self, ts, addr2, airtime):
        self._last_ts = ts
        self._last_addr = addr2
        self._last_airtime = airtime

    def _close(self):
        cur, self.current = self.current, None
        if cur:
            self.completed += 1
            return [cur]
        return []

    def flush(self):
        return self._close()


# ---------------------------------------------------------------------------
# Ubiquiti vendor element (OUI 00:15:6d)
#
# UniFi APs publish their own identity in beacons. Structure, read off the air:
#
#   00156d <subtype> then TLVs of (tag, len, value)
#     subtype 0x01  the rest of the element is the AP name in ASCII
#     subtype 0x00  TLVs, of which:
#       tag 0x81 len 6   the AP's base MAC, shared by every BSSID on that AP
#       tag 0x89 len 36  the controller site UUID, in ASCII
#
# The base MAC is the useful one: it collapses the four or five BSSIDs a
# multi-SSID AP advertises down to one physical radio, which is exactly the
# BSSID-to-AP mapping a survey otherwise has to fetch from the controller.
# ---------------------------------------------------------------------------

UBNT_OUI = b"\x00\x15\x6d"
UBNT_TAG_AP_MAC = 0x81
UBNT_TAG_SITE_UUID = 0x89


def parse_ubnt(ie_list):
    """Extract UniFi AP identity from a beacon's vendor elements."""
    out = {}
    for eid, v in ie_list:
        if eid != 221 or len(v) < 4 or v[:3] != UBNT_OUI:
            continue
        subtype = v[3]
        body = v[4:]
        if subtype == 0x01:
            name = body.split(b"\x00")[0]
            if name:
                out["ap_name"] = name.decode("ascii", "replace")
            continue
        if subtype != 0x00:
            continue
        i = 0
        while i + 2 <= len(body):
            tag, tlen = body[i], body[i + 1]
            i += 2
            if i + tlen > len(body):
                break
            val = body[i : i + tlen]
            if tag == UBNT_TAG_AP_MAC and tlen == 6:
                out["ap_mac"] = mac(val)
            elif tag == UBNT_TAG_SITE_UUID:
                out["site_uuid"] = val.decode("ascii", "replace")
            i += tlen
    return out
