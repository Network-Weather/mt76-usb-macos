"""Multi-Link element decode, the addresses an MLO client shows on each link.

Byte layouts are those of Linux include/linux/ieee80211.h at v6.12
(IEEE80211_ML_CONTROL_*, IEEE80211_MLC_BASIC_PRES_*, IEEE80211_MLE_STA_CONTROL_*,
ieee80211_mle_common_size(), ieee80211_mle_basic_sta_prof_size_ok()).

Every fixture built here was dissected with tshark 4.x and its fields compared
field by field with this decoder's output on 2026-09-03; the builders below are
the same ones that produced those frames.
"""

import struct

import rxd

MLD_MAC = bytes.fromhex("020000000001")
BSSID = bytes.fromhex("0200000000aa")


def per_sta_profile(link_id: int, sta_mac: bytes | None, pad: int = 0) -> bytes:
    """One Per-STA Profile subelement (id 0)."""
    control = link_id & rxd.MLE_STA_CONTROL_LINK_ID
    control |= rxd.MLE_STA_CONTROL_COMPLETE_PROFILE
    sta_info = b""
    if sta_mac is not None:
        control |= rxd.MLE_STA_CONTROL_STA_MAC_PRESENT
        sta_info = sta_mac
    # STA Info Length counts itself.
    body = struct.pack("<H", control) + bytes([1 + len(sta_info)]) + sta_info
    if pad:
        body += bytes([0, pad]) + b"A" * pad
    return bytes([0, len(body)]) + body


def basic_ml_payload(links, link_id=None, mld_capabilities=None, mld_mac=MLD_MAC) -> bytes:
    """The Multi-Link element payload after the element-id-extension octet."""
    control = rxd.ML_TYPE_BASIC
    presence = b""
    if link_id is not None:
        control |= 0x0010
        presence += bytes([link_id])
    if mld_capabilities is not None:
        control |= 0x0100
        presence += struct.pack("<H", mld_capabilities)
    common_body = mld_mac + presence
    common = bytes([1 + len(common_body)]) + common_body  # Common Info Length counts itself
    link_info = b"".join(per_sta_profile(lid, mac, pad) for lid, mac, pad in links)
    return struct.pack("<H", control) + common + link_info


def element_chain(ext_id: int, payload: bytes) -> bytes:
    """Element 255 plus Fragment (242) continuations for a payload over 255 octets."""
    body = bytes([ext_id]) + payload
    if len(body) <= 255:
        return bytes([255, len(body)]) + body
    out = bytes([255, 255]) + body[:255]
    rest = body[255:]
    while rest:
        chunk, rest = rest[:255], rest[255:]
        out += bytes([242, len(chunk)]) + chunk
    return out


def reassoc_req(sta_addr: bytes, ies: bytes) -> bytes:
    """Reassociation Request: 24-byte header then capability, listen interval, current AP."""
    header = struct.pack("<H", 2 << 4) + b"\x00\x00" + BSSID + sta_addr + BSSID + b"\x00\x00"
    fixed = struct.pack("<HH", 0x0431, 10) + BSSID
    return header + fixed + ies


def test_basic_multi_link_reports_mld_and_every_link_address():
    links = [(0, bytes.fromhex("020000000011"), 0), (1, bytes.fromhex("020000000012"), 0)]
    element = element_chain(rxd.EXT_EID_MULTI_LINK, basic_ml_payload(links, link_id=0))
    parsed = rxd.parse_80211(reassoc_req(MLD_MAC, element))

    multi_link = parsed["multi_link"]
    assert multi_link["type_name"] == "basic"
    assert multi_link["mld_mac"] == "02:00:00:00:00:01"
    assert multi_link["link_id"] == 0
    assert multi_link["truncated"] is False
    assert [link["link_id"] for link in multi_link["links"]] == [0, 1]
    assert [link["sta_mac"] for link in multi_link["links"]] == [
        "02:00:00:00:00:11",
        "02:00:00:00:00:12",
    ]


def test_optional_common_info_subfields_are_read_in_presence_order():
    element = element_chain(
        rxd.EXT_EID_MULTI_LINK,
        basic_ml_payload([], link_id=3, mld_capabilities=0x0003),
    )
    multi_link = rxd.parse_80211(reassoc_req(MLD_MAC, element))["multi_link"]

    assert multi_link["link_id"] == 3
    assert multi_link["mld_capabilities"] == 3
    assert multi_link["links"] == []


def test_station_addresses_covers_every_address_the_client_answers_to():
    links = [(0, bytes.fromhex("020000000011"), 0), (1, bytes.fromhex("020000000012"), 0)]
    element = element_chain(rxd.EXT_EID_MULTI_LINK, basic_ml_payload(links))
    parsed = rxd.parse_80211(reassoc_req(MLD_MAC, element))

    addresses = rxd.station_addresses(parsed)
    assert addresses == {
        "02:00:00:00:00:01",  # MLD address, the one addr2 carries
        "02:00:00:00:00:11",  # link 0, seen on that link's data frames
        "02:00:00:00:00:12",  # link 1
    }


def test_station_addresses_never_includes_the_receiver_or_the_bssid():
    # The AP is addr1 and addr3 of this frame. Folding either into the client's
    # identity would make a watcher treat every AP frame as the client's.
    element = element_chain(rxd.EXT_EID_MULTI_LINK, basic_ml_payload([]))
    addresses = rxd.station_addresses(rxd.parse_80211(reassoc_req(MLD_MAC, element)))
    assert "02:00:00:00:00:aa" not in addresses


def test_station_addresses_without_a_multi_link_element_is_the_transmitter():
    parsed = rxd.parse_80211(reassoc_req(MLD_MAC, bytes([0, 4]) + b"TEST"))
    assert "multi_link" not in parsed
    assert rxd.station_addresses(parsed) == {"02:00:00:00:00:01"}


def test_element_fragments_are_joined_before_the_link_info_is_walked():
    # 90 octets of padding per profile pushes the element past 255 octets, so a
    # decoder that reads only element 255 would lose the later links.
    links = [(index, bytes.fromhex("0200000000") + bytes([0x20 + index]), 90) for index in range(3)]
    payload = basic_ml_payload(links)
    element = element_chain(rxd.EXT_EID_MULTI_LINK, payload)
    assert element[0] == 255
    assert element[1] == 255  # a full first part
    assert 242 in element  # continued in at least one Fragment element

    multi_link = rxd.parse_80211(reassoc_req(MLD_MAC, element))["multi_link"]
    assert multi_link["truncated"] is False
    assert [link["sta_mac"] for link in multi_link["links"]] == [
        "02:00:00:00:00:20",
        "02:00:00:00:00:21",
        "02:00:00:00:00:22",
    ]


def test_subelement_fragments_are_joined():
    # A single Per-STA Profile longer than 255 octets continues in subelement 254.
    profile = per_sta_profile(5, bytes.fromhex("020000000033"))[2:]
    profile += bytes([0, 250]) + b"B" * 250
    first, rest = profile[:255], profile[255:]
    link_info = bytes([0, 255]) + first + bytes([rxd.ML_SUBELEM_FRAGMENT, len(rest)]) + rest
    common = bytes([1 + 6]) + MLD_MAC
    payload = struct.pack("<H", rxd.ML_TYPE_BASIC) + common + link_info

    multi_link = rxd.parse_80211(reassoc_req(MLD_MAC, element_chain(107, payload)))["multi_link"]
    assert multi_link["truncated"] is False
    assert multi_link["links"] == [
        {"link_id": 5, "complete_profile": True, "sta_mac": "02:00:00:00:00:33"}
    ]


def test_a_profile_without_the_mac_present_bit_reports_no_address():
    element = element_chain(rxd.EXT_EID_MULTI_LINK, basic_ml_payload([(2, None, 0)]))
    multi_link = rxd.parse_80211(reassoc_req(MLD_MAC, element))["multi_link"]

    assert multi_link["links"] == [{"link_id": 2, "complete_profile": True}]
    assert rxd.station_addresses(rxd.parse_80211(reassoc_req(MLD_MAC, element))) == {
        "02:00:00:00:00:01"
    }


def test_a_truncated_common_info_is_reported_not_guessed():
    # Presence bit for MLD Capabilities set, but the two octets are absent.
    control = rxd.ML_TYPE_BASIC | 0x0100
    common = bytes([1 + 6]) + MLD_MAC
    payload = struct.pack("<H", control) + common
    multi_link = rxd.parse_80211(reassoc_req(MLD_MAC, element_chain(107, payload)))["multi_link"]

    assert multi_link["truncated"] is True
    assert "mld_capabilities" not in multi_link


def test_a_short_element_yields_no_addresses_and_does_not_raise():
    for payload in (b"", b"\x00", b"\x00\x00"):
        parsed = rxd.parse_80211(reassoc_req(MLD_MAC, element_chain(107, payload)))
        multi_link = parsed.get("multi_link")
        if multi_link is not None:
            assert multi_link["links"] == []


def test_other_multi_link_types_are_named_but_not_read_as_basic():
    payload = struct.pack("<H", rxd.ML_TYPE_PROBE_REQ) + bytes([1])
    multi_link = rxd.parse_80211(reassoc_req(MLD_MAC, element_chain(107, payload)))["multi_link"]

    assert multi_link["type_name"] == "probe-request"
    assert "mld_mac" not in multi_link


def test_roaming_event_detail_carries_the_link_addresses():
    links = [(0, bytes.fromhex("020000000011"), 0)]
    element = element_chain(rxd.EXT_EID_MULTI_LINK, basic_ml_payload(links))
    parsed = rxd.parse_80211(reassoc_req(MLD_MAC, element))

    name, detail = rxd.management_event(parsed)
    assert name == "reassoc_req"
    assert detail["multi_link"]["links"][0]["sta_mac"] == "02:00:00:00:00:11"


def test_a_tdls_element_reports_the_access_points_address_as_the_access_points():
    # ieee80211_mle_tdls_common_info: len(1) then ap_mld_mac_addr(6). Treating that as
    # the transmitter's MLD address would fold an access point into a client's identity.
    ap_mld = bytes.fromhex("0200000000cc")
    payload = struct.pack("<H", rxd.ML_TYPE_TDLS) + bytes([1 + 6]) + ap_mld
    parsed = rxd.parse_80211(reassoc_req(MLD_MAC, element_chain(107, payload)))

    multi_link = parsed["multi_link"]
    assert multi_link["type_name"] == "tdls"
    assert multi_link["ap_mld_mac"] == "02:00:00:00:00:cc"
    assert "mld_mac" not in multi_link
    assert rxd.station_addresses(parsed) == {"02:00:00:00:00:01"}
