/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#ifndef MT76_SESSION_H
#define MT76_SESSION_H

#include "mt7921_dev.h"

#define MT_SESSION_PACKET_CAPACITY 16384
#define MT_SESSION_BUSY 2
enum { MT_PACKET_MALFORMED, MT_PACKET_FRAME, MT_PACKET_REPLY, MT_PACKET_STATUS };
enum { MT_SESSION_RUNNING, MT_SESSION_STOPPING, MT_SESSION_CLOSED, MT_SESSION_FAILED };

typedef struct mt76_session mt76_session_t;
typedef struct {
    uint8_t raw[MT_SESSION_PACKET_CAPACITY];
    uint32_t len, generation;
    uint64_t received_ns, epoch_ns;
    int kind;
    bool transitioning;
} mt_session_packet_t;
typedef struct {
    uint64_t transfers, read_timeouts, usb_errors, malformed;
    uint64_t frames_received, frames_delivered, frames_dropped, frames_high_water;
    uint64_t events_received, events_delivered, events_dropped, events_high_water;
    uint64_t replies_matched, unmatched_replies, commands_completed;
    uint64_t epoch_ns;
    uint32_t frame_depth, event_depth, generation;
    bool channel_known;
    uint8_t band, control, center;
    uint16_t width_mhz;
    int state;
} mt_session_stats_t;

/* Pure classifier shared with Python fixtures; validates DMA bounds before routing. */
int mt_session_packet_kind(const uint8_t *raw, uint32_t len, int chip);

/* Fresh bringup required. One worker owns USB until stop succeeds. No warm attach.
 * Queue capacities are 1..4096; drop newest, count every overflow. NULL on failure. */
mt76_session_t *mt_session_start(mt7921_dev_t *dev, unsigned frames, unsigned events);
/* One bounded command slot: concurrent callers get BUSY, never implicit allocation.
 * Callback/context remain valid until this returns. Driver callbacks must honor USB
 * deadlines. A timeout faults the session but cannot forcibly cancel arbitrary C;
 * call waits for callback exit to avoid a use-after-return of context memory.
 * Do not close/reset/reenter this API or perform slow output inside a callback. */
int mt_session_call(mt76_session_t *s, int (*operation)(mt7921_dev_t *, void *),
                    void *context, uint32_t timeout_ms, bool retune);
/* 0 packet, 1 quiet/closed-empty, -1 invalid. Queued records survive stop/failure. */
int mt_session_read(mt76_session_t *s, mt_session_packet_t *out, bool events,
                    uint32_t timeout_ms);
void mt_session_snapshot(mt76_session_t *s, mt_session_stats_t *out);
/* Immutable chip identity during session lifetime; -1 for NULL, no USB I/O. */
int mt_session_chip(const mt76_session_t *s);
/* Stop timeout leaves ownership attached. Retry later; do not free/close device.
 * Lifecycle calls (start/stop/destroy) must be serialized by the caller. */
int mt_session_stop(mt76_session_t *s, uint32_t timeout_ms);
/* Only succeeds after stop and when no command caller remains. */
int mt_session_destroy(mt76_session_t *s);

#endif
