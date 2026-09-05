/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Passive native-session qualification; aggregate/redacted NDJSON only. */
#include "mt76_session.h"
#include "mt7921_radio.h"
#include "mt7921_rxd.h"
#include <CommonCrypto/CommonDigest.h>
#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>

static volatile sig_atomic_t stopping;
static void stop_handler(int sig) { (void)sig; stopping = 1; }
static void quiet(const char *fmt, ...) { (void)fmt; }
static int number(const char *s, long low, long high, unsigned *out) {
    char *end; errno = 0;
    long value = strtol(s, &end, 10);
    if (errno || !*s || *end || value < low || value > high) return -1;
    *out = (unsigned)value; return 0;
}
/* Same checksum-pinned local-file policy as mt76_radio_probe; never fetch blobs. */
static uint8_t *firmware(const char *dir, const char *name, const char *pin, size_t *len) {
    char path[4096], digest[65];
    int n = snprintf(path, sizeof(path), "%s/%s", dir, name);
    if (n < 0 || (size_t)n >= sizeof(path)) return NULL;
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END)) { fclose(f); return NULL; }
    long size = ftell(f);
    if (size <= 0 || size > 8 * 1024 * 1024 || fseek(f, 0, SEEK_SET)) { fclose(f); return NULL; }
    uint8_t *p = malloc((size_t)size);
    if (!p || fread(p, 1, (size_t)size, f) != (size_t)size) { free(p); fclose(f); return NULL; }
    fclose(f);
    unsigned char sha[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(p, (CC_LONG)size, sha);
    for (unsigned i = 0; i < sizeof(sha); i++) snprintf(digest + 2 * i, 3, "%02x", sha[i]);
    if (strcmp(digest, pin)) { free(p); return NULL; }
    *len = (size_t)size; return p;
}
static int tune(mt7921_dev_t *dev, void *ctx) {
    uint8_t channel = *(unsigned *)ctx;
    return mt7921_tune(dev, "5GHz", channel, channel, 20);
}
static int query(mt7921_dev_t *dev, void *ctx) {
    uint32_t offset = dev->usb.chip == MT_CHIP_MT7925 ? 19 : 11;
    return mt_mib_read(dev, &offset, 1, ctx);
}
typedef struct {
    uint64_t consumed, decoded, undecoded, timestamps, transitioning, off_channel, max_latency_us;
    uint64_t queries, retunes, max_mib_us, max_retune_us;
} counts_t;
static void consume(const mt_session_packet_t *p, int chip, unsigned channel, counts_t *counts) {
    counts->consumed++;
    mt7921_rxd_frame_t frame;
    if (mt7921_rxd_decoder_for_chip(chip)(p->raw, p->len, &frame) || !frame.frame) {
        counts->undecoded++; return;
    }
    counts->decoded++; counts->timestamps += frame.has_timestamp;
    counts->transitioning += p->transitioning;
    counts->off_channel += strcmp(frame.band, "5GHz") || frame.channel != channel;
    uint64_t latency = mt_radio_monotonic_us() - p->received_ns / 1000;
    if (latency > counts->max_latency_us) counts->max_latency_us = latency;
}
static void report(const char *event, mt76_session_t *s, const counts_t *c, uint64_t started,
                    bool alive, int result, const char *id) {
    mt_session_stats_t st; mt_session_snapshot(s, &st);
    printf("{\"event\":\"%s\",\"tool\":\"c_session_probe\",\"usb_id\":\"%s\","
           "\"elapsed_seconds\":%.3f,\"state\":%d,\"epoch_ns\":%" PRIu64 ","
           "\"frames_received\":%" PRIu64 ",\"frames_delivered\":%" PRIu64 ","
           "\"frames_dropped\":%" PRIu64 ",\"frame_depth\":%u,\"frame_high_water\":%" PRIu64 ","
           "\"events_received\":%" PRIu64 ",\"events_delivered\":%" PRIu64 ","
           "\"events_dropped\":%" PRIu64 ",\"event_depth\":%u,\"event_high_water\":%" PRIu64 ","
           "\"transfers\":%" PRIu64 ",\"read_timeouts\":%" PRIu64 ",\"usb_errors\":%" PRIu64 ","
           "\"malformed\":%" PRIu64 ",\"replies_matched\":%" PRIu64 ","
           "\"unmatched_replies\":%" PRIu64 ",\"commands_completed\":%" PRIu64 ","
           "\"decoded_frames\":%" PRIu64 ",\"undecoded\":%" PRIu64 ",\"timestamp_frames\":%" PRIu64 ","
           "\"transition_frames\":%" PRIu64 ",\"off_requested_channel\":%" PRIu64 ","
           "\"max_delivery_latency_us\":%" PRIu64 ",\"mib_queries\":%" PRIu64 ","
           "\"max_mib_latency_us\":%" PRIu64 ",\"retunes\":%" PRIu64 ","
           "\"max_retune_latency_us\":%" PRIu64 ",\"channel_known\":%s,\"requested_control\":%u,"
           "\"register_alive_after\":%s,\"exit_code\":%d}\n",
           event, id, (mt_radio_monotonic_us() - started) / 1e6, st.state, st.epoch_ns,
           st.frames_received, st.frames_delivered, st.frames_dropped, st.frame_depth, st.frames_high_water,
           st.events_received, st.events_delivered, st.events_dropped, st.event_depth, st.events_high_water,
           st.transfers, st.read_timeouts, st.usb_errors, st.malformed, st.replies_matched,
           st.unmatched_replies, st.commands_completed, c->decoded, c->undecoded, c->timestamps,
           c->transitioning, c->off_channel, c->max_latency_us, c->queries, c->max_mib_us, c->retunes,
           c->max_retune_us, st.channel_known ? "true" : "false", st.control,
           !strcmp(event, "summary") ? (alive ? "true" : "false") : "null", result);
}
int main(int argc, char **argv) {
    const char *id = NULL, *dir = "firmware";
    unsigned seconds = 60, hop_seconds = 5, mib_seconds = 1, capacity = 256;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--help")) {
            puts("mt76_session_probe --usb-id VID:PID --fw DIR [--seconds 1..14400] "
                 "[--hop-seconds 0..3600] [--mib-seconds 0..3600] [--frame-capacity 1..4096]");
            return 0;
        }
        const char *key = argv[i];
        if (++i == argc) return 2;
        if (!strcmp(key, "--usb-id")) id = argv[i];
        else if (!strcmp(key, "--fw")) dir = argv[i];
        else if (!strcmp(key, "--seconds")) { if (number(argv[i], 1, 14400, &seconds)) return 2; }
        else if (!strcmp(key, "--hop-seconds")) { if (number(argv[i], 0, 3600, &hop_seconds)) return 2; }
        else if (!strcmp(key, "--mib-seconds")) { if (number(argv[i], 0, 3600, &mib_seconds)) return 2; }
        else if (!strcmp(key, "--frame-capacity")) { if (number(argv[i], 1, 4096, &capacity)) return 2; }
        else return 2;
    }
    if (!id || (strcmp(id, "0e8d:7961") && strcmp(id, "0846:9072"))) return 2;
    int chip = !strcmp(id, "0846:9072") ? MT_CHIP_MT7925 : MT_CHIP_MT7921;
    const mt7921_chip_profile_t *prof = mt7921_chip_profile(chip);
    size_t patch_len = 0, ram_len = 0;
    uint8_t *patch = firmware(dir, prof->patch_file, prof->patch_sha256, &patch_len);
    uint8_t *ram = firmware(dir, prof->ram_file, prof->ram_sha256, &ram_len);
    if (!patch || !ram) { free(patch); free(ram); return 1; }
    mt7921_dev_t dev;
    if (mt7921_dev_open(&dev, id)) { free(patch); free(ram); return 1; }
    signal(SIGINT, stop_handler); signal(SIGTERM, stop_handler); signal(SIGPIPE, SIG_IGN);
    setvbuf(stdout, NULL, _IOLBF, 0);
    unsigned channel = 36;
    int result = 1;
    mt76_session_t *s = NULL;
    counts_t counts = {0};
    if (mt7921_bringup(&dev, patch, patch_len, ram, ram_len, quiet) ||
        mt7921_set_monitor_mode(&dev) || mt7921_set_sniffer(&dev, true, 0) || tune(&dev, &channel))
        goto cleanup;
    s = mt_session_start(&dev, capacity, 64);
    if (!s) goto cleanup;
    uint64_t started = mt_radio_monotonic_us(), end = started + (uint64_t)seconds * 1000000;
    uint64_t next_hop = hop_seconds ? started + hop_seconds * 1000000ULL : UINT64_MAX;
    uint64_t next_mib = mib_seconds ? started + mib_seconds * 1000000ULL : UINT64_MAX;
    uint64_t heartbeat = started + 30000000;
    printf("{\"event\":\"ready\",\"usb_id\":\"%s\",\"requested_seconds\":%u,"
           "\"hop_seconds\":%u,\"mib_seconds\":%u,\"patch_sha256\":\"%s\",\"ram_sha256\":\"%s\"}\n",
           id, seconds, hop_seconds, mib_seconds, prof->patch_sha256, prof->ram_sha256);
    result = 0;
    mt_session_packet_t packet;
    while (!stopping && mt_radio_monotonic_us() < end) {
        if (!mt_session_read(s, &packet, false, 50)) consume(&packet, chip, channel, &counts);
        while (!mt_session_read(s, &packet, true, 0)) {}
        mt_session_stats_t stats; mt_session_snapshot(s, &stats);
        if (stats.state != MT_SESSION_RUNNING) { result = 1; break; }
        uint64_t now = mt_radio_monotonic_us();
        if (now >= next_mib) {
            mt_mib_sample_t sample;
            if (mt_session_call(s, query, &sample, 3000, false)) { result = 1; break; }
            counts.queries++;
            uint64_t latency = sample.closed_us - sample.opened_us;
            if (latency > counts.max_mib_us) counts.max_mib_us = latency;
            next_mib = mt_radio_monotonic_us() + mib_seconds * 1000000ULL;
        }
        if (now >= next_hop) {
            channel = channel == 36 ? 149 : 36;
            uint64_t tune_started = mt_radio_monotonic_us();
            if (mt_session_call(s, tune, &channel, 3000, true)) { result = 1; break; }
            uint64_t tune_elapsed = mt_radio_monotonic_us() - tune_started;
            if (tune_elapsed > counts.max_retune_us) counts.max_retune_us = tune_elapsed;
            counts.retunes++; next_hop = mt_radio_monotonic_us() + hop_seconds * 1000000ULL;
        }
        if (now >= heartbeat) {
            report("heartbeat", s, &counts, started, false, result, id);
            heartbeat = now + 30000000;
        }
        if (ferror(stdout)) { result = 1; break; }
    }
    if (mt_session_stop(s, 4000)) {
        /* Retain worker/device memory until process exit rather than race a live callback. */
        fprintf(stderr, "session stop failed; USB ownership retained\n"); return 1;
    }
    while (!mt_session_read(s, &packet, false, 0)) consume(&packet, chip, channel, &counts);
    while (!mt_session_read(s, &packet, true, 0)) {}
    bool alive = mt7921_is_alive(&dev);
    if (!alive || dev.mcu.dropped_frames) result = 1;
    if (stopping && !result) result = 130;
    report("summary", s, &counts, started, alive, result, id);
    if (fflush(stdout) || ferror(stdout)) result = 1;
cleanup:
    if (s) mt_session_destroy(s);
    mt7921_dev_close(&dev); free(patch); free(ram);
    return result;
}
