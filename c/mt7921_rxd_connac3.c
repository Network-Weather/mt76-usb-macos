/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

/* connac3 (MT7925) RX descriptor decode, transcribed from mt7925_mac_fill_rx and
 * mt7925_mac_fill_rx_rate (mt7925/mac.c) and mt76_connac3_mac.h at c5a3bd91. It produces the
 * same mt7921_rxd_frame_t as the connac2 decoder so the pcap writer and the smoke tool do not
 * care which chip received the frame. Differences from connac2: 8 fixed words (32 bytes),
 * group presence bits at RXD1 16..20, FCS error in RXD3 bit 24, every optional group 16 bytes
 * with the 96-byte C-RXV (group 5) stepped over only inside group 3, rate fields spread over
 * P-RXV words 0 and 2, RCPI bytes in P-RXV word 3. */

#include "mt7921_rxd.h"
#include "mt7921_regs.h"

#include <CoreFoundation/CoreFoundation.h>
#include <string.h>

static inline uint32_t c3_read_le32(const void *p) {
    uint32_t val;
    memcpy(&val, p, sizeof(val));
    return CFSwapInt32LittleToHost(val);
}

/* mt7925_mac_fill_rx_rate: FRAME_MODE 0..3 = 20/40/80/160; 4 and 5 both mean 320 MHz. */
static uint16_t frame_mode_to_mhz(uint32_t frame_mode) {
    switch (frame_mode) {
        case 0: return 20;
        case 1: return 40;
        case 2: return 80;
        case 3: return 160;
        case 4: case 5: return 320;
        default: return 0;
    }
}

int mt7921_decode_prxv3(uint32_t v0, uint32_t v2, mt7921_phy_info_t *phy) {
    if (!phy) return -1;
    memset(phy, 0, sizeof(*phy));

    /* mt76_connac3_mac.h P-RXV word 0 */
    uint32_t idx = v0 & 0x7F;              /* MT_PRXV_TX_RATE GENMASK(6, 0) */
    uint32_t nsts = (v0 >> 7) & 0xF;       /* MT_PRXV_NSTS GENMASK(10, 7) */
    bool ldpc = (v0 & (1U << 12)) != 0;    /* MT_PRXV_HT_AD_CODE */
    uint32_t ru = (v0 >> 22) & 0x1FF;      /* MT_PRXV_HE_RU_ALLOC GENMASK(30, 22) */
    bool er_su_106t = (idx & (1U << 5)) != 0; /* MT_PRXV_TX_ER_SU_106T */
    /* word 2 */
    uint32_t frame_mode = v2 & 0x7;        /* MT_PRXV_FRAME_MODE GENMASK(2, 0) */
    uint32_t gi = (v2 >> 3) & 0x3;         /* MT_PRXV_HT_SHORT_GI GENMASK(4, 3) */
    bool dcm = (v2 & (1U << 5)) != 0;      /* MT_PRXV_DCM */
    uint32_t stbc = (v2 >> 9) & 0x3;       /* MT_PRXV_HT_STBC GENMASK(10, 9) */
    uint32_t mode = (v2 >> 11) & 0xF;      /* MT_PRXV_TX_MODE GENMASK(14, 11) */

    uint32_t mcs = idx;
    if (mode == MT_PHY_TYPE_VHT || (mode >= MT_PHY_TYPE_HE_SU && mode <= MT_PHY_TYPE_HE_MU) ||
        mode == MT_PHY_TYPE_EHT_SU || mode == MT_PHY_TYPE_EHT_TRIG || mode == MT_PHY_TYPE_EHT_MU) {
        mcs = idx & 0xF;
    }

    phy->mode = (uint8_t)mode;
    phy->mcs = (uint8_t)mcs;
    phy->nss = (uint8_t)(nsts + 1);  /* the driver keeps nss = NSTS + 1; STBC is a flag */
    phy->nsts = (uint8_t)(nsts + 1);
    phy->bw_mhz = frame_mode_to_mhz(frame_mode);
    phy->gi = (uint8_t)gi;
    phy->stbc = stbc != 0;
    phy->ldpc = ldpc;
    phy->dcm = dcm;
    phy->ru_alloc = (uint16_t)ru;

    uint8_t offs = 0;
    if (mode == MT_PHY_TYPE_HE_MU || mode == MT_PHY_TYPE_HE_TB) {
        if (ru <= 36) offs = (uint8_t)ru;
        else if (ru <= 52) offs = (uint8_t)(ru - 37);
        else if (ru <= 60) offs = (uint8_t)(ru - 53);
        else if (ru <= 64) offs = (uint8_t)(ru - 61);
        else if (ru <= 66) offs = (uint8_t)(ru - 65);
    }
    phy->ru_offset = offs;

    static const char *names[16] = {
        "CCK", "OFDM", "HT", "HT-GF", "VHT", "mode5", "mode6", "mode7",
        "HE-SU", "HE-ER-SU", "HE-TB", "HE-MU", "mode12", "EHT-SU", "EHT-TRIG", "EHT-MU"
    };
    phy->mode_name = names[mode & 0xF];

    mt7921_phy_fill_rate(phy, ru, er_su_106t);
    return 0;
}

int mt7921_rxd_decode_connac3(const uint8_t *buf, uint32_t buf_len, mt7921_rxd_frame_t *out) {
    if (!buf || buf_len < C3_RXD_FIXED_LEN || !out) return -1;
    memset(out, 0, sizeof(*out));

    uint32_t rxd0 = c3_read_le32(buf + 0);
    uint32_t rxd1 = c3_read_le32(buf + 4);
    uint32_t rxd2 = c3_read_le32(buf + 8);
    uint32_t rxd3 = c3_read_le32(buf + 12);
    uint32_t rxd4 = c3_read_le32(buf + 16);
    (void)rxd4;

    uint32_t ptype = (rxd0 >> 27) & 0x1F;
    uint32_t pflag = (rxd0 >> RXD0_PKT_FLAG_SHIFT) & RXD0_PKT_FLAG_MASK;
    if (ptype != PKT_TYPE_NORMAL) {
        /* mt7925_queue_rx_skb: software packet type 0x3801 (masked 0x380F) is a frame */
        uint32_t sw_type = (rxd0 >> 16) & 0xFFFF;
        if ((sw_type & C3_RXD0_SW_PKT_TYPE_MAP) == C3_RXD0_SW_PKT_TYPE_FRAME) ptype = PKT_TYPE_NORMAL;
    }
    if (ptype == PKT_TYPE_RX_EVENT && pflag == PKT_FLAG_NORMAL_MCU) {
        ptype = PKT_TYPE_NORMAL_MCU;
    }
    out->pkt_type = ptype;
    out->dma_len = rxd0 & 0xFFFF;
    out->fcs_err = (rxd3 & C3_RXD3_NORMAL_FCS_ERR) != 0;
    out->icv_err = (rxd1 & C3_RXD1_NORMAL_ICV_ERR) != 0;

    if (ptype != PKT_TYPE_NORMAL && ptype != PKT_TYPE_NORMAL_MCU) return -1;
    if (rxd2 & (C3_RXD2_NORMAL_AMSDU_ERR | C3_RXD2_NORMAL_MAX_LEN_ERROR)) return -1;

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

    uint32_t remove_pad = (rxd2 >> C3_RXD2_NORMAL_HDR_OFFSET_SHIFT) & C3_RXD2_NORMAL_HDR_OFFSET_MASK;
    uint32_t off = C3_RXD_FIXED_LEN;
    bool have_prxv = false;
    uint32_t prxv[4] = {0};

    /* Groups in mt7925_mac_fill_rx order: 4, 1, 2, 3 (+5 inside 3). */
    if (rxd1 & MT_RXD3_NORMAL_GROUP_4) {
        if (off + C3_GROUP_LEN > buf_len) return -1;
        out->fc_rxd = (uint16_t)(c3_read_le32(buf + off) & 0xFFFF); /* MT_RXD8_FRAME_CONTROL */
        off += C3_GROUP_LEN;
    }
    if (rxd1 & MT_RXD3_NORMAL_GROUP_1) {
        off += C3_GROUP_LEN;
    }
    if (rxd1 & MT_RXD3_NORMAL_GROUP_2) {
        off += C3_GROUP_LEN;
    }
    if (rxd1 & MT_RXD3_NORMAL_GROUP_3) {
        if (off + C3_GROUP_LEN <= buf_len) {
            have_prxv = true;
            for (int i = 0; i < 4; i++) prxv[i] = c3_read_le32(buf + off + 4 * i);
        }
        off += C3_GROUP_LEN;
        if (rxd1 & MT_RXD3_NORMAL_GROUP_5) {
            off += C3_GROUP5_LEN;
        }
    }
    /* Group 5 without group 3 is not stepped over, as in the driver; the frame slice is then
     * whatever follows, so callers see it through the 802.11 header validity. */

    if (have_prxv) {
        /* RCPI0..3 are the four bytes of P-RXV word 3, chain 0 low. */
        int8_t max_rssi = -128;
        bool found = false;
        for (int c = 0; c < 4; c++) {
            uint8_t rcpi = (uint8_t)((prxv[3] >> (c * 8)) & 0xFF);
            int val = (int)rcpi / 2 - 110; /* to_rssi(): rcpi / 2 - 110, integer division as upstream */
            if (val < 0 && (!found || val > max_rssi)) {
                max_rssi = (int8_t)val;
                found = true;
            }
        }
        out->rssi = found ? max_rssi : -100;
        out->has_phy = true;
        mt7921_decode_prxv3(prxv[0], prxv[2], &out->phy);
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
