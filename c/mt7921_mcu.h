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
    const mt7921_chip_profile_t *prof; /* MCU geometry and command encodings for usb->chip */
    uint8_t msg_seq;
    bool evt_ep4;
    uint32_t dropped_frames;
    uint32_t stale_events;
    uint32_t other_packets;
    /* From the NIC capability reply (MT7925 element list): 0 when not reported. */
    uint8_t phy_nss;
    bool has_6ghz;
    /* Injectable transport for offline stale-reply/timeout tests; initialized to
     * native USB functions. Callers must retain single-reader ownership. */
    int (*read_bulk)(mt7921_usb_t *, uint8_t, void *, uint32_t *, uint32_t);
    int (*write_bulk)(mt7921_usb_t *, uint8_t, const void *, uint32_t, uint32_t);
    void *session_context;
    int (*session_wait)(void *, uint8_t, uint8_t, uint8_t *, uint32_t *, uint32_t);
} mt7921_mcu_t;

void mt7921_mcu_init(mt7921_mcu_t *mcu, mt7921_usb_t *usb);

enum { MT_THERMAL_TEMPERATURE = 0, MT_THERMAL_RAW_ADC = 1 };
typedef struct {
    uint32_t raw;
    int32_t reported_temperature_c;
    bool has_temperature;
    int chip, action;
    uint64_t opened_us, closed_us;
    uint32_t dropped_frames; /* legacy MCU discards, not session queue overflow */
} mt_thermal_sample_t;
/* Pure query-only encoders/parsers. MT7921: temperature only, EXT2c.
 * MT7925: UNI35 tag0 temperature/raw ADC, band0; ADC conversion uncalibrated.
 * Output unchanged on failure; no sensor/protection controls. */
int mt_thermal_request(int chip, int action, uint8_t *out, size_t capacity);
int mt_thermal_parse(int chip, int action, const uint8_t *raw, size_t len,
                      uint8_t sequence, uint32_t *value);
int mt_thermal_read(mt7921_mcu_t *mcu, int action, mt_thermal_sample_t *sample);

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
/* Same, marking a __MCU_CMD_FIELD_QUERY command word (affects the MT7925 option byte). */
int mt7921_mcu_uni_query(mt7921_mcu_t *mcu, uint8_t cid, const void *payload,
                         uint32_t payload_len, bool wait, uint8_t *resp_buf,
                         uint32_t *resp_len, uint32_t timeout_ms);

/* TXD builders, exposed for offline tests. total_len includes the TXD itself. */
void mt7921_mcu_build_txd(const mt7921_mcu_t *mcu, uint8_t *out, uint32_t total_len, uint8_t cid,
                          uint8_t seq, uint8_t ext_cid, uint8_t set_query, uint8_t s2d);
void mt7921_mcu_build_uni_txd(const mt7921_mcu_t *mcu, uint8_t *out, uint32_t total_len,
                              uint8_t cid, uint8_t seq, bool query);
/* Reply payload after the chip's MCU reply header, or NULL when the reply is too short. */
const uint8_t *mt7921_mcu_reply_body(const mt7921_mcu_t *mcu, const uint8_t *resp, uint32_t resp_len,
                                     uint32_t *body_len);

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

/* Housekeeping queries are MT7921-only; both return MT7921_ERR_UNSUPPORTED on the MT7925. */
#define MT7921_ERR_UNSUPPORTED -2
int mt7921_get_temperature(mt7921_mcu_t *mcu, int32_t *temp_c);
int mt7921_read_efuse(mt7921_mcu_t *mcu, uint32_t offset, uint8_t data[16], uint32_t *valid);

#endif /* MT7921_MCU_H */
