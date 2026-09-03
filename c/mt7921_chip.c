/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#include "mt7921_chip.h"
#include "mt7921_regs.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

/* mt7921/usb.c mt7921u_device_table and mt7925/usb.c mt7925u_device_table at c5a3bd91,
 * minus the MT7927 id (0e8d:6639), whose firmware is not fetched here. Same table as
 * mt7921u.SUPPORTED_DEVICES. */
static const mt7921_supported_device_t SUPPORTED[] = {
    { 0x0E8D, 0x7961, MT_CHIP_MT7921, "MT7921AU reference (ALFA AWUS036AXML)" },
    { 0x0E8D, 0x7925, MT_CHIP_MT7925, "MediaTek MT7925" },
    { 0x0846, 0x9050, MT_CHIP_MT7925, "Netgear Nighthawk A8500" },
    { 0x0846, 0x9072, MT_CHIP_MT7925, "Netgear Nighthawk A9000" },
};

static const mt7921_chip_profile_t PROFILES[MT_CHIP_COUNT] = {
    [MT_CHIP_MT7921] = {
        .chip = MT_CHIP_MT7921,
        .name = "mt7921",
        .chip_id = MT_CHIP_ID_7961,
        .txd1 = MCU_TXD1_CONNAC2,
        .mcu_rxd_len = MCU_RXD_LEN,
        .rxd_seq_offset = RXD_SEQ_OFFSET,
        .rxd_status_offset = RXD_STATUS_OFFSET,
        /* mt7921_wfsys_desc: BIT(22) of the UDMA status word after selecting page 0 */
        .wfsys_rst_reg = MT_CBTOP_RGU_WF_SUBSYS_RST,
        .wfsys_done_reg = MT_UDMA_CONN_INFRA_STATUS,
        .wfsys_done_mask = MT_UDMA_CONN_WFSYS_INIT_DONE,
        .wfsys_done_val = MT_UDMA_CONN_WFSYS_INIT_DONE,
        .wfsys_delay_us = 1000,
        .wfsys_need_status_sel = true,
        .patch_file = "WIFI_MT7961_patch_mcu_1_2_hdr.bin",
        .patch_sha256 = "a276c06c2b772adb50b86639d33c82824ff4c21d617feb78caea74c040b873f6",
        .ram_file = "WIFI_RAM_CODE_MT7961_1.bin",
        .ram_sha256 = "b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9",
    },
    [MT_CHIP_MT7925] = {
        .chip = MT_CHIP_MT7925,
        .name = "mt7925",
        .chip_id = MT_CHIP_ID_7925,
        .txd1 = MCU_TXD1_CONNAC3,
        .mcu_rxd_len = MT7925_MCU_RXD_LEN,
        .rxd_seq_offset = MT7925_RXD_SEQ_OFFSET,
        .rxd_status_offset = MT7925_RXD_STATUS_OFFSET,
        /* mt7925_wfsys_desc: whole-word compare against 0x1d1e, 20 ms settle, no page select */
        .wfsys_rst_reg = MT7925_CBTOP_RGU_WF_SUBSYS_RST,
        .wfsys_done_reg = MT7925_WFSYS_INIT_DONE_ADDR,
        .wfsys_done_mask = 0xFFFFFFFFU,
        .wfsys_done_val = MT7925_WFSYS_INIT_DONE,
        .wfsys_delay_us = 20000,
        .wfsys_need_status_sel = false,
        .patch_file = "mt7925/WIFI_MT7925_PATCH_MCU_1_1_hdr.bin",
        .patch_sha256 = "8eb46014d2a6b4124472eee7476d995008a6f40b1daffef87eb42f30d98699e1",
        .ram_file = "mt7925/WIFI_RAM_CODE_MT7925_1_1.bin",
        .ram_sha256 = "23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120",
    },
};

const mt7921_chip_profile_t *mt7921_chip_profile(mt7921_chip_t chip) {
    if ((unsigned)chip >= MT_CHIP_COUNT) return NULL;
    return &PROFILES[chip];
}

const mt7921_supported_device_t *mt7921_supported_devices(size_t *count) {
    if (count) *count = sizeof(SUPPORTED) / sizeof(SUPPORTED[0]);
    return SUPPORTED;
}

int mt7921_chip_for_usb_id(uint16_t vid, uint16_t pid) {
    for (size_t i = 0; i < sizeof(SUPPORTED) / sizeof(SUPPORTED[0]); i++) {
        if (SUPPORTED[i].vid == vid && SUPPORTED[i].pid == pid) return (int)SUPPORTED[i].chip;
    }
    return -1;
}

int mt7921_parse_usb_id(const char *text, uint16_t *vid, uint16_t *pid) {
    unsigned v, p;
    char tail;
    if (!text || sscanf(text, "%4x:%4x%c", &v, &p, &tail) != 2 || strlen(text) != 9 || text[4] != ':') {
        return -1;
    }
    if (vid) *vid = (uint16_t)v;
    if (pid) *pid = (uint16_t)p;
    return 0;
}

uint8_t mt7921_uni_option(const mt7921_chip_profile_t *prof, uint8_t cid, bool query) {
    if (!prof || prof->chip == MT_CHIP_MT7921) {
        return MCU_CMD_UNI_EXT_ACK; /* mt76_connac2_mcu_fill_message: always EXT_ACK */
    }
    /* mt7925_mcu_fill_message: QUERY_ACK when the command word has the QUERY bit, else
     * EXT_ACK; HIF_CTRL and CHIP_CONFIG clear the ACK bit. */
    uint8_t option = query ? MCU_CMD_UNI_QUERY_ACK : MCU_CMD_UNI_EXT_ACK;
    if (cid == MCU_UNI_CMD_HIF_CTRL || cid == MCU_UNI_CMD_CHIP_CONFIG) {
        option &= (uint8_t)~MCU_CMD_ACK;
    }
    return option;
}
