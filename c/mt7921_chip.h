/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#ifndef MT7921_CHIP_H
#define MT7921_CHIP_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* Which mt792x USB chip a device is; selects MCU geometry, reset registers, command
 * encodings, firmware files, and the RX descriptor decoder. Mirrors mt7921u.SUPPORTED_DEVICES
 * and the class attributes on Mt7921uMcu / Mt7925uDevice in the Python reference. */
typedef enum {
    MT_CHIP_MT7921 = 0,
    MT_CHIP_MT7925 = 1,
    MT_CHIP_COUNT
} mt7921_chip_t;

typedef struct {
    uint16_t vid;
    uint16_t pid;
    mt7921_chip_t chip;
    const char *note;
} mt7921_supported_device_t;

typedef struct {
    mt7921_chip_t chip;
    const char *name;            /* "mt7921" / "mt7925", as the Python and JSON name them */
    uint16_t chip_id;            /* expected rr(MT_HW_CHIPID) & 0xFFFF */
    uint32_t txd1;               /* MCU TXD word 1 */
    uint32_t mcu_rxd_len;        /* MCU reply header length */
    uint32_t rxd_seq_offset;     /* seq byte within the raw reply */
    uint32_t rxd_status_offset;  /* patch-semaphore / patch-finish status byte */
    /* struct mt792xu_wfsys_desc */
    uint32_t wfsys_rst_reg;
    uint32_t wfsys_done_reg;
    uint32_t wfsys_done_mask;
    uint32_t wfsys_done_val;
    uint32_t wfsys_delay_us;
    bool wfsys_need_status_sel;
    /* firmware, relative to the firmware directory, with linux-firmware pinned SHA-256 */
    const char *patch_file;
    const char *patch_sha256;
    const char *ram_file;
    const char *ram_sha256;
} mt7921_chip_profile_t;

const mt7921_chip_profile_t *mt7921_chip_profile(mt7921_chip_t chip);
const mt7921_supported_device_t *mt7921_supported_devices(size_t *count);
/* Chip for a VID:PID, or -1 when not supported. */
int mt7921_chip_for_usb_id(uint16_t vid, uint16_t pid);
/* "0846:9072" -> vid, pid; returns 0 on success. */
int mt7921_parse_usb_id(const char *text, uint16_t *vid, uint16_t *pid);

/* The uni_txd option byte for one command (mt7925_mcu_fill_message vs. the mt7921 constant). */
uint8_t mt7921_uni_option(const mt7921_chip_profile_t *prof, uint8_t cid, bool query);

#endif /* MT7921_CHIP_H */
