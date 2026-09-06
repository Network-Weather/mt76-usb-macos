/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#include "mt76_histogram.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint32_t seed=0x13579bdf;
static uint32_t random_word(void) { seed=seed*1664525U+1013904223U; return seed; }
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
    puts("Histogram bounds, wide totals and20,000 malformed-input cases passed");
    return 0;
}
