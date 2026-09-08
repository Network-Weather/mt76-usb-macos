/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#ifndef MT76_CSI_SESSION_H
#define MT76_CSI_SESSION_H
#include "mt76_csi.h"
#include "mt76_session.h"

typedef struct {
    mt76_session_t *session; /* Must outlive capture; serialize all capture methods. */
    bool active, ready, needs_reload;
    uint64_t epoch_ns, configured_ns;
    uint32_t generation;
    uint8_t transmitter[6], receivers;
} mt_csi_capture_t;
/* Zero-initialize guard. Exactly one CSI controller/device, no out-of-band CSI
 * commands or retunes. Narrow pinned MT7925 channel36/20MHz profile. Methods
 * submit their own callbacks: never call from an mt_session_call callback.
 * Validate before I/O. Failed start may leave active/needs_reload true. */
int mt_csi_capture_start(mt76_session_t *session, mt_csi_capture_t *capture,
                          const uint8_t transmitter[6], unsigned receivers);
/* Disable host acceptance immediately. Active stays true if STOP fails.
 * STOP is not full restoration: needs_reload remains true; caller stops the USB
 * worker before explicit firmware reload. Call before session stop/destruction. */
int mt_csi_capture_stop(mt_csi_capture_t *capture);
/* 0 report, 1 filtered/non-CSI/not-ready, -1 invalid report or session context.
 * No USB/queue reads. Context failure clears ready. Output unchanged on nonzero.
 * Preserve packet epoch/generation and session overflow/queue-loss metadata. */
int mt_csi_capture_accept(mt_csi_capture_t *capture, const mt_session_packet_t *packet,
                           mt_beacon_csi_report_t *out);
#endif
