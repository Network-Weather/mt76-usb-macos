/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
#ifndef MT7921_RADIO_H
#define MT7921_RADIO_H
#include "mt7921_dev.h"

#define MT_MIB_MAX 16
typedef struct {
    uint32_t offsets[MT_MIB_MAX];
    uint64_t values[MT_MIB_MAX];
    size_t count;
    unsigned counter_bits;
    uint64_t opened_us, closed_us; /* host monotonic; use midpoint for sampling */
    uint32_t dropped_frames;       /* frames consumed by this MCU round trip */
} mt_mib_sample_t;

/* Pure bounded wire helpers. EXT accepts one entry: this firmware's single-value
 * reply does NOT echo the offset. UNI requires a unique echoed entry for every
 * requested offset. No partial output on error; values have chip-specific units. */
int mt_mib_request(int chip, uint8_t band, const uint32_t *offsets, size_t count,
                   uint8_t *out, size_t capacity);
int mt_mib_parse(int chip, const uint8_t *body, size_t len,
                 const uint32_t *offsets, size_t count, uint64_t *values);
int mt_mib_read(mt7921_dev_t *dev, const uint32_t *offsets, size_t count,
                mt_mib_sample_t *sample);
/* Same firmware epoch only; rejects implausible wrap/reset deltas via max_delta.
 * A reset with a plausible positive delta cannot be detected from two values. */
bool mt_mib_delta(uint64_t before, uint64_t after, unsigned bits,
                  uint64_t max_delta, uint64_t *delta);
uint64_t mt_radio_monotonic_us(void);

/* Injectable register boundary used by restoration/timeout fault tests. */
typedef struct {
    void *ctx;
    int (*read)(void *, uint32_t, uint32_t *);
    int (*write)(void *, uint32_t, uint32_t);
    void (*pause_ms)(void *, unsigned);
} mt_radio_reg_io_t;
typedef struct {
    mt_radio_reg_io_t io;
    uint32_t saved_bit;
    bool active; /* remains true on failure until restoration succeeds */
} mt_g5_guard_t;

/* Opt-in only. Caller must restore even if begin fails with guard.active true.
 * Do not reuse an active guard or reset firmware during its lifetime. MT7921 only;
 * mt792x_mac_init_band disables this bit by default due to hardware issues. */
int mt_g5_begin(mt_g5_guard_t *guard, mt_radio_reg_io_t io);
int mt_g5_restore(mt_g5_guard_t *guard);
int mt_g5_begin_device(mt7921_dev_t *dev, mt_g5_guard_t *guard);
mt_radio_reg_io_t mt_radio_device_io(mt7921_dev_t *dev);
#endif
