# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
# Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear).
# See NOTICE.md and RELATED_WORK.md for source lineage, firmware, and peer implementations.
"""Userspace driver for the MediaTek MT7925U (Wi-Fi 7 USB, connac3) over libusb.

Transcribed from the mt76 driver at c5a3bd91: mt7925/usb.c, mt7925/mcu.c, mt7925/mcu.h,
mt792x_usb.c (the mt7925 WFSYS descriptor), and mt76_connac_mcu.h. The USB transport,
DMA init, and firmware-download protocol are the mt792x ones mt7921u.py already
implements, so this module is a subclass that changes what differs:

- WFSYS reset registers and timing (mt7925_wfsys_desc).
- MCU TXD word 1 has no LONG_FORMAT bit; the UNI ack option depends on the command.
- The MCU reply header is 44 bytes (struct mt7925_mcu_rxd has 8 rxd words, not 6).
- NIC capability and efuse buffer mode are UNI commands with tag/length TLVs.
- There is no CHANNEL_SWITCH command; the sniffer CONFIG TLV is the channel command.

Passive receive only. Injection, thermal, and raw efuse reads are not ported.
"""

from __future__ import annotations

import struct

import mt7921u as m

__all__ = ["Mt7925uDevice"]

# mt792x_regs.h: mt7925_wfsys_desc registers (mt792x_usb.c:384-391 at c5a3bd91)
MT7925_CBTOP_RGU_WF_SUBSYS_RST = 0x70028600
MT7925_WFSYS_INIT_DONE_ADDR = 0x184C1604
MT7925_WFSYS_INIT_DONE = 0x00001D1E

# mt7925/mcu.h struct mt7925_mcu_rxd: __le32 rxd[8]; le16 len; le16 pkt_type_id; u8 eid;
# u8 seq; u8 option; u8 rsv; u8 ext_eid; u8 rsv1[2]; u8 s2d_index; u8 tlv[].
MT7925_MCU_RXD_LEN = 44
MT7925_RXD_SEQ_OFFSET = 32 + 2 + 2 + 1  # rxd[8], len, pkt_type_id, eid
MT7925_RXD_STATUS_OFFSET = MT7925_MCU_RXD_LEN - 4  # skb_pull(sizeof(*rxd) - 4)

# mt7925_mcu_fill_message: txd[1] = FIELD_PREP(MT_TXD1_HDR_FORMAT, MT_HDR_FORMAT_CMD) with
# MT_TXD1_HDR_FORMAT GENMASK(15, 14) in mt76_connac3_mac.h. No LONG_FORMAT bit exists.
MT7925_TXD1_HDR_FORMAT_SHIFT = 14
MT7925_TXD1 = m.MT_HDR_FORMAT_CMD << MT7925_TXD1_HDR_FORMAT_SHIFT

# mt76_connac_mcu.h
MCU_CMD_UNI_QUERY_ACK = m.MCU_CMD_ACK | m.MCU_CMD_UNI
MCU_UNI_CMD_HIF_CTRL = 0x07
MCU_UNI_CMD_BAND_CONFIG = 0x08
MCU_UNI_CMD_CHIP_CONFIG = 0x0E
MCU_UNI_CMD_EFUSE_CTRL = 0x2D
# mt7925/mcu.h tag enums
UNI_CHIP_CONFIG_NIC_CAPA = 0x3
UNI_EFUSE_BUFFER_MODE = 0x2

# mt7925_mcu_parse_response returns event->status for these UNI commands; every other
# reply is success once its sequence number matched.
UNI_STATUS_CIDS = (
    0x01,
    0x02,
    0x03,
    0x06,
    0x05,
    0x56,
)  # DEV_INFO, BSS_INFO, STA_REC, OFFLOAD, SUSPEND, NAN

# struct mt7925_mcu_phy_cap (mt7925/mcu.h), 13 bytes, parsed by mt7925_mcu_parse_phy_cap
PHY_CAP_FIELDS = (
    "ht",
    "vht",
    "_5g",
    "max_bw",
    "nss",
    "dbdc",
    "tx_ldpc",
    "rx_ldpc",
    "tx_stbc",
    "rx_stbc",
    "hw_path",
    "he",
    "eht",
)
HW_PATH_WF0_24G = 1 << 0
HW_PATH_WF0_5G = 1 << 1


def uni_tlv_request(tag: int, body: bytes) -> bytes:
    """[4 reserved][le16 tag][le16 len][body] as the mt7925 UNI requests are laid out.

    len covers tag, len, and body (sizeof(req) - 4 in the driver structs).
    """
    return struct.pack("<4xHH", tag, 4 + len(body)) + body


def parse_nic_capability(body: bytes) -> dict:
    """mt7925_mcu_get_nic_capability's reply: struct mt76_connac_cap_hdr then n_element
    TLVs of {le16 tag, le16 len, data}, where len includes the 4-byte TLV header."""
    if len(body) < 4:
        raise m.McuError(f"capability response too short ({len(body)} bytes)")
    (n_element,) = struct.unpack_from("<H", body, 0)
    off = 4
    caps: dict[int, bytes] = {}
    for _ in range(n_element):
        if off + 4 > len(body):
            break
        tag, tlen = struct.unpack_from("<HH", body, off)
        if tlen < 4 or off + tlen > len(body):
            break
        caps[tag] = body[off + 4 : off + tlen]
        off += tlen
    return caps


def parse_phy_cap(data: bytes) -> dict:
    """mt7925_mcu_parse_phy_cap. Returns the struct fields plus derived antenna_mask."""
    if len(data) < len(PHY_CAP_FIELDS):
        raise m.McuError(f"PHY capability element too short ({len(data)} bytes)")
    out = dict(zip(PHY_CAP_FIELDS, data[: len(PHY_CAP_FIELDS)], strict=True))
    out["antenna_mask"] = (1 << out["nss"]) - 1
    out["has_2ghz"] = bool(out["hw_path"] & HW_PATH_WF0_24G)
    out["has_5ghz"] = bool(out["hw_path"] & HW_PATH_WF0_5G)
    return out


class Mt7925uDevice(m.Mt7921uDevice):
    """MT7925U passive capture device. See the module docstring for what differs."""

    CHIP = m.CHIP_MT7925
    CHIP_IDS = (0x7925,)  # 0x6639 (MT7927) needs the mt7927/ blobs and is refused

    TXD1 = MT7925_TXD1
    MCU_RXD_LEN = MT7925_MCU_RXD_LEN
    RXD_SEQ_OFFSET = MT7925_RXD_SEQ_OFFSET
    RXD_STATUS_OFFSET = MT7925_RXD_STATUS_OFFSET

    # mt7925_wfsys_desc: whole-word compare against 0x1d1e, 20 ms settle, no status select.
    WFSYS_RST_REG = MT7925_CBTOP_RGU_WF_SUBSYS_RST
    WFSYS_DONE_REG = MT7925_WFSYS_INIT_DONE_ADDR
    WFSYS_DONE_MASK = 0xFFFFFFFF
    WFSYS_DONE_VAL = MT7925_WFSYS_INIT_DONE
    WFSYS_RST_DELAY_S = 0.020
    WFSYS_NEED_STATUS_SEL = False

    def __init__(self, verbose: bool = False, usb_id: str | None = None):
        super().__init__(verbose=verbose, usb_id=usb_id)
        self.nic_caps: dict[int, bytes] = {}
        self.phy_cap: dict | None = None

    # ---- MCU framing ---------------------------------------------------

    def uni_option(self, cid: int, query: bool = False) -> int:
        """mt7925_mcu_fill_message: QUERY_ACK for query commands, else EXT_ACK; HIF_CTRL
        and CHIP_CONFIG drop the ACK bit."""
        option = MCU_CMD_UNI_QUERY_ACK if query else m.MCU_CMD_UNI_EXT_ACK
        if cid in (MCU_UNI_CMD_HIF_CTRL, MCU_UNI_CMD_CHIP_CONFIG):
            option &= ~m.MCU_CMD_ACK
        return option

    def uni_status(self, cid: int, rxd: bytes) -> int | None:
        """event->status for the UNI commands whose reply carries one (cid at +0, le32
        status at +4 after the header), else None."""
        if cid not in UNI_STATUS_CIDS:
            return None
        body = self.reply_body(rxd)
        if len(body) < 8:
            raise m.McuError(f"UNI event for cid 0x{cid:02x} too short ({len(body)} bytes)")
        event_cid = body[0]
        (status,) = struct.unpack_from("<I", body, 4)
        if event_cid != cid:
            raise m.McuError(f"UNI event cid 0x{event_cid:02x} does not match 0x{cid:02x}")
        return status

    # ---- post-firmware init (mt7925_run_firmware, __mt7925_init_hardware) ----

    def get_nic_capability(self) -> dict:
        """mt7925_mcu_get_nic_capability: MCU_UNI_CMD(CHIP_CONFIG) tag NIC_CAPA."""
        req = uni_tlv_request(UNI_CHIP_CONFIG_NIC_CAPA, b"")
        rxd = self.mcu_uni(MCU_UNI_CMD_CHIP_CONFIG, req)
        self.nic_caps = parse_nic_capability(self.reply_body(rxd))
        phy = self.nic_caps.get(0x08)  # MT_NIC_CAP_PHY
        self.phy_cap = parse_phy_cap(phy) if phy else None
        return self.nic_caps

    def set_eeprom(self) -> None:
        """mt7925_mcu_set_eeprom: MCU_UNI_CMD(EFUSE_CTRL) tag BUFFER_MODE, whole efuse."""
        body = struct.pack("<BBH", m.EE_MODE_EFUSE, m.EE_FORMAT_WHOLE, 0)
        self.mcu_uni(MCU_UNI_CMD_EFUSE_CTRL, uni_tlv_request(UNI_EFUSE_BUFFER_MODE, body))

    def post_firmware_init(self, log=print) -> None:
        """mt7925_run_firmware tail and __mt7925_init_hardware: NIC capability, then the
        efuse push. CLC loading is skipped on USB (mt7925_regd_clc_supported)."""
        self.get_nic_capability()
        if self.phy_cap:
            log(
                f"  phy cap: nss={self.phy_cap['nss']} max_bw={self.phy_cap['max_bw']} "
                f"he={self.phy_cap['he']} eht={self.phy_cap['eht']} "
                f"hw_path=0x{self.phy_cap['hw_path']:02x} "
                f"6g={'6G' in self.cap_names()}"
            )
        self.set_eeprom()
        log("efuse pushed")

    def cap_names(self) -> list[str]:
        return [m.NIC_CAP_NAMES.get(tag, f"0x{tag:02x}") for tag in sorted(self.nic_caps)]

    # ---- not ported --------------------------------------------------------

    def set_chan_info(self, *args, **kwargs):
        raise NotImplementedError(
            "MT7925 has no CHANNEL_SWITCH command; config_sniffer() is the channel command"
        )

    def get_temperature(self):
        raise NotImplementedError("MT7925 thermal query is MCU_UNI_CMD(THERMAL) 0x35; not ported")

    def read_efuse(self, offset: int):
        raise NotImplementedError("MT7925 efuse read is UNI EFUSE_CTRL tag 1; not ported")

    def inject(self, *args, **kwargs):
        raise NotImplementedError("transmit is not ported to the MT7925 (connac3 TXD differs)")
