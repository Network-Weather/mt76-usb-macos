/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Protocol references: openwrt/mt76 c5a3bd91aa735b669618610d5f0ebfa5786845a6.
 * mt76_connac_mcu.h GET_MIB_INFO; mt7915/mcu.h struct mt7915_mcu_mib;
 * mt7996/mcu.c mt7996_mcu_get_chan_mib_info. Chip-specific measured semantics:
 * docs/FIRMWARE_RECON.md and docs/MT7925_MIB.md. */
#include "mt7921_radio.h"
#include <string.h>
#include <time.h>
#include <unistd.h>

static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t le64(const uint8_t *p) { return le32(p) | (uint64_t)le32(p + 4) << 32; }
static void put32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i));
}
static bool valid_offsets(int chip, const uint32_t *offsets, size_t n) {
    if (!offsets || !n || n > MT_MIB_MAX ||
        (chip != MT_CHIP_MT7921 && chip != MT_CHIP_MT7925) ||
        (chip == MT_CHIP_MT7921 && n != 1)) return false;
    for (size_t i = 0; i < n; i++) {
        if (offsets[i] > 511) return false;
        for (size_t j = 0; j < i; j++) if (offsets[i] == offsets[j]) return false;
    }
    return true;
}
int mt_mib_request(int chip, uint8_t band, const uint32_t *offsets, size_t n,
                   uint8_t *out, size_t cap) {
    if (!out || band > 1 || !valid_offsets(chip, offsets, n)) return -1;
    size_t len = chip == MT_CHIP_MT7921 ? 16 : 4 + 8 * n;
    if (cap < len) return -1;
    memset(out, 0, len);
    out[0] = band;
    if (chip == MT_CHIP_MT7921) put32(out + 4, offsets[0]);
    else for (size_t i = 0; i < n; i++) {
        out[4 + i * 8 + 2] = 8; /* tag 0, request TLV length 8 */
        put32(out + 4 + i * 8 + 4, offsets[i]);
    }
    return (int)len;
}
int mt_mib_parse(int chip, const uint8_t *body, size_t len,
                 const uint32_t *offsets, size_t n, uint64_t *values) {
    if (!body || !values || !valid_offsets(chip, offsets, n)) return -1;
    uint64_t parsed[MT_MIB_MAX] = {0};
    if (chip == MT_CHIP_MT7921) {
        /* Measured 32-bit word at body+28, NOT the mt7915 64-bit layout.
         * No echoed offset: correlate through the MCU sequence and one-entry request. */
        if (len < 32) return -1;
        parsed[0] = le32(body + 28);
    } else {
        bool found[MT_MIB_MAX] = {false};
        /* Firmware prefix length varies. Match tag, permitted wire length, and echo
         * on a 16-bit boundary; reject duplicate/ambiguous entries rather than guessing. */
        for (size_t at = 0; at <= len && len - at >= 8; at += 2) {
            if (body[at] || body[at + 1]) continue;
            uint32_t echoed = le32(body + at + 4);
            for (size_t i = 0; i < n; i++) {
                if (echoed != offsets[i]) continue;
                unsigned size = body[at + 2] | (unsigned)body[at + 3] << 8;
                if (size != 8 && size != 16) continue;
                if (len - at < 16 || found[i]) return -1;
                parsed[i] = le64(body + at + 8);
                found[i] = true;
            }
        }
        for (size_t i = 0; i < n; i++) if (!found[i]) return -1;
    }
    memcpy(values, parsed, n * sizeof(*values));
    return 0;
}
uint64_t mt_radio_monotonic_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000 + (uint64_t)ts.tv_nsec / 1000;
}
int mt_mib_read(mt7921_dev_t *dev, const uint32_t *offsets, size_t n,
                mt_mib_sample_t *sample) {
    if (!dev || !sample) return -1;
    memset(sample, 0, sizeof(*sample));
    uint8_t request[4 + MT_MIB_MAX * 8], reply[1024];
    int len = mt_mib_request(dev->usb.chip, 0, offsets, n, request, sizeof(request));
    if (len < 0) return -1;
    uint32_t reply_len = sizeof(reply), dropped = dev->mcu.dropped_frames;
    sample->opened_us = mt_radio_monotonic_us();
    int ret = dev->usb.chip == MT_CHIP_MT7925
        ? mt7921_mcu_uni_query(&dev->mcu, 0x22, request, (uint32_t)len, true,
                              reply, &reply_len, 700)
        : mt7921_mcu_cmd_word(&dev->mcu, MCU_EXT_CMD(0x5a), request, (uint32_t)len,
                             true, reply, &reply_len, 700);
    sample->closed_us = mt_radio_monotonic_us();
    sample->dropped_frames = dev->mcu.dropped_frames - dropped;
    if (ret) return ret;
    uint32_t body_len = 0;
    const uint8_t *body = mt7921_mcu_reply_body(&dev->mcu, reply, reply_len, &body_len);
    if (mt_mib_parse(dev->usb.chip, body, body_len, offsets, n, sample->values)) return -1;
    memcpy(sample->offsets, offsets, n * sizeof(*offsets));
    sample->count = n;
    sample->counter_bits = dev->usb.chip == MT_CHIP_MT7925 ? 64 : 32;
    return 0;
}
bool mt_mib_delta(uint64_t before, uint64_t after, unsigned bits,
                  uint64_t max_delta, uint64_t *delta) {
    if (!delta || (bits != 32 && bits != 64)) return false;
    if (bits == 32 && (before > UINT32_MAX || after > UINT32_MAX)) return false;
    uint64_t value = after - before;
    if (bits == 32) value &= UINT32_MAX;
    if (value > max_delta) return false;
    *delta = value;
    return true;
}

/* mt792x_regs.h MT_DMA_DCR0(0), MT_DMA_DCR0_RXD_G5_EN, c5a3bd91. */
#define G5_REG 0x820e7000U
#define G5_BIT (1U << 23)
int mt_g5_begin(mt_g5_guard_t *guard, mt_radio_reg_io_t io) {
    if (!guard || guard->active || !io.read || !io.write) return -1;
    uint32_t old, check;
    if (io.read(io.ctx, G5_REG, &old)) return -1;
    guard->io = io;
    guard->saved_bit = old & G5_BIT;
    guard->active = true; /* a failed write may still have reached hardware */
    if (io.write(io.ctx, G5_REG, old | G5_BIT) ||
        io.read(io.ctx, G5_REG, &check) || !(check & G5_BIT)) return -1;
    return 0;
}
int mt_g5_restore(mt_g5_guard_t *guard) {
    if (!guard) return -1;
    if (!guard->active) return 0;
    uint32_t current, check;
    mt_radio_reg_io_t *io = &guard->io;
    if (io->read(io->ctx, G5_REG, &current) ||
        io->write(io->ctx, G5_REG, (current & ~G5_BIT) | guard->saved_bit) ||
        io->read(io->ctx, G5_REG, &check) || (check & G5_BIT) != guard->saved_bit) return -1;
    guard->active = false;
    return 0;
}
static int reg_read(void *ctx, uint32_t addr, uint32_t *v) {
    return mt7921_rr_checked(ctx, addr, v);
}
static int reg_write(void *ctx, uint32_t addr, uint32_t v) { return mt7921_wr(ctx, addr, v); }
static void reg_pause(void *ctx, unsigned ms) { (void)ctx; usleep(ms * 1000); }
mt_radio_reg_io_t mt_radio_device_io(mt7921_dev_t *dev) {
    return (mt_radio_reg_io_t){&dev->usb, reg_read, reg_write, reg_pause};
}
int mt_g5_begin_device(mt7921_dev_t *dev, mt_g5_guard_t *guard) {
    if (!dev || dev->usb.chip != MT_CHIP_MT7921) return MT7921_ERR_UNSUPPORTED;
    return mt_g5_begin(guard, mt_radio_device_io(dev));
}
