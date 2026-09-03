/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#ifndef MT7921_MCU_H
#define MT7921_MCU_H

#include "mt7921_usb.h"
#include <stdbool.h>

#define MAX_PATCH_SECTIONS 16
#define MAX_RAM_REGIONS    16

typedef struct {
    uint32_t type;
    uint32_t offs;
    uint32_t size;
    uint32_t addr;
    uint32_t len;
    uint32_t sec_key_idx;
    uint32_t align_len;
} patch_sec_t;

typedef struct {
    char build_date[17];
    char platform[5];
    uint32_t hw_sw_ver;
    uint32_t patch_ver;
    uint16_t checksum;
    uint32_t n_region;
    patch_sec_t sections[MAX_PATCH_SECTIONS];
} patch_hdr_t;

typedef struct {
    uint32_t addr;
    uint32_t len;
    uint8_t feature_set;
    uint8_t type;
} ram_region_t;

typedef struct {
    char fw_ver[11];
    char build_date[16];
    uint8_t n_region;
    ram_region_t regions[MAX_RAM_REGIONS];
} ram_trailer_t;

typedef struct {
    mt7921_usb_t *usb;
    uint8_t msg_seq;
    bool evt_ep4;
    uint32_t dropped_frames;
    uint32_t stale_events;
    uint32_t other_packets;
} mt7921_mcu_t;

void mt7921_mcu_init(mt7921_mcu_t *mcu, mt7921_usb_t *usb);
uint8_t mt7921_mcu_next_seq(mt7921_mcu_t *mcu);

int mt7921_mcu_send(mt7921_mcu_t *mcu, uint8_t cid, const void *payload,
                    uint32_t payload_len, bool wait, uint8_t *resp_buf,
                    uint32_t *resp_len, uint32_t timeout_ms);

int mt7921_mcu_cmd_word(mt7921_mcu_t *mcu, uint32_t cmd, const void *payload,
                        uint32_t payload_len, bool wait, uint8_t *resp_buf,
                        uint32_t *resp_len, uint32_t timeout_ms);

int mt7921_mcu_uni(mt7921_mcu_t *mcu, uint8_t cid, const void *payload,
                   uint32_t payload_len, bool wait, uint8_t *resp_buf,
                   uint32_t *resp_len, uint32_t timeout_ms);

int mt7921_mcu_wait(mt7921_mcu_t *mcu, uint8_t seq, uint8_t cid,
                    uint8_t *resp_buf, uint32_t *resp_len, uint32_t timeout_ms);

/* Firmware Parsing & Loading */
int mt7921_parse_patch(const uint8_t *blob, size_t len, patch_hdr_t *out);
int mt7921_parse_ram(const uint8_t *blob, size_t len, ram_trailer_t *out);

int mt7921_load_patch(mt7921_mcu_t *mcu, const uint8_t *blob, size_t len,
                      void (*log_fn)(const char *fmt, ...));
int mt7921_load_ram(mt7921_mcu_t *mcu, const uint8_t *blob, size_t len,
                    void (*log_fn)(const char *fmt, ...));

int mt7921_nic_power_ctrl(mt7921_mcu_t *mcu, uint8_t power_mode);
int mt7921_get_nic_capability(mt7921_mcu_t *mcu);
int mt7921_set_eeprom(mt7921_mcu_t *mcu);

#endif /* MT7921_MCU_H */
