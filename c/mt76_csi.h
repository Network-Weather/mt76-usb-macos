/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#ifndef MT76_CSI_H
#define MT76_CSI_H
#include "mt7921_chip.h"

enum { MT_CSI_STOP, MT_CSI_START, MT_CSI_BEACON_SELECTOR, MT_CSI_RECEIVER_COUNT,
       MT_CSI_ADD_TRANSMITTER, MT_CSI_REMOVE_TRANSMITTER };
/* Pure, finite band0 controls, MT7925 only. receivers=0 except count action;
 * transmitter=NULL except filter actions. START clears filters: apply allowlist
 * afterward, receiver restriction LAST, plus host filtering of queued reports.
 * STOP is not full configuration restoration; reload after experimentation. */
int mt_csi_request(int chip, int action, unsigned receivers, const uint8_t *transmitter,
                    uint8_t *out, size_t capacity);
int mt_csi_ack(int chip, const uint8_t *raw, size_t len, uint8_t sequence, uint32_t *status);

typedef struct {
    uint32_t version, data_count, rx_index, tx_index, rx_mode_raw, rx_rate_raw;
    uint32_t channel_index_raw; /* Not an RF channel label. */
    int32_t rssi_raw_s8;
    uint32_t snr_raw, mcu_gpt_raw; /* raw encoding / wrapping MCU clock, not TSF/ToA */
    uint8_t transmitter[6]; /* Sensitive data; never include in default diagnostics. */
    int16_t i[64], q[64];   /* Owned signed coefficients, not calibrated amplitude/phase. */
} mt_beacon_csi_report_t;
/* Strict version22/band0/20MHz OFDM6/64-tone parser; rejects stale CCK storage
 * and unsupported dimensions. Requires separately qualified session/epoch/filter;
 * bytes alone do not prove a beacon or sensor freshness. Output unchanged on error. */
int mt_beacon_csi_parse(int chip, const uint8_t *raw, size_t len, mt_beacon_csi_report_t *out);
#endif
