/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Synthetic session boundary; no hardware or driver transport is linked. */
#include "../examples/measurements.c"
#include <assert.h>
#include <stdlib.h>
#include <string.h>

static uint64_t clock_us;
static int mode, generation;
static mt7921_dev_t device;
static mt_counter_descriptor_t descriptors[] = {
    {.name = "rx_mpdu", .unit = MT_COUNTER_COUNT},
    {.name = "primary_cca", .unit = MT_COUNTER_DURATION_TICKS},
};
uint64_t mt_radio_monotonic_us(void) { clock_us += 100000; return clock_us; }
int mt_session_read(mt76_session_t *s, mt_session_packet_t *p, bool events, uint32_t ms) {
    (void)s; (void)p; (void)ms; return events || mode == 3;
}
void mt_session_snapshot(mt76_session_t *s, mt_session_stats_t *out) {
    (void)s;
    *out = (mt_session_stats_t){.state = MT_SESSION_RUNNING, .epoch_ns = 1,
        .generation = generation, .control = 6, .frames_dropped = 3};
}
int mt_session_call(mt76_session_t *s, int (*op)(mt7921_dev_t *, void *),
                    void *ctx, uint32_t timeout, bool retune) {
    (void)s; assert(timeout == 3000 && !retune);
    if (mode == 1) return -1;
    int result = op(&device, ctx);
    if (mode == 2) generation++;
    return result;
}
int mt_counter_read(mt7921_dev_t *dev, const int *names, size_t n, mt_counter_sample_t *out) {
    (void)dev;
    assert(n == 2 && names[0] == MT_COUNTER_RX_MPDU && names[1] == MT_COUNTER_PRIMARY_CCA);
    memset(out, 0, sizeof(*out));
    out->raw.count = 2; out->raw.opened_us = 10; out->raw.closed_us = 20;
    out->descriptors[0] = &descriptors[0]; out->descriptors[1] = &descriptors[1];
    return 0;
}
int mt_thermal_read(mt7921_mcu_t *mcu, int action, mt_thermal_sample_t *out) {
    (void)mcu; assert(action == MT_THERMAL_TEMPERATURE);
    *out = (mt_thermal_sample_t){.has_temperature = true, .reported_temperature_c = 38,
        .opened_us = 21, .closed_us = 30};
    return 0;
}
int main(int argc, char **argv) {
    if (argc != 2) return 1;
    mode = atoi(argv[1]);
    /* Opaque identity only: stubs never dereference a session. */
    mt76_session_t *s = (mt76_session_t *)(void *)&device;
    assert(example_measurements(NULL, 1, stdout) == -1);
    assert(example_measurements(s, 0, stdout) == -1);
    assert(example_measurements(s, 61, stdout) == -1);
    int result = example_measurements(s, 1, stdout);
    assert(result == (mode == 1 || mode == 2 ? -1 : mode == 3 ? 2 : 0));
    return 0;
}
