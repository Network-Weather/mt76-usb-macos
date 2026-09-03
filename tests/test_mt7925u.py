# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""MT7925 MCU framing, reply parsing, and reset sequence, offline.

Expected bytes come from mt7925/mcu.c, mt7925/mcu.h, and mt792x_usb.c at c5a3bd91.
"""

import struct

import pytest

import mt7921u as m
import mt7925u as m25


class Recording(m25.Mt7925uDevice):
    """Records bulk-OUT frames and UHW register traffic; replies are scripted."""

    def __init__(self, replies=None):
        super().__init__()
        self.frames = []
        self.uhw = []
        self.regs = {}
        self.replies = list(replies or [])

    def bulk_out(self, ep, data, timeout=1000):
        self.frames.append((ep, bytes(data)))
        return len(data)

    def mcu_wait(self, seq, cid, timeout=3000):
        body = self.replies.pop(0) if self.replies else b""
        reply = bytearray(self.MCU_RXD_LEN)
        struct.pack_into("<I", reply, 0, m.PKT_TYPE_RX_EVENT << 27)
        reply[self.RXD_SEQ_OFFSET] = seq
        return bytes(reply) + body

    # WFSYS reset goes through the UHW vendor pair.
    def uhw_rr(self, addr):
        self.uhw.append(("rr", addr))
        return self.regs.get(addr, 0)

    def uhw_wr(self, addr, val):
        self.uhw.append(("wr", addr, val))
        self.regs[addr] = val

    def wait_udma_idle(self):
        self.uhw.append(("udma_idle",))

    def epctl_rst_opt(self, reset):
        self.uhw.append(("epctl", reset))


def unpad(frame: bytes) -> bytes:
    """Strip the 4-byte USB/SDIO length header and return the TXD + payload."""
    (length,) = struct.unpack_from("<I", frame, 0)
    return frame[4 : 4 + (length & 0xFFFF)]


def test_geometry_constants_match_struct_mt7925_mcu_rxd():
    assert m25.Mt7925uDevice.MCU_RXD_LEN == 44
    assert m25.Mt7925uDevice.RXD_SEQ_OFFSET == 37
    assert m25.Mt7925uDevice.RXD_STATUS_OFFSET == 40
    assert m25.Mt7925uDevice.TXD1 == 0x4000
    # The MT7921 class is untouched by the subclass.
    assert m.Mt7921uDevice.MCU_RXD_LEN == 36
    assert m.Mt7921uDevice.RXD_SEQ_OFFSET == 29
    assert m.Mt7921uDevice.RXD_STATUS_OFFSET == 32
    assert m.Mt7921uDevice.TXD1 == (1 << 31) | (1 << 16)


def test_legacy_txd_drops_long_format():
    dev = Recording()
    dev.msg_seq = 0
    dev.patch_sem_ctrl(True)
    ep, frame = dev.frames[0]
    assert ep == dev.ep_out_inband_cmd
    txd = unpad(frame)
    words = struct.unpack_from("<8I", txd, 0)
    assert words[1] == 0x4000  # HDR_FORMAT_CMD << 14, nothing else
    assert (words[0] >> 25) == m.MT_TX_MCU_PORT_RX_Q0
    assert ((words[0] >> 23) & 0x3) == m.MT_TX_TYPE_CMD
    assert (words[0] & 0xFFFF) == len(txd)
    # struct mt76_connac2_mcu_txd tail: len, pq_id, cid, pkt_type, set_query, seq
    length, _pq, cid, pkt_type, _set_query, seq = struct.unpack_from("<HHBBBB", txd, 32)
    assert length == len(txd) - 32
    assert cid == m.MCU_CMD_PATCH_SEM_CONTROL
    assert pkt_type == m.MCU_PKT_ID
    assert seq == 1


@pytest.mark.parametrize(
    ("cid", "query", "option"),
    [
        (m.MCU_UNI_CMD_SNIFFER, False, 0x7),  # EXT_ACK
        (m25.MCU_UNI_CMD_EFUSE_CTRL, False, 0x7),
        (m25.MCU_UNI_CMD_EFUSE_CTRL, True, 0x3),  # QUERY_ACK
        (m25.MCU_UNI_CMD_CHIP_CONFIG, False, 0x6),  # ACK bit cleared
        (m25.MCU_UNI_CMD_HIF_CTRL, False, 0x6),
        (m25.MCU_UNI_CMD_CHIP_CONFIG, True, 0x2),
    ],
)
def test_uni_option_follows_mt7925_mcu_fill_message(cid, query, option):
    dev = Recording()
    assert dev.uni_option(cid, query) == option
    dev.msg_seq = 0
    dev.mcu_uni(cid, b"\x00" * 4, wait=False, query=query)
    txd = unpad(dev.frames[0][1])
    words = struct.unpack_from("<8I", txd, 0)
    assert words[1] == 0x4000
    # struct mt76_connac2_mcu_uni_txd: len, cid, rsv, pkt_type, frag_n, seq, checksum, s2d, option
    length, tcid, _rsv, pkt_type, _frag, seq, _csum, s2d, topt = struct.unpack_from(
        "<HHBBBBHBB", txd, 32
    )
    assert (length, tcid, pkt_type, seq, s2d, topt) == (
        len(txd) - 32,
        cid,
        m.MCU_PKT_ID,
        1,
        m.MCU_S2D_H2N,
        option,
    )


def test_mt7921_uni_option_is_unchanged():
    dev = m.Mt7921uDevice()
    assert dev.uni_option(m25.MCU_UNI_CMD_CHIP_CONFIG, True) == m.MCU_CMD_UNI_EXT_ACK


def test_set_eeprom_wire_bytes():
    # mt7925_mcu_set_eeprom: rsv[4], tag=UNI_EFUSE_BUFFER_MODE(2), len=8, mode=0, format=1, buf_len=0
    dev = Recording()
    dev.msg_seq = 0
    dev.set_eeprom()
    txd_payload = unpad(dev.frames[0][1])
    payload = txd_payload[m.MCU_UNI_TXD_LEN :]
    assert payload == bytes.fromhex("000000000200080000010000")
    assert struct.unpack_from("<HH", txd_payload, 34)[0] == m25.MCU_UNI_CMD_EFUSE_CTRL


def test_get_nic_capability_request_and_element_parse():
    # Reply body: cap_hdr {n_element=3, rsv[2]} then TLVs whose len includes the header.
    mac = bytes.fromhex("020000000001")
    phy = bytes([1, 1, 1, 3, 2, 0, 1, 1, 1, 1, 0x03, 1, 1])  # nss=2, hw_path=2G|5G, he, eht
    body = struct.pack("<H2x", 3)
    body += struct.pack("<HH", 0x07, 4 + len(mac)) + mac
    body += struct.pack("<HH", 0x08, 4 + len(phy)) + phy
    body += struct.pack("<HH", 0x18, 4 + 4) + bytes([1, 0, 0, 0])  # 6G supported
    dev = Recording(replies=[body])
    dev.msg_seq = 0
    caps = dev.get_nic_capability()

    payload = unpad(dev.frames[0][1])[m.MCU_UNI_TXD_LEN :]
    assert payload == bytes.fromhex("0000000003000400")  # rsv, tag=3, len=4
    assert struct.unpack_from("<HH", unpad(dev.frames[0][1]), 34)[0] == m25.MCU_UNI_CMD_CHIP_CONFIG

    assert caps[0x07] == mac
    assert caps[0x18] == bytes([1, 0, 0, 0])
    assert dev.phy_cap["nss"] == 2
    assert dev.phy_cap["antenna_mask"] == 0x3
    assert dev.phy_cap["has_2ghz"] is True
    assert dev.phy_cap["has_5ghz"] is True
    assert dev.phy_cap["eht"] == 1
    assert "6G" in dev.cap_names()


def test_nic_capability_parse_is_bounds_checked():
    truncated = struct.pack("<H2x", 2) + struct.pack("<HH", 0x08, 40) + b"\x00" * 5
    assert m25.parse_nic_capability(truncated) == {}
    with pytest.raises(m.McuError):
        m25.parse_nic_capability(b"\x00")
    with pytest.raises(m.McuError):
        m25.parse_phy_cap(b"\x00" * 5)


def test_status_byte_is_read_at_offset_40():
    dev = Recording()
    reply = bytearray(44 + 4)
    reply[40] = m.PATCH_NOT_DL_SEM_SUCCESS
    assert dev._status_byte(bytes(reply)) == m.PATCH_NOT_DL_SEM_SUCCESS
    assert dev.reply_body(bytes(reply)) == b"\x00" * 4


def test_uni_status_for_event_carrying_commands():
    dev = Recording()
    header = bytes(44)
    ok = header + bytes([0x02, 0, 0, 0]) + struct.pack("<I", 0)
    assert dev.uni_status(0x02, ok) == 0
    bad = header + bytes([0x02, 0, 0, 0]) + struct.pack("<I", 7)
    assert dev.uni_status(0x02, bad) == 7
    assert dev.uni_status(m.MCU_UNI_CMD_SNIFFER, header) is None
    with pytest.raises(m.McuError):
        dev.uni_status(0x02, header + bytes([0x03, 0, 0, 0]) + struct.pack("<I", 0))


def test_mcu_wait_matches_seq_at_offset_37(monkeypatch):
    class Queued(m25.Mt7925uDevice):
        def __init__(self, transfers):
            super().__init__()
            self.evt_ep4 = True
            self.transfers = list(transfers)

        def bulk_in(self, ep, length, timeout=1000):
            assert ep == self.ep_in_pkt_rx
            return self.transfers.pop(0)

    def event(seq):
        raw = bytearray(44 + 8)
        struct.pack_into("<I", raw, 0, m.PKT_TYPE_RX_EVENT << 27)
        raw[37] = seq
        return bytes(raw)

    def frame():
        raw = bytearray(64)
        struct.pack_into("<I", raw, 0, m.PKT_TYPE_NORMAL << 27)
        return bytes(raw)

    dev = Queued([frame(), event(3), event(5)])
    got = dev.mcu_wait(5, 0x24)
    assert got[37] == 5
    assert dev.mcu_wait_dropped_frames == 1
    assert dev.mcu_wait_stale_events == 1


def test_wfsys_reset_uses_the_mt7925_descriptor():
    dev = Recording()
    dev.regs[m25.MT7925_WFSYS_INIT_DONE_ADDR] = m25.MT7925_WFSYS_INIT_DONE
    dev.regs[m25.MT7925_CBTOP_RGU_WF_SUBSYS_RST] = 0x10
    dev.wfsys_reset()
    assert dev.uhw == [
        ("udma_idle",),
        ("epctl", False),
        ("rr", 0x70028600),
        ("wr", 0x70028600, 0x11),
        ("rr", 0x70028600),
        ("wr", 0x70028600, 0x10),
        ("rr", 0x184C1604),
    ]
    assert dev.WFSYS_RST_DELAY_S == 0.020


def test_wfsys_reset_requires_the_whole_done_word():
    dev = Recording()
    dev.regs[m25.MT7925_WFSYS_INIT_DONE_ADDR] = 0x00001D1F  # one bit off
    with pytest.raises(RuntimeError, match="WFSYS"):
        dev.wfsys_reset()


def test_mt7921_wfsys_descriptor_is_unchanged():
    assert m.Mt7921uDevice.WFSYS_RST_REG == 0x70002600
    assert m.Mt7921uDevice.WFSYS_DONE_REG == m.MT_UDMA_CONN_INFRA_STATUS
    assert m.Mt7921uDevice.WFSYS_DONE_MASK == 1 << 22
    assert m.Mt7921uDevice.WFSYS_NEED_STATUS_SEL is True


def test_unported_operations_refuse_loudly():
    dev = m25.Mt7925uDevice()
    for call in (
        lambda: dev.set_chan_info(control_ch=1, center_ch=1, bw=0, band=0),
        dev.get_temperature,
        lambda: dev.read_efuse(0),
        lambda: dev.inject(b"", 0),
    ):
        with pytest.raises(NotImplementedError):
            call()


def test_device_class_for_each_chip():
    assert m.device_class_for(m.CHIP_MT7921) is m.Mt7921uDevice
    assert m.device_class_for(m.CHIP_MT7925) is m25.Mt7925uDevice
    with pytest.raises(m.UnsupportedDevice):
        m.device_class_for("mt7663")


def test_firmware_files_for_mt7925_are_the_mt7925_blobs():
    (patch, _), (ram, _) = m.FIRMWARE_FILES[m25.Mt7925uDevice.CHIP]
    assert patch == "mt7925/WIFI_MT7925_PATCH_MCU_1_1_hdr.bin"
    assert ram == "mt7925/WIFI_RAM_CODE_MT7925_1_1.bin"
