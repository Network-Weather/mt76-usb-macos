/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#ifndef MT76_HISTOGRAM_ACQUISITION_H
#define MT76_HISTOGRAM_ACQUISITION_H
#include "mt76_histogram.h"
#include "mt7921_radio.h"

typedef struct {
    mt_radio_reg_io_t registers;
    void *command_ctx;
    int (*activate)(void *); /* MT7925: fixed UNI36/tag2, checked ACK/status */
} mt_histogram_io_t;
typedef struct {
    mt_histogram_io_t io;
    mt7921_dev_t *dev; /* nonnull only for device wrapper; must outlive guard */
    int chip;
    uint32_t saved[4], channel_key;
    uint64_t command_open_us, command_closed_us;
    bool active, pending, ready, needs_reload;
} mt_histogram_guard_t;
typedef struct {
    mt_histogram_bins_t bins;
    uint64_t command_open_us, command_closed_us, read_open_us, read_closed_us;
    bool coverage_known; /* always false for current profiles */
    double coverage_fraction; /* ignored when !coverage_known */
    unsigned sample_period_ns; /* zero = unknown, never inferred from totals */
} mt_histogram_sample_t;

/* Zero-initialize guard. One owner/device, serialized methods, no reset/retune
 * or out-of-band histogram operations. Use session callbacks if it owns USB.
 * Caller bounds elapsed acquisition and routes the MT7925 event (no queue reads).
 * History is irreversibly reset. active remains true after a partially failed
 * begin; needs_reload remains true even after successful restoration. */
int mt_histogram_begin(mt_histogram_guard_t *guard, int chip, mt_histogram_io_t io);
int mt_histogram_begin_device(mt7921_dev_t *dev, mt_histogram_guard_t *guard);
/* Legacy: raw=NULL,len=0. Modern: exact complete async event; checks stopped
 * controls and event/bank agreement. Output unchanged on error. */
int mt_histogram_finish(mt_histogram_guard_t *guard, const uint8_t *raw, size_t len,
                       mt_histogram_sample_t *out);
/* Modern pending acquisitions refuse WITHOUT I/O: stop USB worker and reload
 * firmware instead of racing an armed timer. Legacy can explicitly stop. */
int mt_histogram_restore(mt_histogram_guard_t *guard);
#endif
