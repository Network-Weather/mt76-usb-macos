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
#define RT_RATE                      (1U << 2)
#define RT_CHANNEL                   (1U << 3)
#define RT_DBM_ANTSIGNAL             (1U << 5)
#define RT_MCS                       (1U << 19)
#define RT_VHT                       (1U << 21)
#define RT_HE                        (1U << 23)
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

int mt7921_decode_rxv(uint32_t rxv0, uint32_t rxv1, mt7921_phy_info_t *phy) {
    if (!phy) return -1;
    memset(phy, 0, sizeof(*phy));

    uint32_t idx = rxv0 & 0x7F;
    uint32_t nsts = (rxv0 >> 7) & 0x7;
    bool ldpc = (rxv0 & (1U << 11)) != 0;
    uint32_t bw = (rxv0 >> 12) & 0x7;
    uint32_t gi = (rxv0 >> 15) & 0x3;
    uint32_t stbc = (rxv0 >> 22) & 0x3;
    uint32_t mode = (rxv0 >> 24) & 0xF;
    bool dcm = (idx & (1U << 4)) != 0;

    /* Extract Connac2 HE RU allocation: DW0 bits 31..28 and DW1 bits 3..0 */
    uint32_t ru = ((rxv1 & 0x0F) << 4) | ((rxv0 >> 28) & 0x0F);

    uint32_t nss = nsts + 1;
    if (stbc && nss > 1) {
        nss >>= 1;
    }

    uint32_t mcs = idx;
    if (mode == MT_PHY_TYPE_VHT ||
        mode == MT_PHY_TYPE_HE_SU ||
        mode == MT_PHY_TYPE_HE_EXT_SU ||
        mode == MT_PHY_TYPE_HE_TB ||
        mode == MT_PHY_TYPE_HE_MU) {
        mcs = idx & 0xF;
    }

    uint16_t bw_mhz = 20;
    if (bw == 1) bw_mhz = 40;
    else if (bw == 2) bw_mhz = 80;
    else if (bw == 3) bw_mhz = 160;

    phy->mode = (uint8_t)mode;
    phy->mcs = (uint8_t)mcs;
    phy->nss = (uint8_t)nss;
    phy->bw_mhz = bw_mhz;
    phy->gi = (uint8_t)gi;
    phy->stbc = stbc != 0;
    phy->ldpc = ldpc;
    phy->dcm = dcm;
    phy->ru_alloc = (uint8_t)ru;

    switch (mode) {
        case MT_PHY_TYPE_CCK:
            phy->mode_name = "CCK";
            break;
        case MT_PHY_TYPE_OFDM:
            phy->mode_name = "OFDM";
            break;
        case MT_PHY_TYPE_HT:
            phy->mode_name = "HT";
            break;
        case MT_PHY_TYPE_HT_GF:
            phy->mode_name = "HT-GF";
            break;
        case MT_PHY_TYPE_VHT:
            phy->mode_name = "VHT";
            break;
        case MT_PHY_TYPE_HE_SU:
            phy->mode_name = "HE-SU";
            break;
        case MT_PHY_TYPE_HE_EXT_SU:
            phy->mode_name = "HE-ER-SU";
            break;
        case MT_PHY_TYPE_HE_TB:
            phy->mode_name = "HE-TB";
            break;
        case MT_PHY_TYPE_HE_MU:
            phy->mode_name = "HE-MU";
            break;
        case MT_PHY_TYPE_EHT_SU:
            phy->mode_name = "EHT-SU";
            break;
        case MT_PHY_TYPE_EHT_TRIG:
            phy->mode_name = "EHT-TRIG";
            break;
        case MT_PHY_TYPE_EHT_MU:
            phy->mode_name = "EHT-MU";
            break;
        default:
            phy->mode_name = "UNKNOWN";
            break;
    }

    static const struct {
        double bits;
        double coding;
    } mcs_params[12] = {
        {1.0, 1.0 / 2.0},  /* MCS 0: BPSK 1/2 */
        {2.0, 1.0 / 2.0},  /* MCS 1: QPSK 1/2 */
        {2.0, 3.0 / 4.0},  /* MCS 2: QPSK 3/4 */
        {4.0, 1.0 / 2.0},  /* MCS 3: 16-QAM 1/2 */
        {4.0, 3.0 / 4.0},  /* MCS 4: 16-QAM 3/4 */
        {6.0, 2.0 / 3.0},  /* MCS 5: 64-QAM 2/3 */
        {6.0, 3.0 / 4.0},  /* MCS 6: 64-QAM 3/4 */
        {6.0, 5.0 / 6.0},  /* MCS 7: 64-QAM 5/6 */
        {8.0, 3.0 / 4.0},  /* MCS 8: 256-QAM 3/4 */
        {8.0, 5.0 / 6.0},  /* MCS 9: 256-QAM 5/6 */
        {10.0, 3.0 / 4.0}, /* MCS 10: 1024-QAM 3/4 */
        {10.0, 5.0 / 6.0}  /* MCS 11: 1024-QAM 5/6 */
    };

    double rate = 0.0;
    if (mode == MT_PHY_TYPE_CCK) {
        uint32_t cck_hw = mcs & ~0x4;
        if (cck_hw == 0) rate = 1.0;
        else if (cck_hw == 1) rate = 2.0;
        else if (cck_hw == 2) rate = 5.5;
        else if (cck_hw == 3) rate = 11.0;
    } else if (mode == MT_PHY_TYPE_OFDM) {
        if (mcs == 11) rate = 6.0;
        else if (mcs == 15) rate = 9.0;
        else if (mcs == 10) rate = 12.0;
        else if (mcs == 14) rate = 18.0;
        else if (mcs == 9) rate = 24.0;
        else if (mcs == 13) rate = 36.0;
        else if (mcs == 8) rate = 48.0;
        else if (mcs == 12) rate = 54.0;
    } else if (mode == MT_PHY_TYPE_HT || mode == MT_PHY_TYPE_HT_GF) {
        uint32_t streams = (mcs / 8) + 1;
        uint32_t m = mcs % 8;
        if (m < 8) {
            double bits = mcs_params[m].bits;
            double coding = mcs_params[m].coding;
            double nsd = (bw_mhz == 40) ? 108.0 : 52.0;
            double tsym = (gi != 0) ? 3.6 : 4.0;
            rate = (nsd * bits * coding * streams) / tsym;
        }
    } else if (mode == MT_PHY_TYPE_VHT) {
        if (mcs <= 9) {
            double bits = mcs_params[mcs].bits;
            double coding = mcs_params[mcs].coding;
            double nsd = (bw_mhz == 160) ? 468.0 : ((bw_mhz == 80) ? 234.0 : ((bw_mhz == 40) ? 108.0 : 52.0));
            double tsym = (gi != 0) ? 3.6 : 4.0;
            rate = (nsd * bits * coding * nss) / tsym;
        }
    } else if (mode >= MT_PHY_TYPE_HE_SU && mode <= MT_PHY_TYPE_HE_MU) {
        if (mcs <= 11) {
            double bits = mcs_params[mcs].bits;
            double coding = mcs_params[mcs].coding;
            if (dcm) {
                /* DCM modulates each bit onto 2 subcarriers; halves payload rate */
                bits /= 2.0;
            }

            double nsd = 234.0;
            uint16_t ru_tones = 242;

            if (mode == MT_PHY_TYPE_HE_MU || mode == MT_PHY_TYPE_HE_TB) {
                if (ru <= 36) {
                    ru_tones = 26;
                    nsd = 24.0;
                } else if (ru <= 52) {
                    ru_tones = 52;
                    nsd = 48.0;
                } else if (ru <= 60) {
                    ru_tones = 106;
                    nsd = 102.0;
                } else if (ru <= 64) {
                    ru_tones = 242;
                    nsd = 234.0;
                } else if (ru <= 66) {
                    ru_tones = 484;
                    nsd = 468.0;
                } else if (ru == 67) {
                    ru_tones = 996;
                    nsd = 980.0;
                } else if (ru == 68) {
                    ru_tones = 1992;
                    nsd = 1960.0;
                } else {
                    ru_tones = (bw_mhz == 160) ? 1992 : ((bw_mhz == 80) ? 996 : ((bw_mhz == 40) ? 484 : 242));
                    nsd = (bw_mhz == 160) ? 1960.0 : ((bw_mhz == 80) ? 980.0 : ((bw_mhz == 40) ? 468.0 : 234.0));
                }
            } else if (mode == MT_PHY_TYPE_HE_EXT_SU) {
                if (rxv0 & (1U << 5)) { /* MT_PRXV_TX_ER_SU_106T */
                    ru_tones = 106;
                    nsd = 102.0;
                } else {
                    ru_tones = 242;
                    nsd = 234.0;
                }
            } else {
                /* HE_SU uses full channel bandwidth */
                ru_tones = (bw_mhz == 160) ? 1992 : ((bw_mhz == 80) ? 996 : ((bw_mhz == 40) ? 484 : 242));
                nsd = (bw_mhz == 160) ? 1960.0 : ((bw_mhz == 80) ? 980.0 : ((bw_mhz == 40) ? 468.0 : 234.0));
            }

            phy->ru_tones = ru_tones;

            double tsym = (gi == 0) ? 13.6 : ((gi == 1) ? 14.4 : 16.0);
            rate = (nsd * bits * coding * nss) / tsym;
        }
    }

    phy->rate_mbps = (double)((int)(rate * 10.0 + 0.5)) / 10.0;
    return 0;
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

    if (have_rxv_group3) {
        out->has_phy = true;
        mt7921_decode_rxv(rxv_group3[0], rxv_group3[1], &out->phy);
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
    uint8_t rt_buf[64] = {0};
    uint32_t present = RT_FLAGS | RT_CHANNEL | RT_DBM_ANTSIGNAL;

    bool has_rate = rf->has_phy && (rf->phy.mode == MT_PHY_TYPE_CCK || rf->phy.mode == MT_PHY_TYPE_OFDM) && rf->phy.rate_mbps > 0;
    bool has_mcs = rf->has_phy && (rf->phy.mode == MT_PHY_TYPE_HT || rf->phy.mode == MT_PHY_TYPE_HT_GF);
    bool has_vht = rf->has_phy && (rf->phy.mode == MT_PHY_TYPE_VHT);
    bool has_he = rf->has_phy && (rf->phy.mode >= MT_PHY_TYPE_HE_SU && rf->phy.mode <= MT_PHY_TYPE_HE_MU);

    if (has_rate) present |= RT_RATE;
    if (has_mcs) present |= RT_MCS;
    if (has_vht) present |= RT_VHT;
    if (has_he) present |= RT_HE;

    uint16_t freq = freq_for(rf->band, rf->channel);
    uint16_t ch_flags = (strcmp(rf->band, "2.4GHz") == 0) ? (CH_FLAG_2GHZ | CH_FLAG_CCK) : (CH_FLAG_5GHZ | CH_FLAG_OFDM);

    size_t off = 8;
    /* Bit 1: Flags (1 byte, align 1) */
    rt_buf[off++] = rf->fcs_err ? RT_FLAG_BADFCS : 0;

    /* Bit 2: Rate (1 byte, align 1) */
    if (has_rate) {
        rt_buf[off++] = (uint8_t)(rf->phy.rate_mbps * 2.0 + 0.5);
    }

    /* Bit 3: Channel (4 bytes, align 2) */
    if (off & 1) rt_buf[off++] = 0;
    uint16_t le_freq = CFSwapInt16HostToLittle(freq);
    uint16_t le_ch_flags = CFSwapInt16HostToLittle(ch_flags);
    memcpy(rt_buf + off, &le_freq, 2);
    memcpy(rt_buf + off + 2, &le_ch_flags, 2);
    off += 4;

    /* Bit 5: dBm Ant Signal (1 byte, align 1) */
    rt_buf[off++] = (uint8_t)rf->rssi;

    /* Bit 19: MCS (3 bytes, align 1) */
    if (has_mcs) {
        rt_buf[off++] = 0x07; /* known: bw, mcs, gi */
        rt_buf[off++] = (rf->phy.bw_mhz == 40 ? 1 : 0) | (rf->phy.gi ? 4 : 0);
        rt_buf[off++] = rf->phy.mcs;
    }

    /* Bit 21: VHT (12 bytes, align 2) */
    if (has_vht) {
        if (off & 1) rt_buf[off++] = 0;
        uint16_t vht_known = CFSwapInt16HostToLittle(0x0045); /* STBC, GI, Bandwidth */
        memcpy(rt_buf + off, &vht_known, 2);
        rt_buf[off + 2] = (rf->phy.stbc ? 1 : 0) | (rf->phy.gi ? 4 : 0);
        uint8_t vht_bw = (rf->phy.bw_mhz == 160) ? 11 : ((rf->phy.bw_mhz == 80) ? 4 : ((rf->phy.bw_mhz == 40) ? 1 : 0));
        rt_buf[off + 3] = vht_bw;
        rt_buf[off + 4] = ((rf->phy.mcs & 0x0F) << 4) | (rf->phy.nss & 0x0F);
        rt_buf[off + 5] = 0;
        rt_buf[off + 6] = 0;
        rt_buf[off + 7] = 0;
        rt_buf[off + 8] = rf->phy.ldpc ? 1 : 0;
        rt_buf[off + 9] = 0;
        rt_buf[off + 10] = 0;
        rt_buf[off + 11] = 0;
        off += 12;
    }

    /* Bit 23: HE (12 bytes, align 2) */
    if (has_he) {
        if (off & 1) rt_buf[off++] = 0;
        uint16_t format = (rf->phy.mode == MT_PHY_TYPE_HE_EXT_SU) ? 1 :
                          ((rf->phy.mode == MT_PHY_TYPE_HE_MU) ? 2 :
                          ((rf->phy.mode == MT_PHY_TYPE_HE_TB) ? 3 : 0));

        /* Upstream radiotap struct ieee80211_radiotap_he { __le16 data1..6; } */
        /* data1: format (bits 0..1) + known flags: MCS(bit 5), DCM(bit 6), CODING(bit 7), STBC(bit 9), BW/RU(bit 14) */
        uint16_t he_data1 = format | 0x0020 | 0x0040 | 0x0080 | 0x0200 | 0x4000;

        /* data2: GI_KNOWN (bit 1) */
        uint16_t he_data2 = 0x0002;

        /* data3: bits 8..11 = MCS, bit 12 = DCM, bit 13 = CODING/LDPC, bit 15 = STBC */
        uint16_t he_data3 = ((rf->phy.mcs & 0x0F) << 8) |
                            (rf->phy.dcm ? (1U << 12) : 0) |
                            (rf->phy.ldpc ? (1U << 13) : 0) |
                            (rf->phy.stbc ? (1U << 15) : 0);

        /* data4: spatial reuse / MU STA ID (0) */
        uint16_t he_data4 = 0;

        /* data5: bits 0..3 = DATA_BW_RU_ALLOC, bits 4..5 = GI */
        uint8_t he_bw = (rf->phy.bw_mhz == 160) ? 3 :
                        ((rf->phy.bw_mhz == 80) ? 2 :
                        ((rf->phy.bw_mhz == 40) ? 1 : 0));
        uint16_t he_data5 = (he_bw & 0x0F) | ((rf->phy.gi & 0x03) << 4);

        /* data6: bits 0..3 = NSTS (stream count) */
        uint16_t he_data6 = (rf->phy.nss > 0 ? rf->phy.nss : 1) & 0x0F;

        uint16_t le_d1 = CFSwapInt16HostToLittle(he_data1);
        uint16_t le_d2 = CFSwapInt16HostToLittle(he_data2);
        uint16_t le_d3 = CFSwapInt16HostToLittle(he_data3);
        uint16_t le_d4 = CFSwapInt16HostToLittle(he_data4);
        uint16_t le_d5 = CFSwapInt16HostToLittle(he_data5);
        uint16_t le_d6 = CFSwapInt16HostToLittle(he_data6);
        memcpy(rt_buf + off + 0, &le_d1, 2);
        memcpy(rt_buf + off + 2, &le_d2, 2);
        memcpy(rt_buf + off + 4, &le_d3, 2);
        memcpy(rt_buf + off + 6, &le_d4, 2);
        memcpy(rt_buf + off + 8, &le_d5, 2);
        memcpy(rt_buf + off + 10, &le_d6, 2);
        off += 12;
    }

    uint16_t rt_len = (uint16_t)off;
    rt_buf[0] = 0; /* version */
    rt_buf[1] = 0; /* pad */
    uint16_t le_rt_len = CFSwapInt16HostToLittle(rt_len);
    uint32_t le_present = CFSwapInt32HostToLittle(present);
    memcpy(rt_buf + 2, &le_rt_len, 2);
    memcpy(rt_buf + 4, &le_present, 4);

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
