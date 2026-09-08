/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#include "mt76_histogram.h"
#include <string.h>

static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static int body(int chip, const uint8_t *raw, size_t len, unsigned eid, unsigned seq) {
    if (chip!=MT_CHIP_MT7925 || !raw || len<44) return -1;
    uint32_t word=le32(raw), size=word&65535;
    if (size<44 || size>len || word>>27!=7 || ((word>>16)&15)==1 || raw[36]!=eid || raw[37]!=seq) return -1;
    return (int)size-44;
}
int mt_histogram_request(int chip, uint8_t *out, size_t capacity) {
    const uint8_t request[8]={0,0,0,0,2,0,4,0};
    if (chip!=MT_CHIP_MT7925 || !out || capacity<8) return -1;
    memcpy(out,request,8); return 8;
}
int mt_histogram_ack(int chip, const uint8_t *raw, size_t len, uint8_t sequence, uint32_t *status) {
    if (!status || !sequence || sequence>15 || body(chip,raw,len,1,sequence)!=8 || le32(raw+44)!=0x36) return -1;
    *status=le32(raw+48); return 0;
}
static void fill(mt_histogram_bins_t *out, const uint8_t *raw) {
    const int8_t labels[10]={-92,-89,-86,-83,-80,-75,-70,-65,-60,-55};
    memcpy(out->threshold_labels_raw,labels,10);
    for (unsigned view=0;view<out->view_count;view++)
        for (unsigned i=0;i<11;i++) {
            out->bins[view][i]=le32(raw+44*view+4*i);
            out->totals[view]+=out->bins[view][i];
        }
}
int mt_histogram_event(int chip, const uint8_t *raw, size_t len, mt_histogram_bins_t *out) {
    const uint8_t prefix[8]={0,0,0,0,2,0,92,0};
    if (!out || body(chip,raw,len,0x36,0)!=96 || memcmp(raw+44,prefix,8)) return -1;
    mt_histogram_bins_t result={.chip=chip,.source=MT_HISTOGRAM_FIRMWARE_TIMER,.view_count=2};
    fill(&result,raw+52); *out=result; return 0;
}
int mt_histogram_legacy(int chip, const uint8_t *raw, size_t len, mt_histogram_bins_t *out) {
    if (chip!=MT_CHIP_MT7921 || !raw || !out || len!=44) return -1;
    mt_histogram_bins_t result={.chip=chip,.source=MT_HISTOGRAM_LEGACY_ORDINARY,.view_count=1};
    fill(&result,raw); *out=result; return 0;
}
