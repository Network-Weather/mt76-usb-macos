/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Fake USB replay. No firmware, radio, or ambient identifiers. */
#include "mt76_session.h"
#include "mt76_probe_metrics.h"
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int mode, step, writes, chip, reply_seq;
static atomic_int entered, released;
static pthread_t reader;
static bool reader_set;
static void packet(uint8_t *p, unsigned type, unsigned seq, unsigned marker) {
    memset(p, 0, 64); p[0] = 64; p[3] = (uint8_t)(type << 3);
    p[chip == MT_CHIP_MT7925 ? 37 : 29] = (uint8_t)seq; p[63] = (uint8_t)marker;
}
static int read_fake(mt7921_usb_t *usb, uint8_t ep, void *data, uint32_t *len, uint32_t ms) {
    (void)usb;
    assert(ep == MT_ROLE_PKT_RX && *len == MT_SESSION_PACKET_CAPACITY && ms <= 50);
    if (reader_set) assert(pthread_equal(reader, pthread_self()));
    reader = pthread_self(); reader_set = true;
    if (mode == 5) return MT7921_ERR_IO;
    if (step < 0 || mode == 1) { usleep(ms * 1000); return MT7921_ERR_TIMEOUT; }
    uint8_t *p = data;
    if (step < 10) packet(p, PKT_TYPE_NORMAL, 0, (unsigned)step);
    else if (step == 10) packet(p, 0, 0, 0);
    else if (step == 11) packet(p, PKT_TYPE_RX_EVENT, (unsigned)(reply_seq % 15 + 1), 0);
    else {
        packet(p, PKT_TYPE_RX_EVENT, (unsigned)reply_seq, 0);
        step = -2;
    }
    step++; *len = 64;
    return 0;
}
static int write_fake(mt7921_usb_t *usb, uint8_t ep, const void *data, uint32_t len, uint32_t ms) {
    (void)usb; (void)ep; (void)data; (void)len; (void)ms;
    assert(reader_set && pthread_equal(reader, pthread_self()));
    writes++; step = 0;
    reply_seq = ((const uint8_t *)data)[43];
    return mode == 2 ? -1 : 0;
}
static int command(mt7921_dev_t *dev, void *ctx) {
    (void)ctx;
    uint8_t reply[128]; uint32_t len = mode == 3 ? 8 : sizeof(reply);
    int result = mt7921_mcu_send(&dev->mcu, 0x44, NULL, 0, true, reply, &len, mode == 1 ? 10 : 1000);
    /* An error swallowed by a legacy helper must still fault the session. */
    return mode == 1 ? 0 : result;
}
static int blocking(mt7921_dev_t *dev, void *ctx) {
    (void)dev; (void)ctx;
    atomic_store(&entered, 1);
    while (!atomic_load(&released)) usleep(1000);
    return 0;
}
static void *caller(void *s) {
    assert(mt_session_call(s, blocking, NULL, 1000, false) != 0);
    return NULL;
}
int session_replay_test(int test_chip, int test_mode) {
    mt_probe_clock_t clock = {0};
    mt_probe_clock_observe(&clock, UINT32_C(0xfffffff0), 1000000000);
    mt_probe_clock_observe(&clock, 16, 1000032000);
    assert(clock.wrap_candidates == 1 && !clock.backsteps);
    mt_probe_clock_observe(&clock, 15, 1000042000);
    assert(clock.backsteps == 1 && clock.wrap_candidates == 1);
    mt_probe_clock_observe(&clock, 99, UINT64_C(3000000000000));
    assert(clock.ambiguous_gaps == 1);
    mt_probe_clock_observe(&clock, 98, 1); /* host reorder cannot look like a wrap */
    assert(clock.ambiguous_gaps == 2 && clock.backsteps == 2);
    chip = test_chip; mode = test_mode; step = -1; writes = 0; reader_set = false;
    mt7921_dev_t dev = {0};
    dev.usb.chip = chip;
    mt7921_mcu_init(&dev.mcu, &dev.usb);
    dev.mcu.evt_ep4 = true; dev.session_ready = true;
    dev.mcu.read_bulk = read_fake; dev.mcu.write_bulk = write_fake;
    mt76_session_t *s = mt_session_start(&dev, 2, 1);
    assert(s);
    mt_session_packet_t p;
    mt_session_stats_t stats;
    assert(mt7921_rx_read(&dev, &p, &(uint32_t){sizeof(p)}, 1) != 0);
    assert(mt7921_mcu_next_seq(&dev.mcu) == 0);
    assert(mt_session_destroy(s) != 0);
    if (mode == 4) {
        atomic_store(&entered, 0); atomic_store(&released, 0);
        pthread_t client;
        assert(!pthread_create(&client, NULL, caller, s));
        while (!atomic_load(&entered)) usleep(1000);
        assert(mt_session_call(s, command, NULL, 100, false) == MT_SESSION_BUSY);
        assert(mt_session_stop(s, 1) != 0);
        assert(dev.usb.session_context == s);
        atomic_store(&released, 1);
        pthread_join(client, NULL);
    } else if (mode == 6) {
        for (int i = 0; i < 32; i++) assert(!mt_session_call(s, command, NULL, 500, false));
        assert(dev.mcu.msg_seq == 2);
        mt_session_snapshot(s, &stats);
        assert(stats.commands_completed == 32 && stats.replies_matched == 32);
        assert(stats.frames_received == 320 && stats.frames_dropped == 318);
    } else if (mode == 5) {
        for (int i = 0; i < 1000; i++) {
            mt_session_snapshot(s, &stats);
            if (stats.state == MT_SESSION_FAILED) break;
            usleep(1000);
        }
        assert(stats.state == MT_SESSION_FAILED && stats.usb_errors == 1);
    } else {
        int result = mt_session_call(s, command, NULL, 500, true);
        assert((result != 0) == (mode != 0));
        mt_session_snapshot(s, &stats);
        if (!mode) {
            assert(stats.frames_received == 10 && stats.frames_dropped == 8);
            assert(stats.events_received == 2 && stats.events_dropped == 1);
            assert(stats.replies_matched == 1 && stats.unmatched_replies == 1);
            assert(stats.generation == 1 && dev.mcu.dropped_frames == 0);
            for (unsigned i = 0; i < 2; i++) {
                assert(!mt_session_read(s, &p, false, 0));
                assert(p.raw[63] == i && p.transitioning && p.generation == 0);
                assert(p.epoch_ns == stats.epoch_ns);
            }
            assert(mt_session_read(s, &p, false, 0) == 1);
        } else {
            assert(stats.state == MT_SESSION_FAILED);
            assert(mt_session_call(s, command, NULL, 100, false) != 0);
            assert(writes == 1);
        }
    }
    assert(!mt_session_stop(s, 1000));
    mt_session_snapshot(s, &stats);
    assert(stats.state == ((!mode || mode == 6) ? MT_SESSION_CLOSED : MT_SESSION_FAILED) || mode == 4);
    assert(dev.usb.session_context == NULL);
    assert(mt_session_start(&dev, 2, 1) == NULL);
    assert(!mt_session_destroy(s));
    return 0;
}
#ifndef MT_SESSION_NO_MAIN
int main(void) {
    for (int c = 0; c < 2; c++) for (int m = 0; m < 7; m++) session_replay_test(c, m);
    puts("native session: both chips, overflow/replies/failure/cancellation passed");
    return 0;
}
#endif
