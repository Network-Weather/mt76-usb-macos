# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Offline tests for firmware parsing and USB/MCU framing."""

import struct
from importlib.metadata import version

import pytest

import mt7921u as m


def test_module_and_distribution_versions_match():
    assert m.__version__ == version("mt7921u-macos") == "0.1.0"


class RecordingMcu(m.Mt7921uMcu):
    """MCU transport with USB replaced by an in-memory recording."""

    def __init__(self):
        super().__init__()
        self.writes = []
        self.waits = []

    def bulk_out(self, ep, data, timeout=1000):
        self.writes.append((ep, data, timeout))
        return len(data)

    def mcu_wait(self, seq, cid, timeout=3000):
        self.waits.append((seq, cid, timeout))
        return b"reply"


def test_sequence_wraps_without_using_zero():
    dev = m.Mt7921uMcu()
    dev.msg_seq = 14

    assert dev._next_seq() == 15
    assert dev._next_seq() == 1


def test_mcu_command_framing_and_response_wait():
    dev = RecordingMcu()

    assert dev.mcu_send(0x44, b"abc") == b"reply"

    ep, frame, timeout = dev.writes[0]
    assert ep == m.EP_OUT_INBAND_CMD
    assert timeout == 3000
    assert struct.unpack_from("<I", frame)[0] == m.MCU_TXD_LEN + 3
    assert len(frame) % 4 == 0
    assert len(frame) >= 4 + m.MCU_TXD_LEN + 3 + 4
    assert frame[4 + 36] == 0x44
    assert frame[4 + 39] == 1
    assert dev.waits == [(1, 0x44, 3000)]


def test_firmware_scatter_uses_data_endpoint_without_txd():
    dev = RecordingMcu()

    assert dev.mcu_send(m.MCU_CMD_FW_SCATTER, b"payload", wait=False) is None

    ep, frame, _ = dev.writes[0]
    assert ep == m.EP_OUT_AC_BE
    assert struct.unpack_from("<I", frame)[0] == len(b"payload")
    assert frame[4:11] == b"payload"
    assert not dev.waits


def test_patch_parser_decodes_header_and_section():
    blob = bytearray(m.PATCH_HDR_LEN + m.PATCH_SEC_LEN + 48)
    blob[0:8] = b"20260831"
    blob[16:20] = b"MT79"
    struct.pack_into(">IIH", blob, 20, 0x10203, 7, 0xCAFE)
    struct.pack_into(">IIIII", blob, 32, 9, 10, 11, 1, 12)
    struct.pack_into(">IIIIIII", blob, m.PATCH_HDR_LEN, 2, 160, 64, 0x900000, 48, 3, 4)

    parsed = m.parse_patch(bytes(blob))

    assert parsed["build_date"] == "20260831"
    assert parsed["platform"] == "MT79"
    assert parsed["n_region"] == 1
    assert parsed["sections"] == [
        {
            "type": 2,
            "offs": 160,
            "size": 64,
            "addr": 0x900000,
            "len": 48,
            "sec_key_idx": 3,
            "align_len": 4,
        }
    ]


def test_ram_parser_decodes_region_and_trailer():
    blob = bytearray(0x2000 + m.FW_REGION_LEN + m.FW_TRAILER_LEN)
    region = 0x2000
    trailer = region + m.FW_REGION_LEN
    struct.pack_into("<III", blob, region, 1, 2, 3)
    struct.pack_into("<II", blob, region + 16, 0x100000, 0x2000)
    struct.pack_into("<BB", blob, region + 24, 0x21, 4)
    struct.pack_into("<BBBBB", blob, trailer, 0x61, 2, 1, 3, 4)
    blob[trailer + 7 : trailer + 12] = b"1.2.3"
    blob[trailer + 17 : trailer + 25] = b"20260831"
    struct.pack_into("<I", blob, trailer + 32, 0x12345678)

    parsed = m.parse_ram(bytes(blob))

    assert parsed["chip_id"] == 0x61
    assert parsed["fw_ver"] == "1.2.3"
    assert parsed["n_region"] == 1
    assert parsed["regions"][0]["addr"] == 0x100000
    assert parsed["regions"][0]["len"] == 0x2000
    assert parsed["regions"][0]["feature_set"] == 0x21


@pytest.mark.parametrize(
    ("parser", "size"),
    [
        (m.parse_patch, m.PATCH_HDR_LEN - 1),
        (m.parse_ram, m.FW_TRAILER_LEN - 1),
    ],
)
def test_firmware_parsers_reject_truncated_images(parser, size):
    with pytest.raises(ValueError, match="shorter"):
        parser(b"\0" * size)


def test_patch_parser_rejects_section_outside_image():
    blob = bytearray(m.PATCH_HDR_LEN + m.PATCH_SEC_LEN)
    struct.pack_into(">I", blob, 44, 1)  # n_region
    struct.pack_into(">IIIIIII", blob, m.PATCH_HDR_LEN, 2, len(blob) - 2, 8, 0, 8, 0, 0)

    with pytest.raises(ValueError, match="payload"):
        m.parse_patch(bytes(blob))


def test_ram_parser_rejects_declared_regions_outside_image():
    blob = bytearray(4 + m.FW_REGION_LEN + m.FW_TRAILER_LEN)
    region = 4
    trailer = region + m.FW_REGION_LEN
    struct.pack_into("<II", blob, region + 16, 0x100000, 5)
    struct.pack_into("<BBBBB", blob, trailer, 0x61, 2, 1, 3, 4)

    with pytest.raises(ValueError, match="declare"):
        m.parse_ram(bytes(blob))


def test_probe_request_has_expected_addresses_and_elements():
    src = bytes.fromhex("001122334455")

    frame = m.build_probe_request(src, b"lab", seq=0xABC)

    assert struct.unpack_from("<H", frame)[0] == 0x0040
    assert frame[4:10] == b"\xff" * 6
    assert frame[10:16] == src
    assert frame[16:22] == b"\xff" * 6
    assert struct.unpack_from("<H", frame, 22)[0] == 0xABC0
    assert frame[24:29] == b"\x00\x03lab"


def test_probe_request_rejects_invalid_mac_and_ssid():
    with pytest.raises(ValueError, match="6 bytes"):
        m.build_probe_request(b"short")
    with pytest.raises(ValueError, match="32 bytes"):
        m.build_probe_request(b"\0" * 6, b"x" * 33)


def test_txwi_requires_a_complete_80211_header():
    dev = m.Mt7921uDevice()

    with pytest.raises(ValueError, match="24-byte"):
        dev._build_txwi(b"\0" * 23)


class QueuedRxMcu(m.Mt7921uMcu):
    """MCU transport whose RX endpoint replays a fixed queue of transfers."""

    def __init__(self, transfers):
        super().__init__()
        self.evt_ep4 = True
        self.queue = list(transfers)

    def bulk_in(self, ep, length, timeout=1000):
        assert ep == m.EP_IN_PKT_RX
        return self.queue.pop(0)


def rx_event(seq: int) -> bytes:
    raw = bytearray(m.MCU_RXD_LEN + 4)
    struct.pack_into("<I", raw, 0, m.PKT_TYPE_RX_EVENT << 27)
    raw[m.RXD_SEQ_OFFSET] = seq
    return bytes(raw)


def rx_frame() -> bytes:
    # Packet type 0 in rxd0 bits 27..31: an ordinary received 802.11 frame.
    return bytes(m.MCU_RXD_LEN + 4)


def test_mcu_wait_counts_frames_and_stale_events_it_discards():
    dev = QueuedRxMcu([rx_frame(), rx_frame(), rx_event(3), rx_frame(), rx_event(7)])

    assert dev.mcu_wait(seq=7, cid=0x44) == rx_event(7)
    assert dev.mcu_wait_dropped_frames == 3
    assert dev.mcu_wait_stale_events == 1
    assert dev.queue == []
