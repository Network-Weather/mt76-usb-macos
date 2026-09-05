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
