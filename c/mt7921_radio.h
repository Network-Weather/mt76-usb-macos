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

/* Named MCU-only profile; docs/MT7925_MIB.md and SUBCHANNEL_MEASUREMENTS.md.
 * No inferred percentages, MMIO fallback, or dynamic firmware detection. */
enum {
    MT_COUNTER_RX_MPDU = 1, MT_COUNTER_RX_FCS_ERROR, MT_COUNTER_RX_MDRDY,
    MT_COUNTER_PRIMARY_CCA, MT_COUNTER_CCA_NAV_TX, MT_COUNTER_CCK_RX_DURATION,
    MT_COUNTER_OFDM_RX_DURATION, MT_COUNTER_PRIMARY_ED, MT_COUNTER_NAV,
    MT_COUNTER_IDLE_SLOTS
};
enum { MT_COUNTER_COUNT, MT_COUNTER_DURATION_TICKS, MT_COUNTER_SLOTS };
typedef struct {
    const char *name;
    int counter;
    uint32_t offset;
    int unit;
    unsigned wire_bits, hardware_bits, accumulator_bits, tick_ns;
    bool hardware_saturates;
} mt_counter_descriptor_t;
/* NULL for unsupported chip/name. Zero bits/tick_ns means UNKNOWN, not zero.
 * Static lifetime. Wire width != hardware/accumulator width; 9-us idle slots
 * can saturate before firmware reads them, so conversion cannot recover loss. */
const mt_counter_descriptor_t *mt_counter_descriptor(int chip, int counter);
typedef struct {
    mt_mib_sample_t raw;
    const mt_counter_descriptor_t *descriptors[MT_MIB_MAX];
} mt_counter_sample_t;
/* Validate the entire named request before I/O. Band0 only, pinned firmware.
 * Old chip: serial one-entry queries. New chip: one batch, not a simultaneous
 * latch. Caller owns device or uses mt_session_call; retain session epoch and
 * channel generation alongside this outer host interval. Output unchanged on
 * failure; unsupported names are not successful zero-valued measurements. */
int mt_counter_read(mt7921_dev_t *dev, const int *counters, size_t count,
                     mt_counter_sample_t *sample);

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

enum { MT_PROBE_CCK1, MT_PROBE_OFDM6, MT_PROBE_OFDM54 };
/* Pure descriptor builder for Probe Requests only, <=512 bytes. Connac2 supports
 * CCK1 (zero offset) and OFDM6 (0/-8/-16); connac3 OFDM6/54 (0/-8/-16/-32).
 * Units of power_code are experimental codes, NOT absolute dBm. DIS_MAT is always
 * set on connac3 to preserve the submitted source in the measured subset. */
int mt_probe_txwi(int chip, const uint8_t *frame, size_t len, unsigned sequence,
                  int rate, int power_code, uint8_t *out);
/* MT7925 table write, bounded 100 polls. Caller must reload firmware even on error. */
int mt_probe_rate_table(mt_radio_reg_io_t io, int rate);
int mt_probe_prepare(mt7921_dev_t *dev, int rate);
/* Requires successful mt7921_tune, supported measured channel/rate/width and table.
 * <=60 attempted writes per boot; >=50 ms spacing; no ACK. CLI must additionally
 * require explicit transmit acknowledgement. Single-owner, no concurrent retune. */
int mt_probe_transmit(mt7921_dev_t *dev, const uint8_t *frame, size_t len,
                      unsigned sequence, int rate, int power_code);

typedef struct {
    uint8_t format, power_raw, pid, ack_error_bits, error_bits_16_22;
    int16_t power_signed; /* signed representation only; NOT calibrated dBm */
    uint16_t rate_raw, sequence;
    bool has_tx_count;
    uint8_t tx_count;     /* connac3 format 0 only */
    bool has_timing;      /* connac3 raw layout; old-chip timing not promoted */
    uint8_t bandwidth_raw;
    bool rate_stbc, has_front_time;
    uint16_t tx_delay_raw; /* service/packet delay, NOT pure contention */
    uint32_t timestamp_raw; /* wrapping TXS clock, not RXD/host time */
    uint32_t front_time_raw; /* separate wrapping 25-bit clock, format0 only */
    unsigned timestamp_tick_ns, front_time_tick_ns, tx_delay_tick_ns;
    /* Nonzero ticks only for evidenced pinned MT7925 format0; zero = UNKNOWN.
     * No synchronized clock domains, exact latch points, or ranging claim. */
} mt_tx_status_t;
/* Packet type must be TXS (0). Strict DMA bounds and complete records; USB padding
 * beyond DMA length is ignored. Returns record count or -1, no partial output. */
int mt_tx_status_parse(int chip, const uint8_t *raw, size_t len,
                       mt_tx_status_t *out, size_t capacity);
#endif
