/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Bounded passive histogram acquisition with normal RX/counter/thermal queries.
 * One owner per dongle, three windows, fixed traced controls, full final reload. */
#include "mt76_histogram_acquisition.h"
#include "mt76_session.h"
#include "mt7921_rxd.h"
#include "mt76_probe_firmware.h"
#include <inttypes.h>
#include <signal.h>

static volatile sig_atomic_t stopping;
static void stop_handler(int sig) { (void)sig; stopping=1; }
static void quiet(const char *fmt, ...) { (void)fmt; }
typedef struct {
    mt_histogram_guard_t guard;
    mt_histogram_sample_t sample;
    mt_session_packet_t report;
    unsigned frames, events, reports, queries;
} state_t;
typedef struct { uint32_t controls[4], banks[4][11]; } snapshot_t;
static int begin(mt7921_dev_t *dev, void *ctx) {
    return mt_histogram_begin_device(dev,&((state_t *)ctx)->guard);
}
static int finish(mt7921_dev_t *dev, void *ctx) {
    state_t *state=ctx; bool modern=dev->usb.chip==MT_CHIP_MT7925;
    return mt_histogram_finish(&state->guard,modern ? state->report.raw : NULL,
                               modern ? state->report.len : 0,&state->sample);
}
static int restore(mt7921_dev_t *dev, void *ctx) {
    (void)dev; return mt_histogram_restore(&((state_t *)ctx)->guard);
}
static int query(mt7921_dev_t *dev, void *ctx) {
    (void)ctx; const int names[]={MT_COUNTER_PRIMARY_CCA,MT_COUNTER_RX_MPDU};
    mt_counter_sample_t counters; mt_thermal_sample_t thermal;
    return mt_counter_read(dev,names,2,&counters) || mt_thermal_read(&dev->mcu,MT_THERMAL_TEMPERATURE,&thermal) ? -1 : 0;
}
static int snapshot(mt7921_dev_t *dev, void *ctx) {
    snapshot_t *s=ctx; memset(s,0,sizeof(*s));
    bool modern=dev->usb.chip==MT_CHIP_MT7925;
    const uint32_t addresses[2][4]={{0x83082004,0x83088230,0x83088234,0},
                                  {0x83082004,0x83088230,0x83092004,0x83098230}};
    const uint32_t masks[2][4]={{7,1U<<29,0x30000,0},{7,1U<<29,7,1U<<29}};
    const uint32_t bases[4]={0x83088600,0x83001000,0x83098600,0x83011000};
    for (unsigned i=0;i<(modern?4U:3U);i++) {
        uint32_t word;
        if (mt7921_rr_checked(&dev->usb,addresses[modern][i],&word) || word==UINT32_MAX) return -1;
        s->controls[i]=word&masks[modern][i];
    }
    for (unsigned v=0;v<(modern?4U:1U);v++) for (unsigned i=0;i<11;i++)
        if (mt7921_rr_checked(&dev->usb,bases[v]+4*i,&s->banks[v][i])) return -1;
    return 0;
}
static int collect(mt76_session_t *session, state_t *state, unsigned milliseconds, bool expect) {
    uint64_t started=mt_radio_monotonic_us(), next=started;
    state->frames=state->events=state->reports=state->queries=0;
    while (!stopping && mt_radio_monotonic_us()-started < (uint64_t)milliseconds*1000) {
        mt_session_stats_t stats; mt_session_snapshot(session,&stats);
        if (stats.state!=MT_SESSION_RUNNING) return -1;
        if (mt_radio_monotonic_us()>=next) {
            if (mt_session_call(session,query,NULL,3000,false)) return -1;
            state->queries++; next=mt_radio_monotonic_us()+200000;
        }
        mt_session_packet_t packet;
        if (!mt_session_read(session,&packet,false,5)) {
            mt7921_rxd_frame_t frame;
            int rc=mt_session_chip(session)==MT_CHIP_MT7925 ? mt7921_rxd_decode_connac3(packet.raw,packet.len,&frame) : mt7921_rxd_decode(packet.raw,packet.len,&frame);
            if (!rc && frame.frame_len) state->frames++;
        }
        for (unsigned i=0;i<64;i++) {
            if (mt_session_read(session,&packet,true,0)) break;
            state->events++;
            if (packet.len>=44 && packet.raw[36]==0x36) {
                mt_histogram_bins_t bins;
                if (!expect || state->reports || mt_histogram_event(MT_CHIP_MT7925,packet.raw,packet.len,&bins)) return -1;
                state->reports++; state->report=packet;
            }
        }
        if (state->frames+state->events>=4096) return -1;
        if (expect && state->reports) return 0;
    }
    return expect && !stopping && state->reports!=1 ? -1 : 0;
}
static void print_bins(const uint32_t bins[11]) {
    putchar('[');
    for (unsigned i=0;i<11;i++) printf("%s%u",i?",":"",bins[i]);
    putchar(']');
}
int main(int argc, char **argv) {
    const char *dir=NULL; int chip=-1; unsigned channel=6; bool acknowledge=false;
    for (int i=1;i<argc;i++) {
        if (!strcmp(argv[i],"--help")) {
            puts("mt76_histogram_probe --chip mt7921|mt7925 --fw PINNED_DIR --channel 1|6|11|36 --reset-shared-histogram"); return 0;
        }
        if (!strcmp(argv[i],"--reset-shared-histogram")) { acknowledge=true; continue; }
        if (i+1>=argc) return 2;
        const char *key=argv[i++], *value=argv[i];
        if (!strcmp(key,"--fw")) dir=value;
        else if (!strcmp(key,"--chip") && (!strcmp(value,"mt7921") || !strcmp(value,"mt7925"))) chip=!strcmp(value,"mt7925");
        else if (!strcmp(key,"--channel") && (!strcmp(value,"1") || !strcmp(value,"6") || !strcmp(value,"11") || !strcmp(value,"36"))) channel=(unsigned)atoi(value);
        else return 2;
    }
    if (!dir || chip<0 || !acknowledge) return 2;
    const mt7921_chip_profile_t *prof=mt7921_chip_profile(chip);
    size_t patch_len,ram_len;
    uint8_t *patch=mt_probe_firmware(dir,prof->patch_file,prof->patch_sha256,&patch_len);
    uint8_t *ram=mt_probe_firmware(dir,prof->ram_file,prof->ram_sha256,&ram_len);
    if (!patch || !ram) { free(patch); free(ram); return 1; }
    mt7921_dev_t dev;
    if (mt7921_dev_open(&dev,chip ? "0846:9072":"0e8d:7961")) { free(patch); free(ram); return 1; }
    signal(SIGINT,stop_handler); signal(SIGTERM,stop_handler); signal(SIGPIPE,SIG_IGN);
    setvbuf(stdout,NULL,_IOLBF,0);
    state_t state={0}; mt76_session_t *session=NULL; int result=1;
    if (mt7921_bringup(&dev,patch,patch_len,ram,ram_len,quiet) || mt7921_set_monitor_mode(&dev) ||
        mt7921_set_sniffer(&dev,true,0) || mt7921_tune(&dev,channel<=11 ? "2.4GHz":"5GHz",channel,channel,20)) goto cleanup;
    session=mt_session_start(&dev,256,64);
    if (!session) goto cleanup;
    printf("{\"event\":\"ready\",\"chip\":\"mt792%d\",\"channel\":%u,\"patch_sha256\":\"%s\",\"ram_sha256\":\"%s\"}\n",
           chip?5:1,channel,prof->patch_sha256,prof->ram_sha256);
    if (collect(session,&state,250,false)) goto cleanup;
    printf("{\"event\":\"baseline\",\"normal_frames\":%u,\"queries\":%u}\n",state.frames,state.queries);
    const unsigned duration[3]={250,500,1000};
    for (unsigned cycle=0;cycle<3 && !stopping;cycle++) {
        if (mt_session_call(session,begin,&state,3000,false)) goto cleanup;
        printf("{\"event\":\"histogram_started\",\"index\":%u}\n",cycle);
        if (collect(session,&state,chip?2000:duration[cycle],chip!=0)) goto cleanup;
        if (stopping) break;
        if (mt_session_call(session,finish,&state,3000,false)) goto cleanup;
        snapshot_t first,second;
        if (mt_session_call(session,snapshot,&first,3000,false)) goto cleanup;
        char latency[32]="null";
        if (chip) snprintf(latency,sizeof(latency),"%" PRIu64,state.report.received_ns/1000-state.sample.command_open_us);
        printf("{\"event\":\"sample\",\"index\":%u,\"normal_frames\":%u,\"queries\":%u,\"events\":%u,"
               "\"command_open_us\":%" PRIu64 ",\"command_closed_us\":%" PRIu64 ",\"read_open_us\":%" PRIu64
               ",\"read_closed_us\":%" PRIu64 ",\"event_latency_us\":%s,\"coverage_fraction\":null,\"bins\":[",
               cycle,state.frames,state.queries,state.events,state.sample.command_open_us,state.sample.command_closed_us,
               state.sample.read_open_us,state.sample.read_closed_us,latency);
        for (unsigned v=0;v<state.sample.bins.view_count;v++) { if(v) putchar(','); print_bins(state.sample.bins.bins[v]); }
        puts("]}");
        if (collect(session,&state,100,false) || mt_session_call(session,snapshot,&second,3000,false) || memcmp(&first,&second,sizeof(first))) goto cleanup;
        if (mt_session_call(session,restore,&state,3000,false)) goto cleanup;
        printf("{\"event\":\"restored\",\"index\":%u,\"stable_stopped_banks\":true}\n",cycle);
    }
    result=0;
cleanup:
    if (session) {
        if (mt_session_stop(session,4000)) { fputs("session retains USB ownership\n",stderr); return 1; }
        mt_session_stats_t st; mt_session_snapshot(session,&st);
        printf("{\"event\":\"session\",\"state\":%d,\"frames_received\":%" PRIu64 ",\"frames_dropped\":%" PRIu64
               ",\"events_received\":%" PRIu64 ",\"events_dropped\":%" PRIu64 ",\"usb_errors\":%" PRIu64
               ",\"replies_matched\":%" PRIu64 ",\"commands_completed\":%" PRIu64 ",\"frame_depth_at_destroy\":%u,\"event_depth_at_destroy\":%u}\n",
               st.state,st.frames_received,st.frames_dropped,st.events_received,st.events_dropped,st.usb_errors,
               st.replies_matched,st.commands_completed,st.frame_depth,st.event_depth);
        if (mt_session_destroy(session)) return 1;
    }
    printf("{\"event\":\"guard\",\"active\":%s,\"pending\":%s,\"ready\":%s,\"needs_reload\":%s}\n",
           state.guard.active?"true":"false",state.guard.pending?"true":"false",state.guard.ready?"true":"false",state.guard.needs_reload?"true":"false");
    bool reloaded=!mt7921_bringup(&dev,patch,patch_len,ram,ram_len,quiet) && mt7921_is_alive(&dev);
    if (!reloaded) result=1;
    if (stopping && !result) result=130;
    printf("{\"event\":\"cleanup\",\"reload_alive\":%s,\"pending_policy\":\"full reload after worker stop\",\"exit_code\":%d}\n",reloaded?"true":"false",result);
    mt7921_dev_close(&dev); free(patch); free(ram); return result;
}
