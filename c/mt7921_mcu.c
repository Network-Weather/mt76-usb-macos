/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#include "mt7921_mcu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>

static uint64_t current_time_ms(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000ULL + (uint64_t)tv.tv_usec / 1000ULL;
}

static inline uint16_t mcu_read_be16(const void *p) {
    uint16_t val;
    memcpy(&val, p, sizeof(val));
    return CFSwapInt16BigToHost(val);
}

static inline uint32_t mcu_read_be32(const void *p) {
    uint32_t val;
    memcpy(&val, p, sizeof(val));
    return CFSwapInt32BigToHost(val);
}

static inline uint32_t mcu_read_le32(const void *p) {
    uint32_t val;
    memcpy(&val, p, sizeof(val));
    return CFSwapInt32LittleToHost(val);
}

void mt7921_mcu_init(mt7921_mcu_t *mcu, mt7921_usb_t *usb) {
    memset(mcu, 0, sizeof(*mcu));
    mcu->usb = usb;
    mcu->msg_seq = 0;
    mcu->evt_ep4 = false;
}

uint8_t mt7921_mcu_next_seq(mt7921_mcu_t *mcu) {
    mcu->msg_seq = (mcu->msg_seq + 1) & 0x0F;
    if (mcu->msg_seq == 0) {
        mcu->msg_seq = (mcu->msg_seq + 1) & 0x0F;
    }
    return mcu->msg_seq;
}

static void build_mcu_txd(uint8_t *out, uint32_t total_len, uint8_t cid, uint8_t seq,
                          uint8_t ext_cid, uint8_t set_query, uint8_t s2d) {
    uint32_t txd[8] = {0};
    txd[0] = (total_len & 0xFFFF)
           | ((MT_TX_TYPE_CMD & 0x3) << 23)
           | ((MT_TX_MCU_PORT_RX_Q0 & 0x7F) << 25);
    txd[1] = (1U << 31) | ((MT_HDR_FORMAT_CMD & 0x3) << 16);

    for (int i = 0; i < 8; i++) {
        uint32_t le = CFSwapInt32HostToLittle(txd[i]);
        memcpy(out + (i * 4), &le, 4);
    }

    uint16_t pq_id = (MT_TX_PORT_IDX_MCU << 15) | (MT_TX_MCU_PORT_RX_Q0 << 10);
    uint16_t inner_len = (uint16_t)(total_len - 32);

    uint16_t le_len = CFSwapInt16HostToLittle(inner_len);
    uint16_t le_pq = CFSwapInt16HostToLittle(pq_id);
    memcpy(out + 32, &le_len, 2);
    memcpy(out + 34, &le_pq, 2);

    out[36] = cid;
    out[37] = MCU_PKT_ID;
    out[38] = set_query;
    out[39] = seq;

    out[40] = 0;
    out[41] = ext_cid;
    out[42] = s2d;
    out[43] = ext_cid ? 1 : 0;

    memset(out + 44, 0, 20); /* rsv[5] */
}

static void build_uni_txd(uint8_t *out, uint32_t total_len, uint8_t cid, uint8_t seq) {
    uint32_t txd[8] = {0};
    txd[0] = (total_len & 0xFFFF)
           | ((MT_TX_TYPE_CMD & 0x3) << 23)
           | ((MT_TX_MCU_PORT_RX_Q0 & 0x7F) << 25);
    txd[1] = (1U << 31) | ((MT_HDR_FORMAT_CMD & 0x3) << 16);

    for (int i = 0; i < 8; i++) {
        uint32_t le = CFSwapInt32HostToLittle(txd[i]);
        memcpy(out + (i * 4), &le, 4);
    }

    uint16_t inner_len = (uint16_t)(total_len - 32);
    uint16_t le_len = CFSwapInt16HostToLittle(inner_len);
    uint16_t le_cid = CFSwapInt16HostToLittle((uint16_t)cid);

    memcpy(out + 32, &le_len, 2);
    memcpy(out + 34, &le_cid, 2);

    out[36] = 0;
    out[37] = MCU_PKT_ID;
    out[38] = 0;
    out[39] = seq;

    uint16_t rsv0 = 0;
    memcpy(out + 40, &rsv0, 2);
    out[42] = MCU_S2D_H2N;
    out[43] = MCU_CMD_UNI_EXT_ACK;
    memset(out + 44, 0, 4);
}

int mt7921_mcu_send(mt7921_mcu_t *mcu, uint8_t cid, const void *payload,
                    uint32_t payload_len, bool wait, uint8_t *resp_buf,
                    uint32_t *resp_len, uint32_t timeout_ms) {
    uint8_t seq = mt7921_mcu_next_seq(mcu);
    uint8_t ep = EP_OUT_INBAND_CMD;

    uint32_t body_len = 0;
    uint8_t *frame = NULL;
    uint32_t frame_alloc = 0;

    if (cid == MCU_CMD_FW_SCATTER) {
        ep = EP_OUT_AC_BE;
        body_len = payload_len;
        frame_alloc = 4 + body_len + 8;
        frame = (uint8_t*)malloc(frame_alloc);
        if (!frame) return -1;
        uint32_t sdio_hdr = CFSwapInt32HostToLittle(body_len & 0xFFFF);
        memcpy(frame, &sdio_hdr, 4);
        if (payload && payload_len) {
            memcpy(frame + 4, payload, payload_len);
        }
    } else {
        uint32_t total = MCU_TXD_LEN + payload_len;
        body_len = total;
        frame_alloc = 4 + body_len + 8;
        frame = (uint8_t*)malloc(frame_alloc);
        if (!frame) return -1;
        uint32_t sdio_hdr = CFSwapInt32HostToLittle(body_len & 0xFFFF);
        memcpy(frame, &sdio_hdr, 4);
        build_mcu_txd(frame + 4, total, cid, seq, 0, MCU_Q_NA, MCU_S2D_H2N);
        if (payload && payload_len) {
            memcpy(frame + 4 + MCU_TXD_LEN, payload, payload_len);
        }
    }

    uint32_t frame_len = 4 + body_len;
    uint32_t pad = ((frame_len + 3) & ~3) + 4 - frame_len;
    memset(frame + frame_len, 0, pad);
    uint32_t send_len = frame_len + pad;

    int ret = mt7921_bulk_out(mcu->usb, ep, frame, send_len, timeout_ms);
    free(frame);
    if (ret != 0) return -1;

    if (!wait) return 0;
    return mt7921_mcu_wait(mcu, seq, cid, resp_buf, resp_len, timeout_ms);
}

int mt7921_mcu_cmd_word(mt7921_mcu_t *mcu, uint32_t cmd, const void *payload,
                        uint32_t payload_len, bool wait, uint8_t *resp_buf,
                        uint32_t *resp_len, uint32_t timeout_ms) {
    uint8_t cid = (uint8_t)(cmd & MCU_CMD_FIELD_ID);
    uint8_t ext_cid = (uint8_t)((cmd & MCU_CMD_FIELD_EXT_ID) >> 8);
    uint8_t set_query = MCU_Q_NA;
    if (ext_cid || (cmd & MCU_CMD_FIELD_CE)) {
        set_query = (cmd & MCU_CMD_FIELD_QUERY) ? MCU_Q_QUERY : MCU_Q_SET;
    }
    uint8_t s2d = (cmd & MCU_CMD_FIELD_WA) ? MCU_S2D_H2C : MCU_S2D_H2N;

    uint8_t seq = mt7921_mcu_next_seq(mcu);
    uint32_t total = MCU_TXD_LEN + payload_len;
    uint32_t frame_alloc = 4 + total + 8;
    uint8_t *frame = (uint8_t*)malloc(frame_alloc);
    if (!frame) return -1;

    uint32_t sdio_hdr = CFSwapInt32HostToLittle(total & 0xFFFF);
    memcpy(frame, &sdio_hdr, 4);
    build_mcu_txd(frame + 4, total, cid, seq, ext_cid, set_query, s2d);
    if (payload && payload_len) {
        memcpy(frame + 4 + MCU_TXD_LEN, payload, payload_len);
    }

    uint32_t frame_len = 4 + total;
    uint32_t pad = ((frame_len + 3) & ~3) + 4 - frame_len;
    memset(frame + frame_len, 0, pad);
    uint32_t send_len = frame_len + pad;

    int ret = mt7921_bulk_out(mcu->usb, EP_OUT_INBAND_CMD, frame, send_len, timeout_ms);
    free(frame);
    if (ret != 0) return -1;

    if (!wait) return 0;
    return mt7921_mcu_wait(mcu, seq, cid, resp_buf, resp_len, timeout_ms);
}

int mt7921_mcu_uni(mt7921_mcu_t *mcu, uint8_t cid, const void *payload,
                   uint32_t payload_len, bool wait, uint8_t *resp_buf,
                   uint32_t *resp_len, uint32_t timeout_ms) {
    uint8_t seq = mt7921_mcu_next_seq(mcu);
    uint32_t total = MCU_UNI_TXD_LEN + payload_len;
    uint32_t frame_alloc = 4 + total + 8;
    uint8_t *frame = (uint8_t*)malloc(frame_alloc);
    if (!frame) return -1;

    uint32_t sdio_hdr = CFSwapInt32HostToLittle(total & 0xFFFF);
    memcpy(frame, &sdio_hdr, 4);
    build_uni_txd(frame + 4, total, cid, seq);
    if (payload && payload_len) {
        memcpy(frame + 4 + MCU_UNI_TXD_LEN, payload, payload_len);
    }

    uint32_t frame_len = 4 + total;
    uint32_t pad = ((frame_len + 3) & ~3) + 4 - frame_len;
    memset(frame + frame_len, 0, pad);
    uint32_t send_len = frame_len + pad;

    int ret = mt7921_bulk_out(mcu->usb, EP_OUT_INBAND_CMD, frame, send_len, timeout_ms);
    free(frame);
    if (ret != 0) return -1;

    if (!wait) return 0;
    return mt7921_mcu_wait(mcu, seq, cid, resp_buf, resp_len, timeout_ms);
}

int mt7921_mcu_wait(mt7921_mcu_t *mcu, uint8_t seq, uint8_t cid,
                    uint8_t *resp_buf, uint32_t *resp_len, uint32_t timeout_ms) {
    (void)cid;
    uint8_t ep = mcu->evt_ep4 ? EP_IN_PKT_RX : EP_IN_CMD_RESP;
    uint64_t deadline = current_time_ms() + (uint64_t)timeout_ms * 4;

    uint8_t raw[4096];
    while (current_time_ms() < deadline) {
        uint32_t read_len = sizeof(raw);
        int ret = mt7921_bulk_in(mcu->usb, ep, raw, &read_len, timeout_ms);
        if (ret != 0) {
            usleep(5000);
            continue;
        }
        if (read_len < MCU_RXD_LEN) {
            continue;
        }

        uint32_t rxd0 = mcu_read_le32(raw);
        uint32_t pkt_type = (rxd0 >> 27) & 0x1F;
        uint32_t pkt_flag = (rxd0 >> RXD0_PKT_FLAG_SHIFT) & RXD0_PKT_FLAG_MASK;

        bool is_frame = (pkt_type == PKT_TYPE_NORMAL) ||
                        (pkt_type == PKT_TYPE_RX_EVENT && pkt_flag == PKT_FLAG_NORMAL_MCU);

        if (is_frame || pkt_type != PKT_TYPE_RX_EVENT) {
            if (is_frame) mcu->dropped_frames++;
            else mcu->other_packets++;
            continue;
        }

        uint8_t rseq = raw[RXD_SEQ_OFFSET];
        if (rseq == seq) {
            if (resp_buf && resp_len) {
                uint32_t copy_len = (*resp_len < read_len) ? *resp_len : read_len;
                memcpy(resp_buf, raw, copy_len);
                *resp_len = copy_len;
            }
            return 0;
        }
        mcu->stale_events++;
    }
    return -1;
}

/* ---------------- Firmware Parsing & Loading ---------------- */

int mt7921_parse_patch(const uint8_t *blob, size_t len, patch_hdr_t *out) {
    if (len < 96) return -1;
    memset(out, 0, sizeof(*out));

    memcpy(out->build_date, blob, 16);
    out->build_date[16] = '\0';
    memcpy(out->platform, blob + 16, 4);
    out->platform[4] = '\0';

    out->hw_sw_ver = mcu_read_be32(blob + 20);
    out->patch_ver = mcu_read_be32(blob + 24);
    out->checksum = mcu_read_be16(blob + 28);

    out->n_region = mcu_read_be32(blob + 44);
    if (out->n_region > MAX_PATCH_SECTIONS) out->n_region = MAX_PATCH_SECTIONS;

    size_t table_end = 96 + (size_t)out->n_region * 64;
    if (table_end > len) return -1;

    for (uint32_t i = 0; i < out->n_region; i++) {
        const uint8_t *sec = blob + 96 + (i * 64);
        out->sections[i].type = mcu_read_be32(sec + 0);
        out->sections[i].offs = mcu_read_be32(sec + 4);
        out->sections[i].size = mcu_read_be32(sec + 8);
        out->sections[i].addr = mcu_read_be32(sec + 12);
        out->sections[i].len = mcu_read_be32(sec + 16);
        out->sections[i].sec_key_idx = mcu_read_be32(sec + 20);
        out->sections[i].align_len = mcu_read_be32(sec + 24);

        if (out->sections[i].offs > len || out->sections[i].len > len - out->sections[i].offs) {
            return -1;
        }
    }
    return 0;
}

int mt7921_parse_ram(const uint8_t *blob, size_t len, ram_trailer_t *out) {
    if (len < 36) return -1;
    memset(out, 0, sizeof(*out));

    size_t t = len - 36;
    uint8_t n_region = blob[t + 2];
    if (n_region == 0 || n_region > MAX_RAM_REGIONS) return -1;
    out->n_region = n_region;

    memcpy(out->fw_ver, blob + t + 7, 10);
    out->fw_ver[10] = '\0';
    memcpy(out->build_date, blob + t + 17, 15);
    out->build_date[15] = '\0';

    size_t metadata_len = 36 + (size_t)out->n_region * 40;
    if (metadata_len > len) return -1;
    size_t available_payload = len - metadata_len;
    size_t total_payload = 0;

    for (uint32_t i = 0; i < out->n_region; i++) {
        size_t base = t - (size_t)(out->n_region - i) * 40;
        const uint8_t *rg = blob + base;
        out->regions[i].addr = mcu_read_le32(rg + 16);
        out->regions[i].len = mcu_read_le32(rg + 20);
        out->regions[i].feature_set = rg[24];
        out->regions[i].type = rg[25];

        if (out->regions[i].len > available_payload - total_payload) {
            return -1;
        }
        total_payload += out->regions[i].len;
    }
    return 0;
}

static uint32_t get_data_mode(uint32_t sec_info) {
    uint32_t mode = DL_MODE_NEED_RSP;
    if (sec_info == PATCH_SEC_NOT_SUPPORT) return mode;
    uint8_t enc = (sec_info >> 24) & 0xFF;
    if (enc == PATCH_SEC_ENC_TYPE_PLAIN) {
        /* no extra flags */
    } else if (enc == PATCH_SEC_ENC_TYPE_AES) {
        mode |= DL_MODE_ENCRYPT;
        mode |= ((sec_info & 0x0F) << DL_MODE_KEY_IDX_SHIFT) & 0x6;
        mode |= DL_MODE_RESET_SEC_IV;
    } else if (enc == PATCH_SEC_ENC_TYPE_SCRAMBLE) {
        mode |= DL_MODE_ENCRYPT | DL_CONFIG_ENCRY_MODE_SEL | DL_MODE_RESET_SEC_IV;
    }
    return mode;
}

static uint32_t gen_dl_mode(uint8_t feature_set, bool is_wa) {
    uint32_t ret = 0;
    if (feature_set & FW_FEATURE_SET_ENCRYPT) {
        ret |= DL_MODE_ENCRYPT | DL_MODE_RESET_SEC_IV;
    }
    if (feature_set & FW_FEATURE_ENCRY_MODE) {
        ret |= DL_CONFIG_ENCRY_MODE_SEL;
    }
    ret |= (((feature_set & FW_FEATURE_SET_KEY_IDX) >> 1) << DL_MODE_KEY_IDX_SHIFT);
    ret |= DL_MODE_NEED_RSP;
    if (is_wa) {
        ret |= DL_MODE_WORKING_PDA_CR4;
    }
    return ret;
}

static int patch_sem_ctrl(mt7921_mcu_t *mcu, bool get) {
    uint32_t op = CFSwapInt32HostToLittle(get ? PATCH_SEM_GET : PATCH_SEM_RELEASE);
    uint8_t resp[64];
    uint32_t resp_len = sizeof(resp);
    int ret = mt7921_mcu_send(mcu, MCU_CMD_PATCH_SEM_CONTROL, &op, 4, true, resp, &resp_len, 3000);
    if (ret != 0 || resp_len <= RXD_STATUS_OFFSET) return -1;
    return resp[RXD_STATUS_OFFSET];
}

static int init_download(mt7921_mcu_t *mcu, uint32_t addr, uint32_t length, uint32_t mode) {
    uint8_t cid = (addr == 0x900000) ? MCU_CMD_PATCH_START_REQ : MCU_CMD_TARGET_ADDRESS_LEN_REQ;
    uint32_t payload[3] = {
        CFSwapInt32HostToLittle(addr),
        CFSwapInt32HostToLittle(length),
        CFSwapInt32HostToLittle(mode)
    };
    return mt7921_mcu_send(mcu, cid, payload, 12, true, NULL, NULL, 3000);
}

static int send_firmware(mt7921_mcu_t *mcu, const uint8_t *data, size_t len) {
    size_t off = 0;
    while (off < len) {
        size_t n = (len - off < FW_SCATTER_MAX) ? (len - off) : FW_SCATTER_MAX;
        int ret = mt7921_mcu_send(mcu, MCU_CMD_FW_SCATTER, data + off, (uint32_t)n, false, NULL, NULL, 3000);
        if (ret != 0) return -1;
        off += n;
    }
    return 0;
}

static int start_patch(mt7921_mcu_t *mcu) {
    uint8_t zeros[4] = {0};
    uint8_t resp[64];
    uint32_t resp_len = sizeof(resp);
    int ret = mt7921_mcu_send(mcu, MCU_CMD_PATCH_FINISH_REQ, zeros, 4, true, resp, &resp_len, 3000);
    if (ret != 0 || resp_len <= RXD_STATUS_OFFSET) return -1;
    return resp[RXD_STATUS_OFFSET];
}

static int start_firmware(mt7921_mcu_t *mcu, uint32_t override, uint32_t option) {
    uint32_t payload[2] = {
        CFSwapInt32HostToLittle(option),
        CFSwapInt32HostToLittle(override)
    };
    return mt7921_mcu_send(mcu, MCU_CMD_FW_START_REQ, payload, 8, true, NULL, NULL, 3000);
}

int mt7921_load_patch(mt7921_mcu_t *mcu, const uint8_t *blob, size_t len,
                      void (*log_fn)(const char *fmt, ...)) {
    int sem = patch_sem_ctrl(mcu, true);
    if (sem == PATCH_IS_DL) {
        if (log_fn) log_fn("  patch already downloaded\n");
        return 0;
    }
    if (sem != PATCH_NOT_DL_SEM_SUCCESS) {
        if (log_fn) log_fn("  failed to get patch semaphore (status %d)\n", sem);
        return -1;
    }

    patch_hdr_t p;
    if (mt7921_parse_patch(blob, len, &p) != 0) {
        patch_sem_ctrl(mcu, false);
        return -1;
    }

    if (log_fn) log_fn("  patch %s hw/sw 0x%08x, %u region(s)\n", p.build_date, p.hw_sw_ver, p.n_region);

    for (uint32_t i = 0; i < p.n_region; i++) {
        patch_sec_t *sec = &p.sections[i];
        if ((sec->type & PATCH_SEC_TYPE_MASK) != PATCH_SEC_TYPE_INFO) {
            patch_sem_ctrl(mcu, false);
            return -1;
        }
        uint32_t mode = get_data_mode(sec->sec_key_idx);
        if (log_fn) log_fn("  section %u: addr=0x%08x len=%u mode=0x%08x\n", i, sec->addr, sec->len, mode);
        if (init_download(mcu, sec->addr, sec->len, mode) != 0) {
            patch_sem_ctrl(mcu, false);
            return -1;
        }
        if (send_firmware(mcu, blob + sec->offs, sec->len) != 0) {
            patch_sem_ctrl(mcu, false);
            return -1;
        }
    }

    int st = start_patch(mcu);
    patch_sem_ctrl(mcu, false);
    if (st != 0) {
        if (log_fn) log_fn("  PATCH_FINISH_REQ returned %d\n", st);
        return -1;
    }
    if (log_fn) log_fn("  patch started\n");
    return 0;
}

int mt7921_load_ram(mt7921_mcu_t *mcu, const uint8_t *blob, size_t len,
                    void (*log_fn)(const char *fmt, ...)) {
    ram_trailer_t r;
    if (mt7921_parse_ram(blob, len, &r) != 0) return -1;
    if (log_fn) log_fn("  ram fw %s built %s, %u regions\n", r.fw_ver, r.build_date, r.n_region);

    uint32_t override = 0;
    uint32_t option = 0;
    size_t offset = 0;

    for (uint32_t i = 0; i < r.n_region; i++) {
        ram_region_t *rg = &r.regions[i];
        uint32_t mode = gen_dl_mode(rg->feature_set, false);
        if (rg->feature_set & FW_FEATURE_OVERRIDE_ADDR) {
            override = rg->addr;
        }
        if (rg->feature_set & FW_FEATURE_NON_DL) {
            if (log_fn) log_fn("  region %u: NON_DL, skipped (%u bytes)\n", i, rg->len);
            offset += rg->len;
            continue;
        }
        if (offset + rg->len > len - (36 + (size_t)r.n_region * 40)) return -1;
        if (log_fn) log_fn("  region %u: addr=0x%08x len=%u mode=0x%08x\n", i, rg->addr, rg->len, mode);
        if (init_download(mcu, rg->addr, rg->len, mode) != 0) return -1;
        if (send_firmware(mcu, blob + offset, rg->len) != 0) return -1;
        offset += rg->len;
    }

    if (override) {
        option |= FW_START_OVERRIDE;
    }
    if (log_fn) log_fn("  starting firmware: override=0x%08x option=0x%x\n", override, option);
    return start_firmware(mcu, override, option);
}

int mt7921_nic_power_ctrl(mt7921_mcu_t *mcu, uint8_t power_mode) {
    uint8_t payload[4] = { power_mode, 0, 0, 0 };
    return mt7921_mcu_send(mcu, MCU_CMD_NIC_POWER_CTRL, payload, 4, false, NULL, NULL, 3000);
}

int mt7921_get_nic_capability(mt7921_mcu_t *mcu) {
    uint8_t resp[256];
    uint32_t resp_len = sizeof(resp);
    return mt7921_mcu_cmd_word(mcu, MCU_CE_CMD(MCU_CE_CMD_GET_NIC_CAPAB), NULL, 0, true, resp, &resp_len, 3000);
}

int mt7921_set_eeprom(mt7921_mcu_t *mcu) {
    uint8_t req[4] = { EE_MODE_EFUSE, EE_FORMAT_WHOLE, 0, 0 };
    return mt7921_mcu_cmd_word(mcu, MCU_EXT_CMD(MCU_EXT_CMD_EFUSE_BUFFER_MODE), req, 4, true, NULL, NULL, 3000);
}

int mt7921_get_temperature(mt7921_mcu_t *mcu, int32_t *temp_c) {
    if (!mcu || !temp_c) return -1;
    uint8_t req[8] = {0};
    req[0] = THERMAL_SENSOR_TEMP_QUERY;

    uint8_t resp[128];
    uint32_t resp_len = sizeof(resp);
    uint32_t cmd = MCU_EXT_CMD(MCU_EXT_CMD_THERMAL_CTRL);
    int ret = mt7921_mcu_cmd_word(mcu, cmd, req, sizeof(req), true, resp, &resp_len, 3000);
    if (ret != 0 || resp_len < MCU_RXD_LEN + 8) return -1;

    uint8_t *body = resp + MCU_RXD_LEN;
    *temp_c = (int32_t)mcu_read_le32(body + 4);
    return 0;
}

int mt7921_read_efuse(mt7921_mcu_t *mcu, uint32_t offset, uint8_t data[16], uint32_t *valid) {
    if (!mcu || !data) return -1;
    uint32_t base = offset & ~(MT7921_EEPROM_BLOCK_SIZE - 1);
    uint8_t req[8 + MT7921_EEPROM_BLOCK_SIZE] = {0};
    uint32_t le_base = CFSwapInt32HostToLittle(base);
    memcpy(req, &le_base, 4);

    uint8_t resp[128];
    uint32_t resp_len = sizeof(resp);
    uint32_t cmd = MCU_EXT_CMD(MCU_EXT_CMD_EFUSE_ACCESS) | MCU_CMD_FIELD_QUERY;
    int ret = mt7921_mcu_cmd_word(mcu, cmd, req, sizeof(req), true, resp, &resp_len, 3000);
    if (ret != 0 || resp_len < MCU_RXD_LEN + 8 + MT7921_EEPROM_BLOCK_SIZE) return -1;

    uint8_t *body = resp + MCU_RXD_LEN;
    if (valid) {
        *valid = mcu_read_le32(body + 4);
    }
    memcpy(data, body + 8, MT7921_EEPROM_BLOCK_SIZE);
    return 0;
}
