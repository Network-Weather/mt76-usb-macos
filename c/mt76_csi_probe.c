/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Bounded native CSI/session qualification, not a public streaming interface.
 * Passive channel36/20MHz only; all identifiers/IQ/digests stay in memory. */
#include "mt76_csi.h"
#include "mt76_session.h"
#include "mt7921_radio.h"
#include "mt7921_rxd.h"
#include "mt76_probe_firmware.h"
#include <inttypes.h>
#include <signal.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static void stop_handler(int sig) { (void)sig; stopping = 1; }
static void quiet(const char *fmt, ...) { (void)fmt; }
typedef struct { int action; unsigned receivers; const uint8_t *ta; } control_t;
static int control(mt7921_dev_t *dev, void *ctx) {
    control_t *c = ctx;
    uint8_t request[16], reply[256]; uint32_t len = sizeof(reply), status;
    int size = mt_csi_request(dev->usb.chip, c->action, c->receivers, c->ta, request, sizeof(request));
    if (size < 0 || mt7921_uni_option(dev->mcu.prof, 0x4a, false) != 7) return -1;
    if (mt7921_mcu_uni(&dev->mcu, 0x4a, request, (uint32_t)size, true, reply, &len, 1000) ||
        mt_csi_ack(dev->usb.chip, reply, len, dev->mcu.msg_seq, &status) || status) return -1;
    return 0;
}
static int command(mt76_session_t *session, int action, unsigned receivers, const uint8_t *ta) {
    control_t ctx = {action, receivers, ta};
    return mt_session_call(session, control, &ctx, 3000, false);
}
static int query(mt7921_dev_t *dev, void *ctx) {
    (void)ctx;
    const int names[] = {MT_COUNTER_PRIMARY_CCA, MT_COUNTER_RX_MPDU};
    mt_counter_sample_t counters; mt_thermal_sample_t thermal;
    return mt_counter_read(dev, names, 2, &counters) ||
           mt_thermal_read(&dev->mcu, MT_THERMAL_TEMPERATURE, &thermal) ? -1 : 0;
}
typedef struct { uint8_t ta[6]; unsigned beacons, reports; } source_t;
typedef struct {
    unsigned frames, beacons, reports, invalid, accepted, preconfig, unselected, receiver_discarded, after_stop;
    unsigned events, queries, rx[2], source_count, iq_count, source_overflow, iq_overflow;
    uint64_t cutoff_ns;
    bool stopped;
    const uint8_t *selected;
    unsigned receivers;
    source_t sources[32];
    uint8_t iq_digest[512][CC_SHA256_DIGEST_LENGTH];
} window_t;
static source_t *source(window_t *w, const uint8_t *ta) {
    for (unsigned i = 0; i < w->source_count; i++)
        if (!memcmp(w->sources[i].ta, ta, 6)) return w->sources + i;
    if (w->source_count == 32) { w->source_overflow++; return NULL; }
    source_t *s = w->sources + w->source_count++;
    memcpy(s->ta, ta, 6); return s;
}
static void frame(window_t *w, const mt_session_packet_t *p) {
    mt7921_rxd_frame_t f;
    if (mt7921_rxd_decode_connac3(p->raw, p->len, &f) || !f.frame_len) return;
    w->frames++;
    if (!f.fcs_err && f.frame_len >= 36 && f.frame[0] == 0x80) {
        w->beacons++;
        source_t *s = source(w, f.frame + 10);
        if (s) s->beacons++;
    }
}
static void event(window_t *w, const mt_session_packet_t *p) {
    w->events++;
    if (p->len < 44 || p->raw[36] != 0x4a) return;
    mt_beacon_csi_report_t report;
    if (mt_beacon_csi_parse(MT_CHIP_MT7925, p->raw, p->len, &report)) { w->invalid++; return; }
    w->reports++;
    if (w->stopped) { w->after_stop++; return; }
    if (p->received_ns < w->cutoff_ns) { w->preconfig++; return; }
    if (w->selected && memcmp(w->selected, report.transmitter, 6)) { w->unselected++; return; }
    if (report.rx_index >= w->receivers) { w->receiver_discarded++; return; }
    w->accepted++; w->rx[report.rx_index]++;
    source_t *s = source(w, report.transmitter);
    if (s) s->reports++;
    uint8_t digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256_CTX hash;
    CC_SHA256_Init(&hash); CC_SHA256_Update(&hash, report.i, sizeof(report.i));
    CC_SHA256_Update(&hash, report.q, sizeof(report.q)); CC_SHA256_Final(digest, &hash);
    for (unsigned i = 0; i < w->iq_count; i++)
        if (!memcmp(digest, w->iq_digest[i], sizeof(digest))) return;
    if (w->iq_count == 512) { w->iq_overflow++; return; }
    memcpy(w->iq_digest[w->iq_count++], digest, sizeof(digest));
}
static int collect(mt76_session_t *s, const char *name, window_t *w, unsigned milliseconds) {
    uint64_t start = mt_radio_monotonic_us(), next_query = start;
    int result = 0;
    mt_session_packet_t packet;
    while (!stopping && mt_radio_monotonic_us() - start < milliseconds * UINT64_C(1000)) {
        mt_session_stats_t stats; mt_session_snapshot(s, &stats);
        if (stats.state != MT_SESSION_RUNNING) { result = -1; break; }
        if (mt_radio_monotonic_us() >= next_query) {
            if (mt_session_call(s, query, NULL, 3000, false)) { result = -1; break; }
            w->queries++; next_query = mt_radio_monotonic_us() + 250000;
        }
        if (!mt_session_read(s, &packet, false, 5)) frame(w, &packet);
        for (unsigned i = 0; i < 64; i++) {
            if (mt_session_read(s, &packet, true, 0)) break;
            event(w, &packet);
        }
        if (w->frames + w->events > 4096) { result = -1; break; }
    }
    unsigned sources = 0;
    for (unsigned i = 0; i < w->source_count; i++) sources += w->sources[i].reports != 0;
    printf("{\"event\":\"window\",\"name\":\"%s\",\"normal_frames\":%u,\"beacons\":%u,"
           "\"csi_reports\":%u,\"invalid_or_outside_profile\":%u,\"accepted_reports\":%u,"
           "\"preconfiguration_discarded\":%u,\"unselected_discarded\":%u,\"receiver_discarded\":%u,"
           "\"reports_after_stop\":%u,\"counter_thermal_pairs\":%u,\"rx0\":%u,\"rx1\":%u,"
           "\"accepted_sources\":%u,\"iq_distinct\":%u,\"source_overflow\":%u,\"iq_overflow\":%u}\n",
           name,w->frames,w->beacons,w->reports,w->invalid,w->accepted,w->preconfig,w->unselected,
           w->receiver_discarded,w->after_stop,w->queries,w->rx[0],w->rx[1],sources,w->iq_count,
           w->source_overflow,w->iq_overflow);
    return result;
}
int main(int argc, char **argv) {
    const char *dir = NULL;
    unsigned events = 64, stall_ms = 0;
    bool after_filter = true;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--help")) {
            puts("mt76_csi_probe --fw PINNED_DIR [--event-capacity 1|64] [--stall-ms 0|250] [--receiver-order before-filter|after-filter]");
            return 0;
        }
        if (i + 1 >= argc) return 2;
        const char *key = argv[i++], *value = argv[i];
        if (!strcmp(key, "--fw")) dir = value;
        else if (!strcmp(key, "--event-capacity") && (!strcmp(value,"1") || !strcmp(value,"64"))) events = (unsigned)atoi(value);
        else if (!strcmp(key, "--stall-ms") && (!strcmp(value,"0") || !strcmp(value,"250"))) stall_ms = (unsigned)atoi(value);
        else if (!strcmp(key, "--receiver-order") && (!strcmp(value,"before-filter") || !strcmp(value,"after-filter"))) after_filter = !strcmp(value,"after-filter");
        else return 2;
    }
    if (!dir) return 2;
    const mt7921_chip_profile_t *prof = mt7921_chip_profile(MT_CHIP_MT7925);
    size_t patch_len, ram_len;
    uint8_t *patch = mt_probe_firmware(dir, prof->patch_file, prof->patch_sha256, &patch_len);
    uint8_t *ram = mt_probe_firmware(dir, prof->ram_file, prof->ram_sha256, &ram_len);
    if (!patch || !ram) { free(patch); free(ram); return 1; }
    mt7921_dev_t dev;
    if (mt7921_dev_open(&dev, "0846:9072")) { free(patch); free(ram); return 1; }
    signal(SIGINT, stop_handler); signal(SIGTERM, stop_handler); signal(SIGPIPE, SIG_IGN);
    setvbuf(stdout, NULL, _IOLBF, 0);
    int result = 1;
    mt76_session_t *s = NULL;
    if (mt7921_bringup(&dev,patch,patch_len,ram,ram_len,quiet) || mt7921_set_monitor_mode(&dev) ||
        mt7921_set_sniffer(&dev,true,0) || mt7921_tune(&dev,"5GHz",36,36,20)) goto cleanup;
    s = mt_session_start(&dev,256,events);
    if (!s) goto cleanup;
    printf("{\"event\":\"ready\",\"tool\":\"c_csi_probe\",\"event_capacity\":%u,\"stall_ms\":%u,"
           "\"receiver_order\":\"%s\",\"patch_sha256\":\"%s\",\"ram_sha256\":\"%s\"}\n",
           events,stall_ms,after_filter ? "after-filter" : "before-filter",prof->patch_sha256,prof->ram_sha256);
    window_t w = {.stopped=true};
    if (command(s,MT_CSI_STOP,0,NULL) || collect(s,"stopped_baseline",&w,1000) ||
        command(s,MT_CSI_BEACON_SELECTOR,0,NULL) || command(s,MT_CSI_START,0,NULL) ||
        command(s,MT_CSI_RECEIVER_COUNT,2,NULL)) goto cleanup;
    memset(&w,0,sizeof(w)); w.receivers=2; w.cutoff_ns=mt_radio_monotonic_us()*1000;
    if (collect(s,"unfiltered",&w,2000)) goto cleanup;
    uint8_t selected[6]; bool found=false;
    for (unsigned i=0; i<w.source_count; i++) if (w.sources[i].beacons && w.sources[i].reports) {
        memcpy(selected,w.sources[i].ta,6); found=true; break;
    }
    if (!found) { puts("{\"event\":\"filter_gate\",\"reason\":\"no common CSI/beacon source\"}"); goto cleanup; }
    for (unsigned cycle=0; cycle<2 && !stopping; cycle++) {
        if (command(s,MT_CSI_STOP,0,NULL) || command(s,MT_CSI_BEACON_SELECTOR,0,NULL) || command(s,MT_CSI_START,0,NULL) ||
            (!after_filter && command(s,MT_CSI_RECEIVER_COUNT,1,NULL)) || command(s,MT_CSI_ADD_TRANSMITTER,0,selected) ||
            (after_filter && command(s,MT_CSI_RECEIVER_COUNT,1,NULL))) goto cleanup;
        memset(&w,0,sizeof(w)); w.receivers=1; w.selected=selected; w.cutoff_ns=mt_radio_monotonic_us()*1000;
        if (stall_ms) usleep(stall_ms*1000);
        char name[32]; snprintf(name,sizeof(name),"filtered_restart_%u",cycle);
        if (collect(s,name,&w,2000) || command(s,MT_CSI_REMOVE_TRANSMITTER,0,selected) || command(s,MT_CSI_STOP,0,NULL)) goto cleanup;
        memset(&w,0,sizeof(w)); w.stopped=true;
        snprintf(name,sizeof(name),"stopped_%u",cycle);
        if (collect(s,name,&w,500)) goto cleanup;
    }
    if (command(s,MT_CSI_STOP,0,NULL)) goto cleanup;
    result=0;
cleanup:
    if (s) {
        if (mt_session_stop(s,4000)) { fputs("session retains USB ownership\n",stderr); return 1; }
        mt_session_stats_t st; mt_session_snapshot(s,&st);
        printf("{\"event\":\"session\",\"state\":%d,\"frames_received\":%" PRIu64 ",\"frames_dropped\":%" PRIu64
               ",\"events_received\":%" PRIu64 ",\"events_dropped\":%" PRIu64 ",\"usb_errors\":%" PRIu64
               ",\"malformed\":%" PRIu64 ",\"replies_matched\":%" PRIu64 ",\"commands_completed\":%" PRIu64
               ",\"frames_delivered\":%" PRIu64 ",\"events_delivered\":%" PRIu64
               ",\"frame_depth_at_destroy\":%u,\"event_depth_at_destroy\":%u}\n",
               st.state,st.frames_received,st.frames_dropped,st.events_received,st.events_dropped,st.usb_errors,
               st.malformed,st.replies_matched,st.commands_completed,st.frames_delivered,st.events_delivered,
               st.frame_depth,st.event_depth);
        if (mt_session_destroy(s)) return 1;
    }
    control_t stop = {MT_CSI_STOP,0,NULL};
    bool stopped = !control(&dev,&stop);
    bool reloaded = !mt7921_bringup(&dev,patch,patch_len,ram,ram_len,quiet) && mt7921_is_alive(&dev);
    if (!stopped || !reloaded) result=1;
    if (stopping && !result) result=130;
    printf("{\"event\":\"cleanup\",\"stop_ack\":%s,\"reload_alive\":%s,\"exit_code\":%d}\n",
           stopped ? "true":"false",reloaded ? "true":"false",result);
    mt7921_dev_close(&dev); free(patch); free(ram);
    return result;
}
