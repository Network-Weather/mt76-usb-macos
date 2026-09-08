/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Real worker/MCU replay with synthetic USB boundaries; no device or firmware. */
#include "mt76_csi_session.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static struct {
    mt7921_dev_t *dev;
    unsigned writes, stage, mode;
    uint8_t actions[16], reply[64];
    uint32_t reply_len;
    bool pending;
} fake;
static void put32(uint8_t *p, uint32_t v) {
    for (unsigned i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i));
}
static int write_bulk(mt7921_usb_t *usb, uint8_t ep, const void *data, uint32_t len, uint32_t ms) {
    (void)usb; (void)ep; (void)ms;
    if (len<4+MCU_UNI_TXD_LEN+8 || fake.writes>=16) return -1;
    fake.actions[fake.writes++]=((const uint8_t *)data)[4+MCU_UNI_TXD_LEN+4];
    bool failed=fake.stage && fake.writes==fake.stage;
    if (failed && fake.mode==2) return -1;
    memset(fake.reply,0,sizeof(fake.reply));
    fake.reply_len=failed && fake.mode==1 ? 48 : 52;
    put32(fake.reply,fake.reply_len | 7U<<27);
    fake.reply[36]=1; fake.reply[37]=fake.dev->mcu.msg_seq;
    put32(fake.reply+44,0x4a);
    put32(fake.reply+48,failed && fake.mode==0 ? 1 : 0);
    fake.pending=true;
    return 0;
}
static int read_bulk(mt7921_usb_t *usb, uint8_t ep, void *out, uint32_t *len, uint32_t ms) {
    (void)usb; (void)ep; (void)ms;
    if (!fake.pending) { usleep(1000); return MT7921_ERR_TIMEOUT; }
    if (*len<fake.reply_len) return -1;
    memcpy(out,fake.reply,fake.reply_len); *len=fake.reply_len; fake.pending=false;
    return 0;
}
static unsigned ta_offset, rx_offset;
static void packet(mt_session_packet_t *p, const mt_csi_capture_t *capture) {
    memset(p,0,sizeof(*p));
    p->kind=MT_PACKET_REPLY; p->epoch_ns=capture->epoch_ns; p->generation=capture->generation;
    p->received_ns=capture->configured_ns;
    p->raw[36]=0x4a;
    const unsigned tags[]={0,1,2,3,4,5,6,7,8,9,10,12,18,20,21,25};
    unsigned at=52;
    for (unsigned i=0;i<sizeof(tags)/sizeof(*tags);i++) {
        unsigned tag=tags[i], size=tag==6 || tag==7 ? 128 : tag==10 ? 8 : 4;
        put32(p->raw+at,tag); put32(p->raw+at+4,size); at+=8;
        uint32_t value=tag==0 ? 22 : tag==5 ? 64 : tag==12 ? (11U<<16|1) : 0;
        put32(p->raw+at,value);
        if (tag==10) { memcpy(p->raw+at,capture->transmitter,6); ta_offset=at; }
        if (tag==18) rx_offset=at;
        at+=size;
    }
    p->len=at; put32(p->raw,at|7U<<27);
    unsigned body_len=at-44;
    p->raw[50]=(uint8_t)(body_len-4); p->raw[51]=(uint8_t)((body_len-4)>>8);
}
static int retune(mt7921_dev_t *dev, void *ctx) { (void)dev; (void)ctx; return 0; }

int csi_capture_test(unsigned stage, unsigned mode, unsigned change) {
    mt7921_dev_t dev={0};
    dev.usb.chip=change==3 ? MT_CHIP_MT7921 : MT_CHIP_MT7925;
    mt7921_mcu_init(&dev.mcu,&dev.usb);
    dev.mcu.write_bulk=write_bulk; dev.mcu.read_bulk=read_bulk; dev.mcu.evt_ep4=true;
    dev.session_ready=dev.tuned=true; dev.tuned_band=1;
    dev.tuned_control=dev.tuned_center=36; dev.tuned_width=20;
    if (change==4) dev.tuned_width=80;
    memset(&fake,0,sizeof(fake)); fake.dev=&dev; fake.stage=stage; fake.mode=mode;
    mt76_session_t *s=mt_session_start(&dev,8,8);
    if (!s) return 1;
    mt_csi_capture_t capture={0};
    const uint8_t ta[]={2,0,0,0,0,1};
    int start=mt_csi_capture_start(s,&capture,ta,change==5 ? 0 : 1), result=0;
    mt_session_stats_t stats; mt_session_snapshot(s,&stats);
    if (change>=3) {
        if (!start || fake.writes || capture.active || stats.state!=MT_SESSION_RUNNING) result=2;
        goto cleanup;
    }
    if (stage && stage<6) {
        if (!start || !capture.active || capture.ready || !capture.needs_reload ||
            fake.writes!=stage || stats.state!=MT_SESSION_FAILED) result=3;
        goto cleanup;
    }
    if (start || !capture.active || !capture.ready || !capture.needs_reload || fake.writes!=5 ||
        memcmp(fake.actions,(uint8_t[]){0,2,1,4,3},5)) { result=4; goto cleanup; }
    if (!mt_csi_capture_start(s,&capture,ta,1) || fake.writes!=5) { result=5; goto cleanup; }
    mt_session_packet_t p;
    mt_beacon_csi_report_t output;
    packet(&p,&capture);
    if (mt_csi_capture_accept(&capture,&p,&output) || memcmp(output.transmitter,ta,6)) { result=6; goto cleanup; }
    for (unsigned variant=0;variant<7;variant++) {
        packet(&p,&capture);
        if (variant==0) p.epoch_ns=0;
        if (variant==1) p.generation++;
        if (variant==2) p.received_ns--;
        if (variant==3) p.transitioning=true;
        if (variant==4) p.kind=MT_PACKET_FRAME;
        if (variant==5) p.raw[ta_offset+5]=2;
        if (variant==6) put32(p.raw+rx_offset,1);
        memset(&output,0xA5,sizeof(output));
        mt_beacon_csi_report_t before=output;
        if (mt_csi_capture_accept(&capture,&p,&output)!=1 || memcmp(&output,&before,sizeof(output))) { result=7; goto cleanup; }
    }
    packet(&p,&capture); p.len--;
    if (mt_csi_capture_accept(&capture,&p,&output)!=-1) { result=8; goto cleanup; }
    if (change==1) {
        if (mt_session_call(s,retune,NULL,1000,true)) { result=9; goto cleanup; }
        packet(&p,&capture);
        if (mt_csi_capture_accept(&capture,&p,&output)!=-1 || capture.ready) { result=10; goto cleanup; }
    }
    if (change==2) {
        if (mt_session_stop(s,2000)) { result=11; goto cleanup; }
        packet(&p,&capture);
        if (mt_csi_capture_accept(&capture,&p,&output)!=-1 || capture.ready) result=12;
        goto cleanup;
    }
    int stopped=mt_csi_capture_stop(&capture);
    if (stage==6) {
        if (!stopped || capture.ready || !capture.active || !capture.needs_reload) result=13;
    } else {
        if (stopped || capture.ready || capture.active || !capture.needs_reload || fake.writes!=6) result=14;
        packet(&p,&capture);
        if (mt_csi_capture_accept(&capture,&p,&output)!=1 || mt_csi_capture_stop(&capture) || fake.writes!=6) result=15;
        if (!change) {
            uint64_t previous=capture.configured_ns;
            if (mt_csi_capture_start(s,&capture,ta,1) || capture.configured_ns<=previous ||
                mt_csi_capture_accept(&capture,&p,&output)!=1 || mt_csi_capture_stop(&capture)) result=16;
        }
    }
cleanup:
    if (mt_session_stop(s,2000)) return 17;
    if (mt_session_destroy(s)) return 18;
    return result;
}
#ifndef MT_CSI_NO_MAIN
int main(void) {
    for (unsigned stage=0;stage<7;stage++) for (unsigned mode=0;mode<3;mode++)
        assert(!csi_capture_test(stage,mode,0));
    for (unsigned change=1;change<6;change++) assert(!csi_capture_test(0,0,change));
    puts("CSI lifetime: ordered controls, each-stage faults, filtering, retune and stop passed");
    return 0;
}
#endif
