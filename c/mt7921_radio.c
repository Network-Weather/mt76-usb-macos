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
    /* Legacy non-session MCU waits do not trim USB padding. Validate the record
     * here too, so bytes outside DMA length can never manufacture a counter. */
    if (reply_len < dev->mcu.prof->mcu_rxd_len) return -1;
    uint32_t word = le32(reply), size = word & 0xFFFF;
    if (size < dev->mcu.prof->mcu_rxd_len || size > reply_len || size > sizeof(reply) ||
        word >> 27 != PKT_TYPE_RX_EVENT ||
        ((word >> RXD0_PKT_FLAG_SHIFT) & RXD0_PKT_FLAG_MASK) == PKT_FLAG_NORMAL_MCU ||
        reply[dev->mcu.prof->rxd_seq_offset] != dev->mcu.msg_seq) return -1;
    reply_len = size;
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

/* Keep wire/field/accumulator widths distinct. Shared Python/C fixture tests
 * verify this finite profile. Duration tick conversion remains unqualified. */
static const mt_counter_descriptor_t counters_7921[] = {
    {"rx_mpdu", MT_COUNTER_RX_MPDU, 2, MT_COUNTER_COUNT, 32, 0, 0, 0, false},
    {"rx_mdrdy", MT_COUNTER_RX_MDRDY, 7, MT_COUNTER_COUNT, 32, 0, 0, 0, false},
    {"primary_cca", MT_COUNTER_PRIMARY_CCA, 11, MT_COUNTER_DURATION_TICKS, 32, 0, 0, 0, false},
    {"cca_nav_tx", MT_COUNTER_CCA_NAV_TX, 14, MT_COUNTER_DURATION_TICKS, 32, 0, 0, 0, false},
};
static const mt_counter_descriptor_t counters_7925[] = {
    {"rx_mpdu", MT_COUNTER_RX_MPDU, 2, MT_COUNTER_COUNT, 64, 32, 0, 0, false},
    {"rx_fcs_error", MT_COUNTER_RX_FCS_ERROR, 0, MT_COUNTER_COUNT, 64, 32, 0, 0, false},
    {"rx_mdrdy", MT_COUNTER_RX_MDRDY, 11, MT_COUNTER_COUNT, 64, 32, 0, 0, false},
    {"primary_cca", MT_COUNTER_PRIMARY_CCA, 17, MT_COUNTER_DURATION_TICKS, 64, 32, 0, 0, false},
    {"cca_nav_tx", MT_COUNTER_CCA_NAV_TX, 19, MT_COUNTER_DURATION_TICKS, 64, 24, 0, 0, false},
    {"cck_rx_duration", MT_COUNTER_CCK_RX_DURATION, 12, MT_COUNTER_DURATION_TICKS, 64, 32, 0, 0, false},
    {"ofdm_rx_duration", MT_COUNTER_OFDM_RX_DURATION, 13, MT_COUNTER_DURATION_TICKS, 64, 32, 0, 0, false},
    {"primary_ed", MT_COUNTER_PRIMARY_ED, 20, MT_COUNTER_DURATION_TICKS, 64, 24, 0, 0, false},
    {"nav", MT_COUNTER_NAV, 52, MT_COUNTER_DURATION_TICKS, 64, 24, 0, 0, false},
    {"idle_slots", MT_COUNTER_IDLE_SLOTS, 7, MT_COUNTER_SLOTS, 64, 16, 0, 9000, true},
};
const mt_counter_descriptor_t *mt_counter_descriptor(int chip, int counter) {
    const mt_counter_descriptor_t *table;
    size_t count;
    if (chip == MT_CHIP_MT7921) {
        table = counters_7921; count = sizeof(counters_7921) / sizeof(*table);
    } else if (chip == MT_CHIP_MT7925) {
        table = counters_7925; count = sizeof(counters_7925) / sizeof(*table);
    } else return NULL;
    for (size_t i = 0; i < count; i++) if (table[i].counter == counter) return &table[i];
    return NULL;
}
int mt_counter_read(mt7921_dev_t *dev, const int *counters, size_t count,
                     mt_counter_sample_t *sample) {
    if (!dev || !counters || !sample || !count || count > MT_MIB_MAX) return -1;
    mt_counter_sample_t result = {0};
    uint32_t offsets[MT_MIB_MAX];
    for (size_t i = 0; i < count; i++) {
        result.descriptors[i] = mt_counter_descriptor(dev->usb.chip, counters[i]);
        if (!result.descriptors[i]) return MT7921_ERR_UNSUPPORTED;
        offsets[i] = result.descriptors[i]->offset;
        for (size_t j = 0; j < i; j++) if (counters[j] == counters[i]) return -1;
    }
    if (dev->usb.chip == MT_CHIP_MT7925) {
        if (mt_mib_read(dev, offsets, count, &result.raw)) return -1;
    } else {
        for (size_t i = 0; i < count; i++) {
            mt_mib_sample_t one;
            if (mt_mib_read(dev, offsets + i, 1, &one)) return -1;
            if (!i) result.raw.opened_us = one.opened_us;
            result.raw.closed_us = one.closed_us;
            result.raw.dropped_frames += one.dropped_frames;
            result.raw.values[i] = one.values[0];
            result.raw.offsets[i] = offsets[i];
        }
        result.raw.count = count;
        result.raw.counter_bits = 32; /* compatibility field: wire width only */
    }
    *sample = result;
    return 0;
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

int mt_probe_txwi(int chip, const uint8_t *frame, size_t len, unsigned seq,
                  int rate, int power, uint8_t *out) {
    /* mt7925_mac_write_txwi{,_80211}, mt76_connac{2,3}_mac.h, c5a3bd91;
     * measured subset matches research/mt7925_tx_probe.py and tx_power_probe.py. */
    if (!frame || !out || len < 24 || len > 512 || frame[0] != 0x40 || frame[1] || seq > 4095)
        return -1;
    if (power != 0 && power != -8 && power != -16 && !(chip == MT_CHIP_MT7925 && power == -32))
        return -1;
    uint32_t words[16] = {0};
    if (chip == MT_CHIP_MT7921) {
        if ((rate != MT_PROBE_CCK1 && rate != MT_PROBE_OFDM6) || (rate == MT_PROBE_CCK1 && power))
            return -1;
        if (mt7921_build_txwi(out, frame, len, (uint16_t)seq, 3) != 64) return -1;
        uint32_t w2 = le32(out + 8);
        put32(out + 8, (w2 & ~(63U << 24)) | ((uint32_t)power & 63) << 24);
        put32(out + 24, MT_TXD6_FIXED_BW | (rate == MT_PROBE_OFDM6 ? 0x4bU << 16 : 0));
        return 64;
    }
    if (chip != MT_CHIP_MT7925 || (rate != MT_PROBE_OFDM6 && rate != MT_PROBE_OFDM54)) return -1;
    unsigned table = rate == MT_PROBE_OFDM6 ? 18 : 25;
    words[0] = (uint32_t)len + 64 | (1U << 23) | (0x10U << 25);
    words[1] = (1U << 31) | (12U << 16) | (2U << 14);
    words[2] = 4 | (((uint32_t)power & 63) << 26);
    words[3] = (1U << 31) | (1U << 28) | (seq << 16) | (15U << 11) | 1;
    if (frame[4] & 1) words[3] |= 1U << 4;
    words[5] = 3 | (1U << 10);
    words[6] = (table << 16) | (1U << 4) | (1U << 3) | (1U << 2); /* MSDU, DIS_MAT, DAS */
    for (unsigned i = 0; i < 16; i++) put32(out + 4 * i, words[i]);
    return 64;
}

int mt_probe_rate_table(mt_radio_reg_io_t io, int rate) {
    /* mt7925_mac_set_fixed_rate_table, mt792x_regs.h MT_WTBL_IT*, c5a3bd91.
     * mac80211.c mt76_rates: base 14 + OFDM6 index 4 / OFDM54 index 11. */
    if (!io.read || !io.write || !io.pause_ms ||
        (rate != MT_PROBE_OFDM6 && rate != MT_PROBE_OFDM54)) return -1;
    unsigned table = rate == MT_PROBE_OFDM6 ? 18 : 25;
    uint32_t code = rate == MT_PROBE_OFDM6 ? 0x4b : 0x4c;
    if (io.write(io.ctx, 0x820d43b8, code) || io.write(io.ctx, 0x820d43bc, 1U << 6) ||
        io.write(io.ctx, 0x820d43b0, (1U << 16) | (1U << 31) | table)) return -1;
    for (unsigned i = 0; i < 100; i++) {
        uint32_t value;
        if (io.read(io.ctx, 0x820d43b0, &value)) return -1;
        if (!(value & (1U << 31))) return 0;
        io.pause_ms(io.ctx, 1);
    }
    return MT7921_ERR_TIMEOUT;
}
int mt_probe_prepare(mt7921_dev_t *dev, int rate) {
    if (!dev || !dev->tuned) return -1;
    if (dev->usb.chip == MT_CHIP_MT7921)
        return rate == MT_PROBE_CCK1 || rate == MT_PROBE_OFDM6 ? 0 : -1;
    if (dev->usb.chip != MT_CHIP_MT7925 || (rate != MT_PROBE_OFDM6 && rate != MT_PROBE_OFDM54))
        return -1;
    dev->experimental_tx_dirty = true;
    int ret = mt_probe_rate_table(mt_radio_device_io(dev), rate);
    if (!ret) dev->experimental_rates |= 1U << rate;
    return ret;
}
int mt_probe_transmit(mt7921_dev_t *dev, const uint8_t *frame, size_t len,
                      unsigned seq, int rate, int power) {
    if (!dev || !dev->tuned || dev->tuned_width != 20 ||
        dev->tuned_control != dev->tuned_center || dev->experimental_tx_count >= 60) return -1;
    if (rate == MT_PROBE_CCK1) {
        if (dev->tuned_band != 0 || dev->tuned_control != 6) return -1;
    } else if (dev->tuned_band != 1 || (dev->tuned_control != 36 && dev->tuned_control != 149))
        return -1;
    uint8_t packet[4 + 64 + 512 + 8] = {0};
    if (mt_probe_txwi(dev->usb.chip, frame, len, seq, rate, power, packet + 4) < 0) return -1;
    if (dev->usb.chip == MT_CHIP_MT7925 && !(dev->experimental_rates & (1U << rate))) return -1;
    uint64_t now = mt_radio_monotonic_us();
    if (dev->experimental_tx_count && now - dev->experimental_last_tx_us < 50000) return -1;
    put32(packet, (uint32_t)len + 64);
    memcpy(packet + 68, frame, len);
    size_t total = ((68 + len + 3) & ~(size_t)3) + 4;
    dev->experimental_tx_count++;
    dev->experimental_last_tx_us = now;
    return mt7921_bulk_out(&dev->usb, MT_ROLE_AC_BE, packet, (uint32_t)total, 1000);
}

int mt_tx_status_parse(int chip, const uint8_t *raw, size_t len,
                       mt_tx_status_t *out, size_t capacity) {
    /* mt7921_mac_rx_check: prefix 2 DW, records 8 DW; mt7925_mac_rx_check:
     * prefix 4 DW, records 12 DW. MT_TXS* definitions in connac{2,3}_mac.h. */
    if (!raw || !out || len < 4 || (chip != MT_CHIP_MT7921 && chip != MT_CHIP_MT7925)) return -1;
    uint32_t w0 = le32(raw), end = w0 & 0xffff;
    size_t prefix = chip == MT_CHIP_MT7925 ? 16 : 8;
    size_t stride = chip == MT_CHIP_MT7925 ? 48 : 32;
    if ((w0 >> 27) != 0 || end > len || end < prefix || (end - prefix) % stride) return -1;
    size_t n = (end - prefix) / stride;
    if (n > capacity) return -1;
    for (size_t i = 0; i < n; i++) {
        const uint8_t *p = raw + prefix + i * stride;
        uint32_t a = le32(p), b = le32(p + 4), d = le32(p + 12);
        mt_tx_status_t value = {0};
        value.format = (a >> 23) & 3;
        value.rate_raw = a & 0x3fff;
        value.power_raw = b & 255;
        value.power_signed = value.power_raw < 128 ? value.power_raw : (int)value.power_raw - 256;
        value.sequence = b >> 20;
        value.pid = d >> 24;
        value.ack_error_bits = (a >> 16) & 7;
        value.error_bits_16_22 = (a >> 16) & 127;
        value.has_tx_count = chip == MT_CHIP_MT7925 && value.format == 0;
        if (value.has_tx_count) value.tx_count = (le32(p + 20) >> 25) & 31;
        out[i] = value;
    }
    return (int)n;
}
