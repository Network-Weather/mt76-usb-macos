/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#include "mt76_session.h"
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

struct mt76_session {
    mt7921_dev_t *dev;
    pthread_t worker, owner;
    pthread_mutex_t lock;
    pthread_cond_t changed;
    bool ready, exited, joined, stopping;
    bool command_busy, command_done, retune, transitioning;
    int command_result;
    int (*operation)(mt7921_dev_t *, void *);
    void *context;
    uint64_t deadline_ns;
    unsigned frame_capacity, event_capacity, frame_head, event_head;
    mt_session_packet_t *frames, *events;
    mt_session_stats_t stats;
};

static uint64_t now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000 + (uint64_t)t.tv_nsec;
}
static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static void wait_slice(mt76_session_t *s, uint64_t end) {
    uint64_t now = now_ns();
    if (now >= end) return;
    uint64_t ns = end - now;
    if (ns > 50000000) ns = 50000000;
    struct timespec delay = {(time_t)(ns / 1000000000), (long)(ns % 1000000000)};
    /* macOS relative wait avoids wall-clock adjustments changing deadlines. */
    pthread_cond_timedwait_relative_np(&s->changed, &s->lock, &delay);
}
static void fail_locked(mt76_session_t *s) {
    s->stopping = true;
    s->stats.state = MT_SESSION_FAILED;
    s->stats.channel_known = false;
    pthread_cond_broadcast(&s->changed);
}
static void fail(void *context) {
    mt76_session_t *s = context;
    pthread_mutex_lock(&s->lock);
    fail_locked(s);
    pthread_mutex_unlock(&s->lock);
}
static uint32_t io_timeout(void *context, uint32_t requested) {
    mt76_session_t *s = context;
    pthread_mutex_lock(&s->lock);
    uint32_t result = requested;
    if (!requested || !s->ready || !pthread_equal(pthread_self(), s->owner) || s->stopping) {
        result = 0;
    } else if (s->deadline_ns) {
        uint64_t now = now_ns();
        if (now >= s->deadline_ns) {
            fail_locked(s);
            result = 0;
        } else {
            uint64_t left = (s->deadline_ns - now + 999999) / 1000000;
            if (left < result) result = (uint32_t)left;
        }
    } else if (result > 50) result = 50;
    pthread_mutex_unlock(&s->lock);
    return result;
}

int mt_session_packet_kind(const uint8_t *raw, uint32_t len, int chip) {
    if (!raw || len < 4) return MT_PACKET_MALFORMED;
    uint32_t word = le32(raw), size = word & 0xFFFF;
    if (size < 4 || size > len) return MT_PACKET_MALFORMED;
    unsigned type = word >> 27, flag = (word >> RXD0_PKT_FLAG_SHIFT) & RXD0_PKT_FLAG_MASK;
    if (type == PKT_TYPE_NORMAL || (type == PKT_TYPE_RX_EVENT && flag == PKT_FLAG_NORMAL_MCU) ||
        (chip == MT_CHIP_MT7925 && ((word >> 16) & 0x380F) == 0x3801))
        return size >= 32 ? MT_PACKET_FRAME : MT_PACKET_MALFORMED;
    if (type == PKT_TYPE_RX_EVENT)
        return size >= (chip == MT_CHIP_MT7925 ? 44U : 36U) ? MT_PACKET_REPLY : MT_PACKET_MALFORMED;
    return MT_PACKET_STATUS;
}

static int receive(mt76_session_t *s, mt_session_packet_t *p, uint32_t timeout) {
    timeout = io_timeout(s, timeout);
    if (!timeout) return -1;
    p->len = sizeof(p->raw);
    int result = s->dev->mcu.read_bulk(&s->dev->usb, MT_ROLE_PKT_RX, p->raw, &p->len, timeout);
    pthread_mutex_lock(&s->lock);
    if (result == MT7921_ERR_TIMEOUT) {
        s->stats.read_timeouts++;
        pthread_mutex_unlock(&s->lock);
        return 1;
    }
    if (result) {
        if (!s->stopping) { s->stats.usb_errors++; fail_locked(s); }
        pthread_mutex_unlock(&s->lock);
        return -1;
    }
    s->stats.transfers++;
    p->kind = p->len > sizeof(p->raw) ? MT_PACKET_MALFORMED :
              mt_session_packet_kind(p->raw, p->len, s->dev->usb.chip);
    if (p->kind == MT_PACKET_MALFORMED) {
        s->stats.malformed++;
        pthread_mutex_unlock(&s->lock);
        return 1;
    }
    p->len = le32(p->raw) & 0xFFFF;
    p->received_ns = now_ns();
    p->epoch_ns = s->stats.epoch_ns;
    p->generation = s->stats.generation;
    p->transitioning = s->transitioning;
    pthread_mutex_unlock(&s->lock);
    return 0;
}
static void enqueue(mt76_session_t *s, const mt_session_packet_t *p) {
    pthread_mutex_lock(&s->lock);
    bool frame = p->kind == MT_PACKET_FRAME;
    unsigned capacity = frame ? s->frame_capacity : s->event_capacity;
    unsigned head = frame ? s->frame_head : s->event_head;
    uint32_t *depth = frame ? &s->stats.frame_depth : &s->stats.event_depth;
    uint64_t *high = frame ? &s->stats.frames_high_water : &s->stats.events_high_water;
    if (frame) s->stats.frames_received++; else s->stats.events_received++;
    if (*depth == capacity) {
        if (frame) s->stats.frames_dropped++; else s->stats.events_dropped++;
    } else {
        mt_session_packet_t *packets = frame ? s->frames : s->events;
        /* Copy only live bytes; never export uninitialized tail bytes. */
        mt_session_packet_t *target = &packets[(head + *depth) % capacity];
        target->len = p->len; target->received_ns = p->received_ns; target->epoch_ns = p->epoch_ns;
        target->generation = p->generation; target->transitioning = p->transitioning;
        target->kind = p->kind;
        memcpy(target->raw, p->raw, p->len);
        (*depth)++;
        if (*depth > *high) *high = *depth;
        pthread_cond_broadcast(&s->changed);
    }
    pthread_mutex_unlock(&s->lock);
}
static int wait_reply(void *context, uint8_t seq, uint8_t cid, uint8_t *reply,
                       uint32_t *reply_len, uint32_t timeout) {
    (void)cid; /* payload validation belongs to the command, EID need not equal CID */
    mt76_session_t *s = context;
    uint32_t budget = io_timeout(s, timeout);
    if (!budget) return -1;
    uint64_t end = now_ns() + (uint64_t)budget * 1000000;
    mt_session_packet_t packet;
    while (now_ns() < end) {
        uint64_t now = now_ns();
        if (now >= end) break;
        uint32_t left = (uint32_t)((end - now + 999999) / 1000000);
        int result = receive(s, &packet, left < 50 ? left : 50);
        if (result < 0) return -1;
        if (result) continue;
        if (packet.kind == MT_PACKET_REPLY) {
            if (packet.raw[s->dev->mcu.prof->rxd_seq_offset] == seq) {
                pthread_mutex_lock(&s->lock);
                s->stats.replies_matched++;
                pthread_mutex_unlock(&s->lock);
                if (reply && (!reply_len || *reply_len < packet.len)) { fail(s); return -1; }
                if (reply) { memcpy(reply, packet.raw, packet.len); *reply_len = packet.len; }
                return 0;
            }
            pthread_mutex_lock(&s->lock);
            s->stats.unmatched_replies++;
            pthread_mutex_unlock(&s->lock);
        }
        enqueue(s, &packet);
    }
    fail(s); /* even if a command helper swallows the error, no next sequence */
    return -1;
}
static void *run(void *context) {
    mt76_session_t *s = context;
    mt_session_packet_t packet;
    pthread_mutex_lock(&s->lock);
    s->owner = pthread_self(); s->ready = true;
    pthread_cond_broadcast(&s->changed);
    while (!s->stopping) {
        if (s->command_busy && !s->command_done) {
            s->transitioning = s->retune;
            if (s->retune) s->stats.channel_known = false;
            int (*operation)(mt7921_dev_t *, void *) = s->operation;
            void *arg = s->context;
            pthread_mutex_unlock(&s->lock);
            int result = io_timeout(s, 50) ? operation(s->dev, arg) : -1;
            if (!io_timeout(s, 50)) result = -1;
            pthread_mutex_lock(&s->lock);
            if (result) fail_locked(s);
            else {
                s->stats.commands_completed++;
                if (s->retune) {
                    s->stats.generation++;
                    s->stats.channel_known = s->dev->tuned;
                    s->stats.band = s->dev->tuned_band;
                    s->stats.control = s->dev->tuned_control;
                    s->stats.center = s->dev->tuned_center;
                    s->stats.width_mhz = s->dev->tuned_width;
                }
            }
            s->transitioning = false;
            s->deadline_ns = 0;
            s->command_result = result;
            s->command_done = true;
            pthread_cond_broadcast(&s->changed);
        } else {
            pthread_mutex_unlock(&s->lock);
            int result = receive(s, &packet, 50);
            if (!result) {
                if (packet.kind == MT_PACKET_REPLY) {
                    pthread_mutex_lock(&s->lock);
                    s->stats.unmatched_replies++;
                    pthread_mutex_unlock(&s->lock);
                }
                enqueue(s, &packet);
            }
            pthread_mutex_lock(&s->lock);
            if (result < 0 && !s->stopping) fail_locked(s);
        }
    }
    if (s->command_busy && !s->command_done) { s->command_result = -1; s->command_done = true; }
    if (s->stats.state != MT_SESSION_FAILED) s->stats.state = MT_SESSION_CLOSED;
    s->exited = true;
    pthread_cond_broadcast(&s->changed);
    pthread_mutex_unlock(&s->lock);
    return NULL;
}

mt76_session_t *mt_session_start(mt7921_dev_t *dev, unsigned frames, unsigned events) {
    if (!dev || !dev->session_ready || !dev->mcu.evt_ep4 || dev->usb.session_context ||
        !frames || frames > 4096 || !events || events > 4096) return NULL;
    mt76_session_t *s = calloc(1, sizeof(*s));
    if (!s) return NULL;
    s->frames = calloc(frames, sizeof(*s->frames));
    s->events = calloc(events, sizeof(*s->events));
    if (!s->frames || !s->events) goto bad;
    if (pthread_mutex_init(&s->lock, NULL)) goto bad;
    if (pthread_cond_init(&s->changed, NULL)) { pthread_mutex_destroy(&s->lock); goto bad; }
    s->dev = dev; s->frame_capacity = frames; s->event_capacity = events;
    s->stats.state = MT_SESSION_RUNNING; s->stats.epoch_ns = now_ns();
    s->stats.channel_known = dev->tuned;
    s->stats.band = dev->tuned_band; s->stats.control = dev->tuned_control;
    s->stats.center = dev->tuned_center; s->stats.width_mhz = dev->tuned_width;
    dev->session_ready = false;
    dev->usb.session_context = s; dev->usb.session_timeout = io_timeout; dev->usb.session_fail = fail;
    dev->mcu.session_context = s; dev->mcu.session_wait = wait_reply;
    if (pthread_create(&s->worker, NULL, run, s)) {
        dev->usb.session_context = NULL; dev->usb.session_timeout = NULL; dev->usb.session_fail = NULL;
        dev->mcu.session_context = NULL; dev->mcu.session_wait = NULL;
        pthread_cond_destroy(&s->changed); pthread_mutex_destroy(&s->lock);
        goto bad;
    }
    pthread_mutex_lock(&s->lock);
    while (!s->ready) pthread_cond_wait(&s->changed, &s->lock);
    pthread_mutex_unlock(&s->lock);
    return s;
bad:
    free(s->frames); free(s->events); free(s);
    return NULL;
}

int mt_session_call(mt76_session_t *s, int (*operation)(mt7921_dev_t *, void *),
                    void *context, uint32_t timeout_ms, bool retune) {
    if (!s || !operation || !timeout_ms) return -1;
    pthread_mutex_lock(&s->lock);
    if (s->stopping || pthread_equal(pthread_self(), s->owner)) {
        pthread_mutex_unlock(&s->lock); return -1;
    }
    if (s->command_busy) { pthread_mutex_unlock(&s->lock); return MT_SESSION_BUSY; }
    s->command_busy = true; s->command_done = false;
    s->operation = operation; s->context = context; s->retune = retune;
    s->deadline_ns = now_ns() + (uint64_t)timeout_ms * 1000000;
    while (!s->command_done) {
        if (now_ns() >= s->deadline_ns) {
            fail_locked(s);
            /* Must retain callback/context lifetime until the worker returns. */
            pthread_cond_wait(&s->changed, &s->lock);
        } else wait_slice(s, s->deadline_ns);
    }
    int result = s->command_result;
    s->command_busy = false;
    pthread_mutex_unlock(&s->lock);
    return result;
}

int mt_session_read(mt76_session_t *s, mt_session_packet_t *out, bool events, uint32_t timeout_ms) {
    if (!s || !out) return -1;
    uint64_t end = now_ns() + (uint64_t)timeout_ms * 1000000;
    pthread_mutex_lock(&s->lock);
    if (pthread_equal(pthread_self(), s->owner)) { pthread_mutex_unlock(&s->lock); return -1; }
    uint32_t *depth = events ? &s->stats.event_depth : &s->stats.frame_depth;
    while (!*depth && !s->stopping && now_ns() < end) wait_slice(s, end);
    if (!*depth) { pthread_mutex_unlock(&s->lock); return 1; }
    unsigned *head = events ? &s->event_head : &s->frame_head;
    unsigned capacity = events ? s->event_capacity : s->frame_capacity;
    mt_session_packet_t *packets = events ? s->events : s->frames;
    *out = packets[*head];
    *head = (*head + 1) % capacity; (*depth)--;
    if (events) s->stats.events_delivered++; else s->stats.frames_delivered++;
    pthread_mutex_unlock(&s->lock);
    return 0;
}
void mt_session_snapshot(mt76_session_t *s, mt_session_stats_t *out) {
    if (!s || !out) return;
    pthread_mutex_lock(&s->lock); *out = s->stats; pthread_mutex_unlock(&s->lock);
}
int mt_session_stop(mt76_session_t *s, uint32_t timeout_ms) {
    if (!s) return -1;
    uint64_t end = now_ns() + (uint64_t)timeout_ms * 1000000;
    pthread_mutex_lock(&s->lock);
    if (pthread_equal(pthread_self(), s->owner)) { pthread_mutex_unlock(&s->lock); return -1; }
    s->stopping = true;
    if (s->stats.state == MT_SESSION_RUNNING) s->stats.state = MT_SESSION_STOPPING;
    pthread_cond_broadcast(&s->changed);
    while (!s->exited && now_ns() < end) wait_slice(s, end);
    if (!s->exited) { pthread_mutex_unlock(&s->lock); return -1; }
    pthread_mutex_unlock(&s->lock);
    if (!s->joined) { pthread_join(s->worker, NULL); s->joined = true; }
    s->dev->usb.session_context = NULL; s->dev->usb.session_timeout = NULL;
    s->dev->usb.session_fail = NULL;
    s->dev->mcu.session_context = NULL; s->dev->mcu.session_wait = NULL;
    return 0;
}
int mt_session_destroy(mt76_session_t *s) {
    if (!s) return 0;
    pthread_mutex_lock(&s->lock);
    bool safe = s->joined && !s->command_busy;
    pthread_mutex_unlock(&s->lock);
    if (!safe) return -1;
    pthread_cond_destroy(&s->changed); pthread_mutex_destroy(&s->lock);
    free(s->frames); free(s->events); free(s);
    return 0;
}
