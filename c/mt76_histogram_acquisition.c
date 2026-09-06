/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#include "mt76_histogram_acquisition.h"
#include <string.h>

static const uint32_t addresses[2][4]={{0x83082004,0x83088230,0x83088234,0},
                                      {0x83082004,0x83088230,0x83092004,0x83098230}};
static const uint32_t masks[2][4]={{7,1U<<29,0x30000,0},{7,1U<<29,7,1U<<29}};
static unsigned count(const mt_histogram_guard_t *g) { return g->chip==MT_CHIP_MT7925 ? 4 : 3; }
static int read_control(mt_histogram_guard_t *g, unsigned i, uint32_t *value) {
    return g->io.registers.read(g->io.registers.ctx,addresses[g->chip][i],value) || *value==UINT32_MAX ? -1 : 0;
}
static int set(mt_histogram_guard_t *g, unsigned i, uint32_t bits) {
    uint32_t word, check, mask=masks[g->chip][i];
    if (read_control(g,i,&word) || g->io.registers.write(g->io.registers.ctx,addresses[g->chip][i],(word&~mask)|bits) ||
        read_control(g,i,&check) || (check&mask)!=bits) return -1;
    return 0;
}
static uint32_t channel(const mt7921_dev_t *dev) {
    return (uint32_t)dev->tuned_band<<24|(uint32_t)dev->tuned_control<<16|
           (uint32_t)dev->tuned_center<<8|dev->tuned_width;
}
int mt_histogram_begin(mt_histogram_guard_t *g, int chip, mt_histogram_io_t io) {
    if (!g || g->active || (chip!=MT_CHIP_MT7921 && chip!=MT_CHIP_MT7925) || !io.registers.read || !io.registers.write ||
        (chip==MT_CHIP_MT7925 && !io.activate)) return -1;
    mt_histogram_guard_t next={.io=io,.chip=chip,.needs_reload=g->needs_reload};
    for (unsigned i=0;i<count(&next);i++) {
        uint32_t word;
        if (read_control(&next,i,&word)) return -1;
        next.saved[i]=word&masks[chip][i];
        if (next.saved[i] && !(chip==MT_CHIP_MT7921 && i==2)) return -1;
    }
    *g=next; g->active=g->pending=g->needs_reload=true;
    g->command_open_us=mt_radio_monotonic_us();
    if (chip==MT_CHIP_MT7925) {
        if (io.activate(io.command_ctx)) return -1;
    } else {
        if (set(g,0,0)) return -1;
        const uint32_t bits[3]={0,1U<<29,0};
        for (unsigned i=0;i<3;i++) {
            uint32_t word;
            if (read_control(g,1,&word) || io.registers.write(io.registers.ctx,addresses[0][1],(word&~(1U<<29))|bits[i])) return -1;
        }
        uint32_t word;
        if (read_control(g,1,&word) || (word&(1U<<29))) return -1;
        for (unsigned i=0;i<11;i++)
            if (io.registers.read(io.registers.ctx,0x83088600+4*i,&word) || word) return -1;
        if (set(g,2,0x30000) || set(g,0,5)) return -1;
    }
    g->command_closed_us=mt_radio_monotonic_us();
    g->ready=true;
    return 0;
}
static int activate(void *ctx) {
    mt7921_dev_t *dev=ctx;
    uint8_t request[8], reply[256]; uint32_t len=sizeof(reply),status;
    if (mt_histogram_request(dev->usb.chip,request,sizeof(request))<0 || mt7921_uni_option(dev->mcu.prof,0x36,false)!=7 ||
        mt7921_mcu_uni(&dev->mcu,0x36,request,sizeof(request),true,reply,&len,1000) ||
        mt_histogram_ack(dev->usb.chip,reply,len,dev->mcu.msg_seq,&status) || status) return -1;
    return 0;
}
int mt_histogram_begin_device(mt7921_dev_t *dev, mt_histogram_guard_t *g) {
    if (!dev || !g || g->active || !dev->tuned || dev->tuned_width!=20 || dev->tuned_center!=dev->tuned_control ||
        !((dev->tuned_band==0 && (dev->tuned_control==1 || dev->tuned_control==6 || dev->tuned_control==11)) ||
          (dev->tuned_band==1 && dev->tuned_control==36))) return -1;
    if (dev->usb.chip==MT_CHIP_MT7925 && (!dev->mcu.prof || mt7921_uni_option(dev->mcu.prof,0x36,false)!=7)) return -1;
    mt_histogram_io_t io={mt_radio_device_io(dev),dev,activate};
    int rc=mt_histogram_begin(g,dev->usb.chip,io);
    if (g->active) { g->dev=dev; g->channel_key=channel(dev); }
    return rc;
}
int mt_histogram_finish(mt_histogram_guard_t *g, const uint8_t *raw, size_t len, mt_histogram_sample_t *out) {
    if (!g || !g->active || !g->pending || !g->ready || !out || (g->dev && (!g->dev->tuned || channel(g->dev)!=g->channel_key))) return -1;
    bool modern=g->chip==MT_CHIP_MT7925;
    mt_histogram_sample_t result={0};
    if (modern ? mt_histogram_event(g->chip,raw,len,&result.bins) : (raw!=NULL || len!=0)) return -1;
    result.command_open_us=g->command_open_us; result.command_closed_us=g->command_closed_us;
    result.read_open_us=mt_radio_monotonic_us();
    if (modern) {
        for (unsigned i=0;i<4;i++) {
            uint32_t word;
            if (read_control(g,i,&word) || (word&masks[1][i])) return -1;
        }
        for (unsigned v=0;v<2;v++) for (unsigned i=0;i<11;i++) {
            uint32_t word;
            if (g->io.registers.read(g->io.registers.ctx,0x83001000+v*0x10000+4*i,&word) || word!=result.bins.bins[v][i]) return -1;
        }
    } else {
        if (set(g,0,0)) return -1;
        uint8_t words[44];
        for (unsigned i=0;i<11;i++) {
            uint32_t word;
            if (g->io.registers.read(g->io.registers.ctx,0x83088600+4*i,&word)) return -1;
            for (unsigned j=0;j<4;j++) words[4*i+j]=(uint8_t)(word>>(8*j));
        }
        if (mt_histogram_legacy(g->chip,words,sizeof(words),&result.bins)) return -1;
    }
    result.read_closed_us=mt_radio_monotonic_us();
    g->pending=g->ready=false; *out=result; return 0;
}
int mt_histogram_restore(mt_histogram_guard_t *g) {
    if (!g) return -1;
    if (!g->active) return 0;
    g->ready=false;
    if (g->chip==MT_CHIP_MT7925 && g->pending) return -1;
    int error=0;
    if (g->chip==MT_CHIP_MT7921 && set(g,0,0)) error=-1;
    const unsigned order[2][4]={{1,2,0,0},{1,3,0,2}};
    for (unsigned j=0;j<count(g);j++) {
        unsigned i=order[g->chip][j];
        if (set(g,i,g->saved[i])) error=-1;
    }
    if (!error) g->active=g->pending=false;
    return error;
}
