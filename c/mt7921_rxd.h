/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#ifndef MT7921_RXD_H
#define MT7921_RXD_H

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>

#define FRAME_FAMILY_MGMT    0
#define FRAME_FAMILY_CTRL    1
#define FRAME_FAMILY_DATA    2
#define FRAME_FAMILY_OTHER   3

typedef struct {
    uint32_t pkt_type;
    uint32_t dma_len;
    bool fcs_err;
    bool icv_err;
    char band[8];
    uint8_t channel;
    int8_t rssi;
    uint16_t fc_rxd;
    const uint8_t *frame;
    uint32_t frame_len;
    int frame_family;
} mt7921_rxd_frame_t;

int mt7921_frame_family(const uint8_t *frame, uint32_t len);
int mt7921_rxd_decode(const uint8_t *buf, uint32_t buf_len, mt7921_rxd_frame_t *out);

/* Radiotap Pcap writer helpers */
int pcap_writer_open(const char *filename, FILE **f_out);
int pcap_writer_write_frame(FILE *f, const mt7921_rxd_frame_t *rf);
void pcap_writer_close(FILE *f);

#endif /* MT7921_RXD_H */
