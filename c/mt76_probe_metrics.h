/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#ifndef MT76_PROBE_METRICS_H
#define MT76_PROBE_METRICS_H
#include <stdbool.h>
#include <stdint.h>

/* Diagnostic only: no timestamp extension or reset inference. A near-boundary
 * decrease with a plausible modulo delta is a wrap candidate, not proof of one. */
typedef struct {
    bool seen;
    uint32_t first, last;
    uint64_t last_host_ns, wrap_candidates, backsteps, ambiguous_gaps;
} mt_probe_clock_t;

static inline void mt_probe_clock_observe(mt_probe_clock_t *clock, uint32_t value, uint64_t host_ns) {
    if (!clock->seen) {
        clock->seen = true; clock->first = value;
    } else {
        bool ordered = host_ns >= clock->last_host_ns;
        uint64_t elapsed_us = ordered ? (host_ns - clock->last_host_ns) / 1000 : UINT64_MAX;
        if (elapsed_us >= UINT64_C(2147483648)) clock->ambiguous_gaps++;
        if (value < clock->last) {
            uint32_t delta = value - clock->last;
            if (clock->last >= UINT32_C(0xf0000000) && value <= UINT32_C(0x0fffffff) &&
                elapsed_us < UINT64_C(60000000) && delta <= elapsed_us + UINT64_C(5000000))
                clock->wrap_candidates++;
            else clock->backsteps++;
        }
    }
    clock->last = value; clock->last_host_ns = host_ns;
}
#endif
