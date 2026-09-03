/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#include "mt7921_rxd.h"
#include "mt7921_regs.h"

#include <CoreFoundation/CoreFoundation.h>
#include <string.h>
#include <sys/time.h>

#define LINKTYPE_IEEE802_11_RADIOTAP 127
#define RT_FLAGS                     (1U << 1)
#define RT_CHANNEL                   (1U << 3)
#define RT_DBM_ANTSIGNAL             (1U << 5)
#define RT_FLAG_BADFCS               0x40
#define CH_FLAG_CCK                  0x0020
#define CH_FLAG_OFDM                 0x0040
#define CH_FLAG_2GHZ                 0x0080
#define CH_FLAG_5GHZ                 0x0100

int mt7921_frame_family(const uint8_t *frame, uint32_t len) {
    if (len < 2) return FRAME_FAMILY_OTHER;
    uint8_t frame_type = (frame[0] >> 2) & 0x03;
    if (frame_type == 0) return FRAME_FAMILY_MGMT;
    if (frame_type == 1) return FRAME_FAMILY_CTRL;
    if (frame_type == 2) return FRAME_FAMILY_DATA;
    return FRAME_FAMILY_OTHER;
}

static uint16_t freq_for(const char *band, uint8_t chan) {
    if (strcmp(band, "2.4GHz") == 0) {
        return (chan == 14) ? 2484 : (uint16_t)(2407 + chan * 5);
    }
    if (strcmp(band, "5GHz") == 0) {
        return (uint16_t)(5000 + chan * 5);
    }
    if (strcmp(band, "6GHz") == 0) {
        return (uint16_t)(5950 + chan * 5);
    }
    return 2412;
}

int mt7921_rxd_decode(const uint8_t *buf, uint32_t buf_len, mt7921_rxd_frame_t *out) {
    if (!buf || buf_len < 24 || !out) return -1;
    memset(out, 0, sizeof(*out));

    uint32_t rxd0 = CFSwapInt32LittleToHost(*(const uint32_t*)(buf + 0));
    uint32_t rxd1 = CFSwapInt32LittleToHost(*(const uint32_t*)(buf + 4));
    uint32_t rxd2 = CFSwapInt32LittleToHost(*(const uint32_t*)(buf + 8));
    uint32_t rxd3 = CFSwapInt32LittleToHost(*(const uint32_t*)(buf + 12));

    uint32_t ptype = (rxd0 >> 27) & 0x1F;
    uint32_t pflag = (rxd0 >> RXD0_PKT_FLAG_SHIFT) & RXD0_PKT_FLAG_MASK;
    if (ptype == PKT_TYPE_RX_EVENT && pflag == PKT_FLAG_NORMAL_MCU) {
        ptype = PKT_TYPE_NORMAL_MCU; /* 17 */
    }
    out->pkt_type = ptype;
    out->dma_len = rxd0 & 0xFFFF;
    out->fcs_err = (rxd1 & MT_RXD1_NORMAL_FCS_ERR) != 0;
    out->icv_err = (rxd1 & MT_RXD1_NORMAL_ICV_ERR) != 0;

    if (ptype != PKT_TYPE_NORMAL && ptype != PKT_TYPE_NORMAL_MCU) {
        return -1;
    }
    if (rxd2 & (MT_RXD2_NORMAL_AMSDU_ERR | MT_RXD2_NORMAL_MAX_LEN_ERROR)) {
        return -1;
    }

    uint32_t chfreq = (rxd3 >> 8) & 0xFF;
    if (chfreq > 180) {
        strncpy(out->band, "6GHz", sizeof(out->band));
        out->channel = (uint8_t)((chfreq - 181) * 4 + 1);
    } else if (chfreq > 14) {
        strncpy(out->band, "5GHz", sizeof(out->band));
        out->channel = (uint8_t)chfreq;
    } else {
        strncpy(out->band, "2.4GHz", sizeof(out->band));
        out->channel = (uint8_t)chfreq;
    }

    uint32_t remove_pad = (rxd2 >> 14) & 0x3;
    uint32_t off = 24;
    bool have_rxv_group3 = false;
    uint32_t rxv_group3[2] = {0};
    bool have_rxv_group5 = false;
    uint32_t rxv_group5 = 0;

    if (rxd1 & MT_RXD1_NORMAL_GROUP_4) {
        if (off + 16 > buf_len) return -1;
        out->fc_rxd = (uint16_t)(CFSwapInt32LittleToHost(*(const uint32_t*)(buf + off)) & 0xFFFF);
        off += 16;
    }
    if (rxd1 & MT_RXD1_NORMAL_GROUP_1) {
        off += 16;
    }
    if (rxd1 & MT_RXD1_NORMAL_GROUP_2) {
        off += 8;
    }
    if (rxd1 & MT_RXD1_NORMAL_GROUP_3) {
        if (off + 8 <= buf_len) {
            have_rxv_group3 = true;
            rxv_group3[0] = CFSwapInt32LittleToHost(*(const uint32_t*)(buf + off));
            rxv_group3[1] = CFSwapInt32LittleToHost(*(const uint32_t*)(buf + off + 4));
        }
        off += 8;
        if (rxd1 & MT_RXD1_NORMAL_GROUP_5) {
            off += 24;
            if (off + 4 <= buf_len) {
                have_rxv_group5 = true;
                rxv_group5 = CFSwapInt32LittleToHost(*(const uint32_t*)(buf + off));
            }
            off += 48;
        }
    }

    uint32_t rcpi_word = have_rxv_group5 ? rxv_group5 : (have_rxv_group3 ? rxv_group3[1] : 0);
    if (have_rxv_group5 || have_rxv_group3) {
        int8_t max_rssi = -128;
        bool found = false;
        for (int c = 0; c < 4; c++) {
            uint8_t rcpi = (uint8_t)((rcpi_word >> (c * 8)) & 0xFF);
            int val = ((int)rcpi - 220) / 2;
            if (val < 0) {
                if (!found || val > max_rssi) {
                    max_rssi = (int8_t)val;
                    found = true;
                }
            }
        }
        out->rssi = found ? max_rssi : -100;
    } else {
        out->rssi = -100;
    }

    uint32_t hdr_gap = off + 2 * remove_pad;
    uint32_t end = (out->dma_len > 0 && out->dma_len < buf_len) ? out->dma_len : buf_len;

    if (hdr_gap < end) {
        out->frame = buf + hdr_gap;
        out->frame_len = end - hdr_gap;
        out->frame_family = mt7921_frame_family(out->frame, out->frame_len);
    } else {
        out->frame = NULL;
        out->frame_len = 0;
        out->frame_family = -1;
    }

    return 0;
}

/* ---------------- PCAP Writer ---------------- */

int pcap_writer_open(const char *filename, FILE **f_out) {
    if (!filename || !f_out) return -1;
    FILE *f = fopen(filename, "wb");
    if (!f) return -1;

    /* Global PCAP Header */
    uint32_t magic = 0xA1B2C3D4;
    uint16_t ver_major = 2;
    uint16_t ver_minor = 4;
    int32_t thiszone = 0;
    uint32_t sigfigs = 0;
    uint32_t snaplen = 65535;
    uint32_t linktype = LINKTYPE_IEEE802_11_RADIOTAP;

    uint32_t le_magic = CFSwapInt32HostToLittle(magic);
    uint16_t le_major = CFSwapInt16HostToLittle(ver_major);
    uint16_t le_minor = CFSwapInt16HostToLittle(ver_minor);
    int32_t le_zone = (int32_t)CFSwapInt32HostToLittle((uint32_t)thiszone);
    uint32_t le_sig = CFSwapInt32HostToLittle(sigfigs);
    uint32_t le_snap = CFSwapInt32HostToLittle(snaplen);
    uint32_t le_link = CFSwapInt32HostToLittle(linktype);

    fwrite(&le_magic, 4, 1, f);
    fwrite(&le_major, 2, 1, f);
    fwrite(&le_minor, 2, 1, f);
    fwrite(&le_zone, 4, 1, f);
    fwrite(&le_sig, 4, 1, f);
    fwrite(&le_snap, 4, 1, f);
    fwrite(&le_link, 4, 1, f);

    *f_out = f;
    return 0;
}

int pcap_writer_write_frame(FILE *f, const mt7921_rxd_frame_t *rf) {
    if (!f || !rf || !rf->frame || rf->frame_len == 0) return -1;

    struct timeval tv;
    gettimeofday(&tv, NULL);

    /* Radiotap header */
    uint8_t rt_buf[16] = {0};
    uint32_t present = RT_FLAGS | RT_CHANNEL | RT_DBM_ANTSIGNAL;
    uint16_t freq = freq_for(rf->band, rf->channel);
    uint16_t ch_flags = (strcmp(rf->band, "2.4GHz") == 0) ? (CH_FLAG_2GHZ | CH_FLAG_CCK) : (CH_FLAG_5GHZ | CH_FLAG_OFDM);

    rt_buf[0] = 0; /* version */
    rt_buf[1] = 0; /* pad */
    uint16_t rt_len = 15;
    uint16_t le_rt_len = CFSwapInt16HostToLittle(rt_len);
    uint32_t le_present = CFSwapInt32HostToLittle(present);
    memcpy(rt_buf + 2, &le_rt_len, 2);
    memcpy(rt_buf + 4, &le_present, 4);

    rt_buf[8] = rf->fcs_err ? RT_FLAG_BADFCS : 0;
    rt_buf[9] = 0; /* align 2 */

    uint16_t le_freq = CFSwapInt16HostToLittle(freq);
    uint16_t le_ch_flags = CFSwapInt16HostToLittle(ch_flags);
    memcpy(rt_buf + 10, &le_freq, 2);
    memcpy(rt_buf + 12, &le_ch_flags, 2);

    rt_buf[14] = (uint8_t)rf->rssi;

    uint32_t total_packet_len = rt_len + rf->frame_len;

    /* Packet record header */
    uint32_t le_sec = CFSwapInt32HostToLittle((uint32_t)tv.tv_sec);
    uint32_t le_usec = CFSwapInt32HostToLittle((uint32_t)tv.tv_usec);
    uint32_t le_len = CFSwapInt32HostToLittle(total_packet_len);

    fwrite(&le_sec, 4, 1, f);
    fwrite(&le_usec, 4, 1, f);
    fwrite(&le_len, 4, 1, f);
    fwrite(&le_len, 4, 1, f);

    fwrite(rt_buf, rt_len, 1, f);
    fwrite(rf->frame, rf->frame_len, 1, f);
    return 0;
}

void pcap_writer_close(FILE *f) {
    if (f) {
        fflush(f);
        fclose(f);
    }
}
