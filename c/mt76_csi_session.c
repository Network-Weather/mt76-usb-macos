/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#include "mt76_csi_session.h"
#include <string.h>
#include <time.h>

static uint64_t now_ns(void) {
    struct timespec now; clock_gettime(CLOCK_MONOTONIC,&now);
    return (uint64_t)now.tv_sec*UINT64_C(1000000000)+(uint64_t)now.tv_nsec;
}
static int context(mt76_session_t *session, mt_session_stats_t *st) {
    if (!session) return -1;
    mt_session_snapshot(session,st);
    return st->state != MT_SESSION_RUNNING || !st->channel_known || st->band != 1 ||
           st->control != 36 || st->center != 36 || st->width_mhz != 20 ? -1 : 0;
}
static int send(mt7921_dev_t *dev, int action, const mt_csi_capture_t *capture) {
    uint8_t request[16], reply[256]; uint32_t len=sizeof(reply),status;
    unsigned receivers=action==MT_CSI_RECEIVER_COUNT ? capture->receivers : 0;
    const uint8_t *ta=action==MT_CSI_ADD_TRANSMITTER ? capture->transmitter : NULL;
    int size=mt_csi_request(dev->usb.chip,action,receivers,ta,request,sizeof(request));
    if (size<0 || mt7921_uni_option(dev->mcu.prof,0x4a,false)!=7) return -1;
    if (mt7921_mcu_uni(&dev->mcu,0x4a,request,(uint32_t)size,true,reply,&len,1000) ||
        mt_csi_ack(dev->usb.chip,reply,len,dev->mcu.msg_seq,&status) || status) return -1;
    return 0;
}
static int begin(mt7921_dev_t *dev, void *ctx) {
    mt_csi_capture_t *capture=ctx;
    mt_session_stats_t current;
    if (dev->usb.chip != MT_CHIP_MT7925 || context(capture->session,&current) ||
        current.epoch_ns!=capture->epoch_ns || current.generation!=capture->generation) return -1;
    capture->active=capture->needs_reload=true; capture->ready=false;
    const int actions[]={MT_CSI_STOP,MT_CSI_BEACON_SELECTOR,MT_CSI_START,
                         MT_CSI_ADD_TRANSMITTER,MT_CSI_RECEIVER_COUNT};
    for (unsigned i=0;i<sizeof(actions)/sizeof(*actions);i++)
        if (send(dev,actions[i],capture)) return -1;
    capture->configured_ns=now_ns();
    return 0;
}
int mt_csi_capture_start(mt76_session_t *session, mt_csi_capture_t *capture,
                          const uint8_t transmitter[6], unsigned receivers) {
    if (!capture || capture->active || mt_session_chip(session)!=MT_CHIP_MT7925) return -1;
    uint8_t request[16];
    if (mt_csi_request(MT_CHIP_MT7925,MT_CSI_ADD_TRANSMITTER,0,transmitter,request,sizeof(request))<0 ||
        mt_csi_request(MT_CHIP_MT7925,MT_CSI_RECEIVER_COUNT,receivers,NULL,request,sizeof(request))<0) return -1;
    mt_session_stats_t st;
    if (context(session,&st)) return -1;
    capture->session=session; capture->epoch_ns=st.epoch_ns; capture->generation=st.generation;
    capture->receivers=(uint8_t)receivers; memcpy(capture->transmitter,transmitter,6);
    capture->ready=false;
    int result=mt_session_call(session,begin,capture,6000,false);
    if (!result) capture->ready=true;
    return result;
}
static int stop(mt7921_dev_t *dev, void *ctx) { return send(dev,MT_CSI_STOP,ctx); }
int mt_csi_capture_stop(mt_csi_capture_t *capture) {
    if (!capture) return -1;
    capture->ready=false;
    if (!capture->active) return 0;
    int result=mt_session_call(capture->session,stop,capture,2000,false);
    if (!result) capture->active=false;
    return result;
}
int mt_csi_capture_accept(mt_csi_capture_t *capture, const mt_session_packet_t *packet,
                           mt_beacon_csi_report_t *out) {
    if (!capture || !packet || !out || packet->len>MT_SESSION_PACKET_CAPACITY) return -1;
    if (!capture->ready) return 1;
    mt_session_stats_t current;
    if (context(capture->session,&current) || current.epoch_ns!=capture->epoch_ns ||
        current.generation!=capture->generation) { capture->ready=false; return -1; }
    if (packet->epoch_ns!=capture->epoch_ns || packet->generation!=capture->generation ||
        packet->transitioning || packet->received_ns<capture->configured_ns) return 1;
    if (packet->kind!=MT_PACKET_REPLY || packet->len<44 || packet->raw[36]!=0x4a) return 1;
    mt_beacon_csi_report_t report;
    if (mt_beacon_csi_parse(MT_CHIP_MT7925,packet->raw,packet->len,&report)) return -1;
    if (memcmp(report.transmitter,capture->transmitter,6) || report.rx_index>=capture->receivers) return 1;
    *out=report;
    return 0;
}
