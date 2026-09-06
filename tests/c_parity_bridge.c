/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Synthetic-test bridge only; never opens a USB device. */
#include "mt7921_rxd.h"
#include "mt7921_chip.h"
#include "mt7921_radio.h"
#include <string.h>

static uint8_t counter_payload[256];
static unsigned counter_size, counter_writes;
static int counter_chip, counter_failure;
static int thermal_test_action = -1;
static int counter_write(mt7921_usb_t *usb, uint8_t ep, const void *data, uint32_t len, uint32_t ms) {
    (void)usb; (void)ep; (void)ms;
    counter_writes++;
    if (thermal_test_action >= 0 && counter_failure == 1) return -1;
    if (counter_failure == 1 && counter_writes == 2) return -1;
    unsigned prefix = 4 + (counter_chip == MT_CHIP_MT7925 ? MCU_UNI_TXD_LEN : MCU_TXD_LEN);
    if (len < prefix || len - prefix > sizeof(counter_payload)) return -1;
    counter_size = len - prefix;
    memcpy(counter_payload, (const uint8_t *)data + prefix, counter_size);
    return 0;
}
static int counter_reply(void *context, uint8_t seq, uint8_t cid, uint8_t *out,
                           uint32_t *len, uint32_t ms) {
    (void)context; (void)cid; (void)ms;
    const mt7921_chip_profile_t *profile = mt7921_chip_profile(counter_chip);
    uint8_t raw[512] = {0};
    unsigned size = profile->mcu_rxd_len;
    if (thermal_test_action >= 0) {
        uint32_t value = thermal_test_action == MT_THERMAL_TEMPERATURE ? UINT32_C(0xfffffffb) : 68;
        unsigned at = size + (counter_chip == MT_CHIP_MT7925 ? 12 : 4);
        for (unsigned i = 0; i < 4; i++) raw[at + i] = (uint8_t)(value >> (8 * i));
        if (counter_chip == MT_CHIP_MT7925) raw[size + 6] = 12;
        size += counter_chip == MT_CHIP_MT7925 ? 16 : 8;
        raw[counter_chip == MT_CHIP_MT7925 ? 36 : 28] = counter_chip == MT_CHIP_MT7925 ? 0x35 : 0xed;
    } else if (counter_chip == MT_CHIP_MT7921) {
        raw[size + 28] = (uint8_t)(100 + counter_payload[4]);
        size += 32;
    } else {
        for (unsigned at = 4; at + 8 <= counter_size && counter_payload[at + 2] == 8; at += 8) {
            memcpy(raw + size, counter_payload + at, 8);
            raw[size + 8] = (uint8_t)(100 + counter_payload[at + 4]);
            size += 16;
        }
    }
    if (counter_failure == 2) size = profile->mcu_rxd_len + 1;
    raw[0] = (uint8_t)size; raw[1] = (uint8_t)(size >> 8);
    raw[3] = PKT_TYPE_RX_EVENT << 3;
    raw[profile->rxd_seq_offset] = seq;
    if (counter_failure == 5) raw[0] = 1; /* valid bytes outside declared DMA */
    if (counter_failure == 6) raw[profile->rxd_seq_offset] = (uint8_t)(seq % 15 + 1);
    if (*len < size) return -1;
    memcpy(out, raw, size); *len = size;
    return 0;
}
/* Exercises the real read wrapper/encoders with fake USB and matched reply bodies.
 * Failure cases must leave caller output untouched, including partial EXT reads. */
int parity_counter_read(int chip, int mode) {
    thermal_test_action = -1;
    mt7921_dev_t dev = {0};
    dev.usb.chip = chip;
    mt7921_mcu_init(&dev.mcu, &dev.usb);
    dev.mcu.write_bulk = counter_write;
    dev.mcu.session_wait = counter_reply;
    counter_chip = chip; counter_failure = mode; counter_writes = 0;
    int names[MT_MIB_MAX]; size_t count = 0;
    for (int c = MT_COUNTER_RX_MPDU; c <= MT_COUNTER_IDLE_SLOTS; c++)
        if (mt_counter_descriptor(chip, c)) names[count++] = c;
    if (mode == 3) names[count++] = 999; /* reject entire list before writing */
    if (mode == 4) names[count++] = names[0];
    mt_counter_sample_t sample, before;
    memset(&sample, 0xA5, sizeof(sample)); memcpy(&before, &sample, sizeof(sample));
    int result = mt_counter_read(&dev, names, count, &sample);
    bool failed = mode >= 2 || (mode == 1 && chip == MT_CHIP_MT7921);
    if (failed) {
        if (!result || memcmp(&sample, &before, sizeof(sample))) return 1;
        if ((mode == 3 || mode == 4) && counter_writes) return 2;
    } else {
        if (result || sample.raw.count != count || sample.raw.closed_us < sample.raw.opened_us) return 3;
        if (counter_writes != (chip == MT_CHIP_MT7925 ? 1U : count)) return 4;
        for (size_t i = 0; i < count; i++)
            if (sample.raw.values[i] != 100 + sample.descriptors[i]->offset ||
                sample.raw.offsets[i] != sample.descriptors[i]->offset) return 5;
    }
    return 0;
}

int parity_thermal_read(int chip, int action, int mode) {
    mt7921_usb_t usb = {.chip = chip};
    mt7921_mcu_t mcu;
    mt7921_mcu_init(&mcu, &usb);
    mcu.write_bulk = counter_write; mcu.session_wait = counter_reply;
    counter_chip = chip; counter_failure = mode; counter_writes = 0;
    thermal_test_action = action;
    mt_thermal_sample_t sample, before;
    memset(&sample, 0xa5, sizeof(sample)); memcpy(&before, &sample, sizeof(sample));
    int result = mt_thermal_read(&mcu, action, &sample);
    bool unsupported = (chip == MT_CHIP_MT7921 && action != MT_THERMAL_TEMPERATURE) || action > 1;
    if (mode || unsupported) {
        if (!result || memcmp(&sample, &before, sizeof(sample))) return 1;
        if (unsupported && counter_writes) return 2;
    } else {
        if (result || counter_writes != 1 || sample.chip != chip || sample.action != action ||
            sample.closed_us < sample.opened_us) return 3;
        if (action == MT_THERMAL_TEMPERATURE) {
            if (!sample.has_temperature || sample.reported_temperature_c != -5 || sample.raw != UINT32_C(0xfffffffb)) return 4;
            int32_t value = 99;
            if (mt7921_get_temperature(&mcu, &value) || value != -5) return 5;
        } else if (sample.has_temperature || sample.raw != 68) return 6;
    }
    thermal_test_action = -1;
    return 0;
}

/* Fixed scalar output keeps Python tests independent of C struct padding. */
int parity_rx(const unsigned char *raw, unsigned len, int chip, unsigned *v) {
    mt7921_rxd_frame_t frame;
    int result = mt7921_rxd_decoder_for_chip(chip)(raw, len, &frame);
    if (result) return result;
    v[0] = frame.has_timestamp;
    v[1] = frame.timestamp;
    v[2] = frame.group_mask;
    v[3] = frame.g3_words;
    v[4] = frame.g5_words;
    v[5] = frame.frame ? (unsigned)(frame.frame - raw) : 0;
    v[6] = frame.frame_len;
    memcpy(v + 7, frame.g3, sizeof(frame.g3));
    memcpy(v + 11, frame.g5, sizeof(frame.g5));
    return 0;
}

typedef struct { uint32_t reg; int step, fail; } fake_reg_t;
static int fake_read(void *ctx, uint32_t addr, uint32_t *v) {
    (void)addr;
    fake_reg_t *f = ctx;
    if (++f->step == f->fail) return -1;
    *v = f->reg;
    return 0;
}
static int fake_write(void *ctx, uint32_t addr, uint32_t v) {
    (void)addr;
    fake_reg_t *f = ctx;
    f->reg = v; /* emulate a write that reaches hardware but loses its reply */
    return ++f->step == f->fail ? -1 : 0;
}
int parity_g5_fault(int fail, int initially_enabled) {
    uint32_t old = 0x02773400 | (initially_enabled ? 1U << 23 : 0);
    fake_reg_t reg = {old, 0, fail};
    mt_g5_guard_t guard = {0};
    mt_radio_reg_io_t io = {&reg, fake_read, fake_write, NULL};
    int ret = mt_g5_begin(&guard, io);
    if ((fail >= 1 && fail <= 3) != (ret != 0)) return 1;
    reg.reg ^= 1; /* another register field must survive restoration */
    int restored = mt_g5_restore(&guard);
    if (restored && !guard.active) return 2;
    reg.fail = 0;
    if (mt_g5_restore(&guard) || guard.active || reg.reg != (old ^ 1)) return 3;
    return 0;
}

static int fake_rx_step, fake_rx_mode, fake_rx_chip;
static int fake_bulk(mt7921_usb_t *usb, uint8_t ep, void *data, uint32_t *len, uint32_t ms) {
    (void)usb; (void)ep; (void)ms;
    if (fake_rx_mode == 1) return MT7921_ERR_TIMEOUT;
    if (fake_rx_mode == 2) return MT7921_ERR_IO;
    uint8_t *p = data;
    memset(p, 0, 64);
    p[0] = 64;
    p[3] = (fake_rx_step == 0 ? PKT_TYPE_NORMAL : PKT_TYPE_RX_EVENT) << 3;
    const mt7921_chip_profile_t *prof = mt7921_chip_profile(fake_rx_chip);
    p[prof->rxd_seq_offset] = fake_rx_step < 2 ? 4 : 3;
    *len = 64;
    fake_rx_step++;
    return 0;
}
int parity_mcu_fault(int chip, int mode) {
    mt7921_usb_t usb = {0};
    usb.chip = chip;
    mt7921_mcu_t mcu;
    mt7921_mcu_init(&mcu, &usb);
    mcu.read_bulk = fake_bulk;
    fake_rx_step = 0; fake_rx_mode = mode; fake_rx_chip = chip;
    uint8_t reply[128];
    uint32_t len = mode == 3 ? 8 : sizeof(reply);
    int ret = mt7921_mcu_wait(&mcu, 3, 0x22, reply, &len, 1);
    if (mode) return ret != 0 ? 0 : 1;
    return ret || len != 64 || mcu.dropped_frames != 1 || mcu.stale_events != 1;
}

int parity_txs(int chip, const unsigned char *raw, unsigned len, int *v) {
    mt_tx_status_t out[16];
    int n = mt_tx_status_parse(chip, raw, len, out, 16);
    if (n <= 0) return n;
    for (int i = 0; i < n; i++) {
        int *p = v + i * 10;
        p[0] = out[i].format; p[1] = out[i].rate_raw;
        p[2] = out[i].power_raw; p[3] = out[i].power_signed;
        p[4] = out[i].sequence; p[5] = out[i].pid;
        p[6] = out[i].ack_error_bits; p[7] = out[i].error_bits_16_22;
        p[8] = out[i].has_tx_count; p[9] = out[i].tx_count;
    }
    return n;
}

typedef struct { unsigned writes, reads, pauses, mode; uint32_t words[6]; } fake_table_t;
static int table_write(void *ctx, uint32_t addr, uint32_t v) {
    fake_table_t *f = ctx;
    if (f->writes >= 3) return -1;
    f->words[2 * f->writes] = addr;
    f->words[2 * f->writes + 1] = v;
    return ++f->writes == f->mode ? -1 : 0;
}
static int table_read(void *ctx, uint32_t addr, uint32_t *v) {
    (void)addr;
    fake_table_t *f = ctx;
    f->reads++;
    if (f->mode == 4) return -1;
    *v = f->mode == 5 ? 1U << 31 : 0x10012;
    return 0;
}
static void table_pause(void *ctx, unsigned ms) {
    fake_table_t *f = ctx;
    f->pauses += ms;
}
int parity_rate_table(int rate, unsigned mode, unsigned *words) {
    fake_table_t f = {.mode = mode};
    mt_radio_reg_io_t io = {&f, table_read, table_write, table_pause};
    int ret = mt_probe_rate_table(io, rate);
    memcpy(words, f.words, sizeof(f.words));
    words[6] = f.writes; words[7] = f.reads; words[8] = f.pauses;
    return ret;
}

static unsigned vendor_calls, vendor_timeout, vendor_mode;
static IOReturn vendor_request(void *self, IOUSBDevRequestTO *r) {
    (void)self;
    vendor_calls++;
    if (!r->noDataTimeout || r->noDataTimeout > 25 ||
        r->completionTimeout != r->noDataTimeout || r->wLenDone) return kIOReturnBadArgument;
    vendor_timeout = r->completionTimeout;
    if (vendor_mode == 1) return kIOReturnTimeout;
    if (vendor_mode == 2) { r->wLenDone = 2; return kIOReturnSuccess; }
    memset(r->pData, 0xff, r->wLength);
    r->wLenDone = r->wLength;
    return kIOReturnSuccess;
}
int parity_vendor_timeout(unsigned mode) {
    IOUSBDeviceInterface182 interface = {0};
    interface.DeviceRequestTO = vendor_request;
    IOUSBDeviceInterface182 *pointer = &interface;
    mt7921_usb_t usb = {0}; usb.dev = &pointer;
    uint32_t value = 0;
    vendor_calls = vendor_timeout = 0; vendor_mode = mode;
    int ret = mt7921_usb_vendor_req(&usb, 0x63, 0xc0, 0, 0, &value, 4, 25);
    if (!vendor_calls || !vendor_timeout || vendor_calls > 10) return 1;
    if (mode == 1) return ret == -1 ? 0 : 2;
    if (mode == 2) return ret == 2 ? 0 : 3;
    return ret == 4 && value == UINT32_MAX ? 0 : 4;
}
