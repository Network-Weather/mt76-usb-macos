/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Application composition example; not a new installed API or USB owner.
 * Caller freshly boots pinned firmware, tunes 2.4GHz channel6/20MHz, then starts
 * one mt_session. No concurrent retunes/consumers/callers during this function.
 * After return, caller must stop then destroy session BEFORE closing the device.
 * A failed stop retains ownership: do not free/close; retry orderly stop.
 * Build check: clang -Wall -Wextra -Werror -std=c11 -Ic -c examples/measurements.c
 * Link with the same driver objects/frameworks as c/mt76_session_probe.
 */
#include "mt76_session.h"
#include "mt7921_radio.h"
#include <inttypes.h>

typedef struct {
    mt_counter_sample_t counters;
    mt_thermal_sample_t thermal;
} example_sample_t;

static int measure(mt7921_dev_t *dev, void *ctx) {
    example_sample_t *sample = ctx;
    const int names[] = {MT_COUNTER_RX_MPDU, MT_COUNTER_PRIMARY_CCA};
    if (mt_counter_read(dev, names, 2, &sample->counters)) return -1;
    return mt_thermal_read(&dev->mcu, MT_THERMAL_TEMPERATURE, &sample->thermal);
}

/* 0 completed with RX, 2 completed without RX (inconclusive), -1 error.
 * Output is aggregate NDJSON, never packet bytes or ambient identifiers.
 * Classified RX packets are not a good-FCS decode guarantee.
 */
int example_measurements(mt76_session_t *session, unsigned seconds, FILE *output) {
    if (!session || !output || seconds < 1 || seconds > 60) return -1;
    uint64_t started = mt_radio_monotonic_us(), next = started, frames = 0;
    mt_session_packet_t packet;
    while (mt_radio_monotonic_us() - started < (uint64_t)seconds * 1000000) {
        int result = mt_session_read(session, &packet, false, 50);
        if (result < 0) return -1;
        if (!result) frames++;
        while (!mt_session_read(session, &packet, true, 0)) {}
        mt_session_stats_t before, after;
        mt_session_snapshot(session, &before);
        if (before.state != MT_SESSION_RUNNING) return -1;
        if (mt_radio_monotonic_us() < next) continue;
        example_sample_t sample;
        if (mt_session_call(session, measure, &sample, 3000, false)) return -1;
        mt_session_snapshot(session, &after);
        if (after.state != MT_SESSION_RUNNING || after.epoch_ns != before.epoch_ns ||
            after.generation != before.generation) return -1;
        /* RX_MPDU is a count; PRIMARY_CCA has unknown duration scaling.
         * Counter interval and thermal interval are separate host observations.
         */
        if (fprintf(output,
            "{\"event\":\"measurement\",\"schema\":1,\"epoch_ns\":%" PRIu64
            ",\"channel_generation\":%u,\"requested_control\":%u,"
            "\"frames_consumed\":%" PRIu64 ",\"counter_opened_us\":%" PRIu64
            ",\"counter_closed_us\":%" PRIu64 ",\"counters\":["
            "{\"name\":\"%s\",\"raw\":%" PRIu64 ",\"unit\":%d,\"tick_ns\":null},"
            "{\"name\":\"%s\",\"raw\":%" PRIu64 ",\"unit\":%d,\"tick_ns\":null}],"
            "\"reported_temperature_c\":%" PRId32 ",\"thermal_opened_us\":%" PRIu64
            ",\"thermal_closed_us\":%" PRIu64 ",\"channel_busy_fraction\":null,"
            "\"frames_dropped\":%" PRIu64 ",\"events_dropped\":%" PRIu64
            ",\"usb_errors\":%" PRIu64 "}\n",
            after.epoch_ns, after.generation, after.control, frames,
            sample.counters.raw.opened_us, sample.counters.raw.closed_us,
            sample.counters.descriptors[0]->name, sample.counters.raw.values[0],
            sample.counters.descriptors[0]->unit,
            sample.counters.descriptors[1]->name, sample.counters.raw.values[1],
            sample.counters.descriptors[1]->unit,
            sample.thermal.reported_temperature_c, sample.thermal.opened_us,
            sample.thermal.closed_us, after.frames_dropped, after.events_dropped,
            after.usb_errors) < 0 || fflush(output)) return -1;
        next = mt_radio_monotonic_us() + 1000000;
    }
    return frames ? 0 : 2;
}
