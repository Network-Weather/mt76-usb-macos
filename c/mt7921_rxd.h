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

/* PHY Telemetry (transcribed from Connac2 P-RXV / C-RXV descriptors) */
#define MT_PHY_TYPE_CCK        0
#define MT_PHY_TYPE_OFDM       1
#define MT_PHY_TYPE_HT         2
#define MT_PHY_TYPE_HT_GF      3
#define MT_PHY_TYPE_VHT        4
#define MT_PHY_TYPE_HE_SU      8
#define MT_PHY_TYPE_HE_EXT_SU  9
#define MT_PHY_TYPE_HE_TB      10
#define MT_PHY_TYPE_HE_MU      11
#define MT_PHY_TYPE_EHT_SU     13
#define MT_PHY_TYPE_EHT_TRIG   14
#define MT_PHY_TYPE_EHT_MU     15

typedef struct {
    uint8_t mode;          /* MT_PHY_TYPE_* */
    const char *mode_name; /* "CCK", "OFDM", "HT", "HT-GF", "VHT", "HE-SU", etc. */
    uint8_t mcs;           /* Modulation and Coding Scheme */
    uint8_t nss;           /* Spatial streams (1..4) */
    uint16_t bw_mhz;       /* 20, 40, 80, 160 */
    uint8_t gi;            /* Guard Interval */
    bool stbc;             /* Space-Time Block Coding */
    bool ldpc;             /* Low-Density Parity-Check */
    bool dcm;              /* Dual Carrier Modulation */
    uint16_t ru_tones;     /* HE RU allocation size in tones (26, 52, 106, 242, 484, 996, 1992) */
    uint8_t ru_alloc;      /* Raw HE RU allocation index */
    double rate_mbps;      /* Nominal PHY data rate in Mbps */
} mt7921_phy_info_t;

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
    bool has_phy;
    mt7921_phy_info_t phy;
} mt7921_rxd_frame_t;

int mt7921_decode_rxv(uint32_t rxv0, uint32_t rxv1, mt7921_phy_info_t *phy);
int mt7921_frame_family(const uint8_t *frame, uint32_t len);
int mt7921_rxd_decode(const uint8_t *buf, uint32_t buf_len, mt7921_rxd_frame_t *out);

/* Radiotap Pcap writer helpers */
int pcap_writer_open(const char *filename, FILE **f_out);
int pcap_writer_write_frame(FILE *f, const mt7921_rxd_frame_t *rf);
void pcap_writer_close(FILE *f);

#endif /* MT7921_RXD_H */
