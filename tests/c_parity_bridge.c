/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Synthetic-test bridge only; never opens a USB device. */
#include "mt7921_rxd.h"
#include "mt7921_chip.h"
#include "mt7921_radio.h"
#include <string.h>

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
