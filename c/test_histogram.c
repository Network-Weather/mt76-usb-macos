/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#include "mt76_histogram.h"
#include "mt76_histogram_acquisition.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint32_t seed=0x13579bdf;
static uint32_t random_word(void) { seed=seed*1664525U+1013904223U; return seed; }
typedef struct { unsigned chip,operations,fail; uint32_t regs[4],bins[2][11]; } fake_t;
static const uint32_t reg_addresses[2][4]={{0x83082004,0x83088230,0x83088234,0},
                                         {0x83082004,0x83088230,0x83092004,0x83098230}};
static int note(fake_t *f) { return ++f->operations==f->fail ? -1 : 0; }
static int read_word(void *ctx, uint32_t address, uint32_t *word) {
    fake_t *f=ctx;
    if (note(f)) return -1;
    for (unsigned i=0;i<(f->chip?4U:3U);i++) if(address==reg_addresses[f->chip][i]) { *word=f->regs[i]; return 0; }
    for (unsigned v=0;v<(f->chip?2U:1U);v++) {
        uint32_t base=f->chip ? 0x83001000+v*0x10000 : 0x83088600;
        if (address>=base && address<base+44 && !((address-base)%4)) { *word=f->bins[v][(address-base)/4]; return 0; }
    }
    assert(0); return -1;
}
static int write_word(void *ctx, uint32_t address, uint32_t word) {
    fake_t *f=ctx;
    for (unsigned i=0;i<(f->chip?4U:3U);i++) if(address==reg_addresses[f->chip][i]) {
        f->regs[i]=word;
        if (i==1 && (word&(1U<<29))) memset(f->bins,0,sizeof(f->bins));
        return note(f); /* May report failure after the write reached hardware. */
    }
    assert(0); return -1;
}
static int activate(void *ctx) {
    fake_t *f=ctx; f->regs[0]|=5; f->regs[2]|=5; return note(f);
}
static void guard_case(unsigned chip,unsigned phase,unsigned fail) {
    fake_t f={.chip=chip};
    for (unsigned i=0;i<4;i++) f.regs[i]=0x40000000;
    if (!chip) f.regs[2]|=0x10000;
    mt_histogram_io_t io={{&f,read_word,write_word,NULL},&f,activate};
    mt_histogram_guard_t guard={0};
    if (!phase) f.fail=fail;
    int rc=mt_histogram_begin(&guard,(int)chip,io);
    if (rc) {
        assert(!guard.ready);
        if (guard.active) {
            assert(guard.pending && guard.needs_reload); f.fail=0;
            unsigned before=f.operations;
            assert(mt_histogram_restore(&guard)==(chip?-1:0));
            if (chip) assert(f.operations==before);
        }
        return;
    }
    f.fail=0;
    if (chip) { f.regs[0]&=~7U; f.regs[2]&=~7U; }
    uint8_t raw[140]={140,0,0,7<<3}; raw[36]=0x36; raw[48]=2; raw[50]=92;
    for (unsigned v=0;v<2;v++) for (unsigned i=0;i<11;i++) {
        f.bins[v][i]=11*v+i; raw[52+44*v+4*i]=(uint8_t)(11*v+i);
    }
    mt_histogram_sample_t sample,before;
    memset(&sample,0xa5,sizeof(sample)); before=sample;
    if (phase==1) f.fail=f.operations+fail;
    rc=mt_histogram_finish(&guard,chip?raw:NULL,chip?sizeof(raw):0,&sample);
    if (rc) {
        assert(!memcmp(&sample,&before,sizeof(sample)) && guard.pending && guard.active);
        f.fail=0; assert(mt_histogram_restore(&guard)==(chip?-1:0)); return;
    }
    assert(!sample.coverage_known && !sample.sample_period_ns && !guard.pending && !guard.ready);
    f.fail=phase==2 ? f.operations+fail : 0;
    rc=mt_histogram_restore(&guard);
    if (rc) { assert(guard.active); f.fail=0; assert(!mt_histogram_restore(&guard)); }
    assert(!guard.active && guard.needs_reload);
}
int main(void) {
    uint8_t raw[160]={140,0,0,7<<3}; raw[36]=0x36; raw[48]=2; raw[50]=92;
    memset(raw+52,255,88);
    mt_histogram_bins_t out, before;
    assert(!mt_histogram_event(MT_CHIP_MT7925,raw,140,&out));
    assert(out.totals[0]==UINT64_C(11)*UINT32_MAX && out.totals[1]==out.totals[0]);
    assert(!mt_histogram_legacy(MT_CHIP_MT7921,raw+52,44,&out));
    assert(out.view_count==1 && out.totals[1]==0);
    for (unsigned i=0;i<20000;i++) {
        for (unsigned j=0;j<sizeof(raw);j++) raw[j]=(uint8_t)(random_word()>>24);
        size_t len=random_word()%sizeof(raw);
        if (!(i%3)) { raw[0]=140; raw[1]=0; raw[2]=0; raw[3]=7<<3; raw[36]=0x36; raw[37]=0; }
        memset(&out,0xa5,sizeof(out)); before=out;
        int rc=mt_histogram_event(MT_CHIP_MT7925,raw,len,&out);
        if (rc) assert(!memcmp(&out,&before,sizeof(out)));
        memset(&out,0xa5,sizeof(out)); before=out;
        rc=mt_histogram_legacy(MT_CHIP_MT7921,raw,len,&out);
        if (rc) assert(!memcmp(&out,&before,sizeof(out)));
        uint32_t status=123;
        rc=mt_histogram_ack(MT_CHIP_MT7925,raw,len,(uint8_t)(i%17),&status);
        if (rc) assert(status==123);
    }
    for (unsigned chip=0;chip<2;chip++) for(unsigned phase=0;phase<3;phase++)
        for(unsigned fail=1;fail<=64;fail++) guard_case(chip,phase,fail);
    puts("Histogram bounds, guard faults and20,000 malformed-input cases passed");
    return 0;
}
