/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#ifndef MT76_HISTOGRAM_H
#define MT76_HISTOGRAM_H
#include "mt7921_chip.h"
#include <stddef.h>
#include <stdint.h>

enum { MT_HISTOGRAM_LEGACY_ORDINARY=0, MT_HISTOGRAM_FIRMWARE_TIMER=1 };
typedef struct {
    int chip, source;
    unsigned view_count;
    uint32_t bins[2][11];
    uint64_t totals[2];
    int8_t threshold_labels_raw[10];
} mt_histogram_bins_t;

/* Pure pinned-profile records, no I/O or acquisition ownership. Raw view indices
 * and firmware threshold labels are NOT calibrated antenna/dBm/occupancy labels.
 * Totals are collected samples, not full-dwell coverage. Output unchanged on error. */
int mt_histogram_request(int chip, uint8_t *out, size_t capacity);
int mt_histogram_ack(int chip, const uint8_t *raw, size_t len, uint8_t sequence, uint32_t *status);
int mt_histogram_event(int chip, const uint8_t *raw, size_t len, mt_histogram_bins_t *out);
/* Exactly44 little-endian bytes from the already stopped MT7921 ordinary bank. */
int mt_histogram_legacy(int chip, const uint8_t *raw, size_t len, mt_histogram_bins_t *out);
#endif
