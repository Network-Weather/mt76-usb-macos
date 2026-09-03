/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Offline unit test for mt7921_rxd without hardware. */

#include "mt7921_rxd.h"
#include "mt7921_dev.h"
#include "mt7921_mcu.h"
#include "mt7921_regs.h"

#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <unistd.h>

static inline uint16_t read_le16(const uint8_t *p) {
    uint16_t val;
    memcpy(&val, p, sizeof(val));
    return CFSwapInt16LittleToHost(val);
}

static inline uint32_t read_le32(const uint8_t *p) {
    uint32_t val;
    memcpy(&val, p, sizeof(val));
    return CFSwapInt32LittleToHost(val);
}

static void test_decode_24ghz_beacon(void) {
    uint8_t buf[128] = {0};
    /* Frame payload: 802.11 Beacon (frame[0] = 0x80 -> type 0 = Mgmt, subtype 8 = Beacon) */
    uint8_t frame_body[] = { 0x80, 0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
                             0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66 };
    uint32_t frame_len = sizeof(frame_body);

    /* rxd0: length (dma_len = 24 + frame_len), pkt_type = 2 (NORMAL) */
    uint32_t dma_len = 24 + frame_len;
    uint32_t rxd0 = (dma_len & 0xFFFF) | (PKT_TYPE_NORMAL << 27);
    /* rxd1: no groups, no fcs err */
    uint32_t rxd1 = 0;
    /* rxd2: remove_pad = 0 */
    uint32_t rxd2 = 0;
    /* rxd3: chfreq = 1 (2.4GHz channel 1) */
    uint32_t rxd3 = (1 << 8);

    uint32_t le_rxd0 = CFSwapInt32HostToLittle(rxd0);
    uint32_t le_rxd1 = CFSwapInt32HostToLittle(rxd1);
    uint32_t le_rxd2 = CFSwapInt32HostToLittle(rxd2);
    uint32_t le_rxd3 = CFSwapInt32HostToLittle(rxd3);

    memcpy(buf + 0, &le_rxd0, 4);
    memcpy(buf + 4, &le_rxd1, 4);
    memcpy(buf + 8, &le_rxd2, 4);
    memcpy(buf + 12, &le_rxd3, 4);
    memcpy(buf + 24, frame_body, frame_len);

    mt7921_rxd_frame_t out;
    int ret = mt7921_rxd_decode(buf, 24 + frame_len, &out);
    assert(ret == 0);
    assert(strcmp(out.band, "2.4GHz") == 0);
    assert(out.channel == 1);
    assert(out.frame_family == FRAME_FAMILY_MGMT);
    assert(out.frame_len == frame_len);
    assert(memcmp(out.frame, frame_body, frame_len) == 0);
    printf("PASS: test_decode_24ghz_beacon\n");
}

static void test_decode_5ghz_data(void) {
    uint8_t buf[128] = {0};
    /* Frame payload: 802.11 Data (frame[0] = 0x08 -> type 2 = Data) */
    uint8_t frame_body[] = { 0x08, 0x01, 0x30, 0x00, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff };
    uint32_t frame_len = sizeof(frame_body);

    /* rxd0: pkt_type = 7 (RX_EVENT), pkt_flag = 1 -> remapped to NORMAL_MCU */
    uint32_t dma_len = 24 + frame_len;
    uint32_t rxd0 = (dma_len & 0xFFFF) | (1 << 16) | (PKT_TYPE_RX_EVENT << 27);
    uint32_t rxd1 = 0;
    uint32_t rxd2 = 0;
    /* rxd3: chfreq = 36 (5GHz channel 36) */
    uint32_t rxd3 = (36 << 8);

    uint32_t le_rxd0 = CFSwapInt32HostToLittle(rxd0);
    uint32_t le_rxd1 = CFSwapInt32HostToLittle(rxd1);
    uint32_t le_rxd2 = CFSwapInt32HostToLittle(rxd2);
    uint32_t le_rxd3 = CFSwapInt32HostToLittle(rxd3);

    memcpy(buf + 0, &le_rxd0, 4);
    memcpy(buf + 4, &le_rxd1, 4);
    memcpy(buf + 8, &le_rxd2, 4);
    memcpy(buf + 12, &le_rxd3, 4);
    memcpy(buf + 24, frame_body, frame_len);

    mt7921_rxd_frame_t out;
    int ret = mt7921_rxd_decode(buf, 24 + frame_len, &out);
    assert(ret == 0);
    assert(out.pkt_type == PKT_TYPE_NORMAL_MCU);
    assert(out.pkt_type == 17);
    assert(strcmp(out.band, "5GHz") == 0);
    assert(out.channel == 36);
    assert(out.frame_family == FRAME_FAMILY_DATA);
    assert(out.frame_len == frame_len);
    printf("PASS: test_decode_5ghz_data (normalized PKT_TYPE_NORMAL_MCU = 17)\n");
}

static void test_decode_6ghz_psc(void) {
    uint8_t buf[128] = {0};
    uint8_t frame_body[] = { 0xd4, 0x00, 0x00, 0x00 }; /* Control frame (ACK: 0xd4 -> type 1) */
    uint32_t frame_len = sizeof(frame_body);

    uint32_t dma_len = 24 + frame_len;
    uint32_t rxd0 = (dma_len & 0xFFFF) | (PKT_TYPE_NORMAL << 27);
    uint32_t rxd1 = 0;
    uint32_t rxd2 = 0;
    /* 6GHz PSC channel 53 -> chfreq = 181 + (53 - 1) / 4 = 194 */
    uint32_t rxd3 = (194 << 8);

    uint32_t le_rxd0 = CFSwapInt32HostToLittle(rxd0);
    uint32_t le_rxd1 = CFSwapInt32HostToLittle(rxd1);
    uint32_t le_rxd2 = CFSwapInt32HostToLittle(rxd2);
    uint32_t le_rxd3 = CFSwapInt32HostToLittle(rxd3);

    memcpy(buf + 0, &le_rxd0, 4);
    memcpy(buf + 4, &le_rxd1, 4);
    memcpy(buf + 8, &le_rxd2, 4);
    memcpy(buf + 12, &le_rxd3, 4);
    memcpy(buf + 24, frame_body, frame_len);

    mt7921_rxd_frame_t out;
    int ret = mt7921_rxd_decode(buf, 24 + frame_len, &out);
    assert(ret == 0);
    assert(strcmp(out.band, "6GHz") == 0);
    assert(out.channel == 53);
    assert(out.frame_family == FRAME_FAMILY_CTRL);
    printf("PASS: test_decode_6ghz_psc\n");
}

static void test_pcap_writer(void) {
    const char *tmp_pcap = "/tmp/test_c_writer.pcap";
    FILE *f = NULL;
    int ret = pcap_writer_open(tmp_pcap, &f);
    assert(ret == 0 && f != NULL);

    uint8_t frame_body[] = { 0x80, 0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff };
    mt7921_rxd_frame_t rf = {
        .pkt_type = PKT_TYPE_NORMAL,
        .dma_len = 24 + sizeof(frame_body),
        .fcs_err = false,
        .icv_err = false,
        .band = "5GHz",
        .channel = 36,
        .rssi = -65,
        .frame = frame_body,
        .frame_len = sizeof(frame_body),
        .frame_family = FRAME_FAMILY_MGMT,
        .has_phy = true,
        .phy = {
            .mode = MT_PHY_TYPE_OFDM,
            .mode_name = "OFDM",
            .mcs = 12,
            .rate_mbps = 54.0,
            .bw_mhz = 20
        }
    };

    ret = pcap_writer_write_frame(f, &rf);
    assert(ret == 0);

    /* Second frame with HT MCS */
    rf.phy.mode = MT_PHY_TYPE_HT;
    rf.phy.mode_name = "HT";
    rf.phy.mcs = 7;
    rf.phy.rate_mbps = 65.0;
    ret = pcap_writer_write_frame(f, &rf);
    assert(ret == 0);

    /* Third frame with VHT */
    rf.phy.mode = MT_PHY_TYPE_VHT;
    rf.phy.mode_name = "VHT";
    rf.phy.mcs = 9;
    rf.phy.nss = 2;
    rf.phy.bw_mhz = 80;
    rf.phy.gi = 1;
    rf.phy.rate_mbps = 866.7;
    ret = pcap_writer_write_frame(f, &rf);
    assert(ret == 0);

    /* Fourth frame with HE-SU (160MHz, MCS 11, non-STBC) */
    rf.phy.mode = MT_PHY_TYPE_HE_SU;
    rf.phy.mode_name = "HE-SU";
    rf.phy.mcs = 11;
    rf.phy.nss = 2;
    rf.phy.nsts = 2;
    rf.phy.bw_mhz = 160;
    rf.phy.gi = 0;
    rf.phy.stbc = false;
    rf.phy.rate_mbps = 2402.0;
    ret = pcap_writer_write_frame(f, &rf);
    assert(ret == 0);

    /* Fifth frame with HE-SU + STBC (80MHz, MCS 7, NSS=1, NSTS=2) */
    rf.phy.mode = MT_PHY_TYPE_HE_SU;
    rf.phy.mode_name = "HE-SU";
    rf.phy.mcs = 7;
    rf.phy.nss = 1;
    rf.phy.nsts = 2;
    rf.phy.bw_mhz = 80;
    rf.phy.gi = 1;
    rf.phy.stbc = true;
    rf.phy.rate_mbps = 286.8;
    ret = pcap_writer_write_frame(f, &rf);
    assert(ret == 0);

    /* Sixth frame with HE-MU on 52-tone RU (ru_tones=52, ru_offset=3, MCS 5) */
    rf.phy.mode = MT_PHY_TYPE_HE_MU;
    rf.phy.mode_name = "HE-MU";
    rf.phy.mcs = 5;
    rf.phy.nss = 1;
    rf.phy.nsts = 1;
    rf.phy.bw_mhz = 20;
    rf.phy.gi = 0;
    rf.phy.stbc = false;
    rf.phy.ru_tones = 52;
    rf.phy.ru_offset = 3;
    rf.phy.rate_mbps = 14.1;
    ret = pcap_writer_write_frame(f, &rf);
    assert(ret == 0);

    /* Seventh frame with HE-ER-SU on 106-tone RU (ru_tones=106, MCS 0) */
    rf.phy.mode = MT_PHY_TYPE_HE_EXT_SU;
    rf.phy.mode_name = "HE-ER-SU";
    rf.phy.mcs = 0;
    rf.phy.nss = 1;
    rf.phy.nsts = 1;
    rf.phy.bw_mhz = 20;
    rf.phy.gi = 0;
    rf.phy.stbc = false;
    rf.phy.ru_tones = 106;
    rf.phy.ru_offset = 0;
    rf.phy.rate_mbps = 3.8;
    ret = pcap_writer_write_frame(f, &rf);
    assert(ret == 0);

    pcap_writer_close(f);

    /* Verify file exists, read back, and validate exact radiotap HE bytes */
    FILE *chk = fopen(tmp_pcap, "rb");
    assert(chk != NULL);
    uint8_t pcap_buf[2048];
    size_t rd = fread(pcap_buf, 1, sizeof(pcap_buf), chk);
    fclose(chk);
    assert(rd > 24);

    /* PCAP global header is 24 bytes. Skip first 3 packets (OFDM, HT, VHT) using read_le32 to inspect HE packets */
    size_t off = 24;
    for (int p = 0; p < 3; p++) {
        assert(off + 16 <= rd);
        uint32_t incl_len = read_le32(pcap_buf + off + 8);
        off += 16 + incl_len;
    }

    /* 4th packet is HE-SU 160MHz (non-STBC) */
    assert(off + 16 <= rd);
    uint32_t he1_incl_len = read_le32(pcap_buf + off + 8);
    assert(off + 16 + he1_incl_len <= rd);

    uint8_t *rt1 = pcap_buf + off + 16;
    uint16_t rt1_len = read_le16(rt1 + 2);
    uint32_t rt1_present = read_le32(rt1 + 4);
    assert(rt1_present & (1U << 23));
    assert(rt1_len >= 28);

    uint16_t he1_d1 = read_le16(rt1 + 16);
    uint16_t he1_d2 = read_le16(rt1 + 18);
    uint16_t he1_d3 = read_le16(rt1 + 20);
    uint16_t he1_d4 = read_le16(rt1 + 22);
    uint16_t he1_d5 = read_le16(rt1 + 24);
    uint16_t he1_d6 = read_le16(rt1 + 26);

    assert((he1_d1 & 0x0003) == 0);         /* Format: SU */
    assert((he1_d1 & 0x0020) != 0);         /* DATA_MCS_KNOWN (bit 5) */
    assert((he1_d1 & 0x4000) != 0);         /* BW_RU_ALLOC_KNOWN (bit 14) */
    assert((he1_d2 & 0x0002) != 0);         /* GI_KNOWN (bit 1) */
    assert((he1_d2 & 0x4000) == 0);         /* RU_OFFSET_KNOWN not set for SU */
    assert(((he1_d3 >> 8) & 0x0F) == 11);   /* DATA_MCS == 11 */
    assert((he1_d3 & 0x8000) == 0);         /* STBC == 0 */
    assert(he1_d4 == 0);
    assert((he1_d5 & 0x0F) == 3);           /* DATA_BW_RU_ALLOC == 3 (160 MHz) */
    assert(((he1_d5 >> 4) & 0x03) == 0);    /* GI == 0 (0.8us) */
    assert((he1_d6 & 0x0F) == 2);           /* NSTS == 2 */
    off += 16 + he1_incl_len;

    /* 5th packet is HE-SU 80MHz with STBC (NSS=1, NSTS=2) */
    assert(off + 16 <= rd);
    uint32_t he2_incl_len = read_le32(pcap_buf + off + 8);
    assert(off + 16 + he2_incl_len <= rd);

    uint8_t *rt2 = pcap_buf + off + 16;
    uint16_t he2_d3 = read_le16(rt2 + 20);
    uint16_t he2_d5 = read_le16(rt2 + 24);
    uint16_t he2_d6 = read_le16(rt2 + 26);

    assert(((he2_d3 >> 8) & 0x0F) == 7);    /* DATA_MCS == 7 */
    assert((he2_d3 & 0x8000) != 0);         /* STBC flag set in data3 */
    assert((he2_d5 & 0x0F) == 2);           /* DATA_BW_RU_ALLOC == 2 (80 MHz) */
    assert(((he2_d5 >> 4) & 0x03) == 1);    /* GI == 1 (1.6us) */
    assert((he2_d6 & 0x0F) == 2);           /* NSTS == 2 (preserved for STBC, not halved) */
    off += 16 + he2_incl_len;

    /* 6th packet is HE-MU on 52-tone RU */
    assert(off + 16 <= rd);
    uint32_t he3_incl_len = read_le32(pcap_buf + off + 8);
    assert(off + 16 + he3_incl_len <= rd);

    uint8_t *rt3 = pcap_buf + off + 16;
    uint16_t he3_d1 = read_le16(rt3 + 16);
    uint16_t he3_d2 = read_le16(rt3 + 18);
    uint16_t he3_d5 = read_le16(rt3 + 24);

    assert((he3_d1 & 0x0003) == 2);         /* Format: HE-MU */
    assert((he3_d2 & 0x4000) != 0);         /* RU_OFFSET_KNOWN set in data2 */
    assert(((he3_d2 >> 8) & 0x3F) == 3);    /* RU offset == 3 */
    assert((he3_d5 & 0x0F) == 5);           /* DATA_BW_RU_ALLOC_52T == 5 */
    off += 16 + he3_incl_len;

    /* 7th packet is HE-ER-SU on 106-tone RU */
    assert(off + 16 <= rd);
    uint32_t he4_incl_len = read_le32(pcap_buf + off + 8);
    assert(off + 16 + he4_incl_len <= rd);

    uint8_t *rt4 = pcap_buf + off + 16;
    uint16_t he4_d1 = read_le16(rt4 + 16);
    uint16_t he4_d5 = read_le16(rt4 + 24);

    assert((he4_d1 & 0x0003) == 1);         /* Format: HE-EXT-SU */
    assert((he4_d5 & 0x0F) == 6);           /* DATA_BW_RU_ALLOC_106T == 6 */

    unlink(tmp_pcap);
    printf("PASS: test_pcap_writer\n");
}

static void test_parse_ram_bounds_check(void) {
    /* Create a simulated RAM image: 4 payload bytes + 1 region (40 bytes) + trailer (36 bytes) = 80 bytes total */
    uint8_t bad_blob[80] = {0};
    size_t t = sizeof(bad_blob) - 36;
    bad_blob[t + 2] = 1; /* n_region = 1 */
    size_t base = t - 40;
    uint32_t addr = CFSwapInt32HostToLittle(0x00915000);
    /* Declare region len = 5 (exceeds the 4 payload bytes) -> must fail! */
    uint32_t bad_len = CFSwapInt32HostToLittle(5);
    memcpy(bad_blob + base + 16, &addr, 4);
    memcpy(bad_blob + base + 20, &bad_len, 4);

    ram_trailer_t r;
    int ret = mt7921_parse_ram(bad_blob, sizeof(bad_blob), &r);
    assert(ret == -1);

    /* Test n_region = 0 -> must fail */
    bad_blob[t + 2] = 0;
    ret = mt7921_parse_ram(bad_blob, sizeof(bad_blob), &r);
    assert(ret == -1);

    /* Test n_region > MAX_RAM_REGIONS (e.g. 17) -> must fail */
    bad_blob[t + 2] = 17;
    ret = mt7921_parse_ram(bad_blob, sizeof(bad_blob), &r);
    assert(ret == -1);

    /* Test with region len = 4 (exact match for 4 payload bytes) -> must succeed */
    bad_blob[t + 2] = 1;
    uint32_t good_len = CFSwapInt32HostToLittle(4);
    memcpy(bad_blob + base + 20, &good_len, 4);
    ret = mt7921_parse_ram(bad_blob, sizeof(bad_blob), &r);
    assert(ret == 0);
    assert(r.n_region == 1);
    assert(r.regions[0].len == 4);
    printf("PASS: test_parse_ram_bounds_check\n");
}

static void test_build_probe_request(void) {
    uint8_t mac[6] = { 0x00, 0x11, 0x22, 0x33, 0x44, 0x55 };
    uint8_t frame[128];
    int len = mt7921_build_probe_request(frame, sizeof(frame), mac, "test_ssid", 42);
    assert(len == 41);

    const uint8_t expected[] = {
        0x40, 0x00, 0x00, 0x00,
        0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
        0x00, 0x11, 0x22, 0x33, 0x44, 0x55,
        0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
        0xa0, 0x02,
        0x00, 0x09, 0x74, 0x65, 0x73, 0x74, 0x5f, 0x73, 0x73, 0x69, 0x64,
        0x01, 0x04, 0x82, 0x84, 0x8b, 0x96
    };
    assert(sizeof(expected) == 41);
    assert(memcmp(frame, expected, 41) == 0);
    printf("PASS: test_build_probe_request\n");
}

static void test_build_txwi(void) {
    uint8_t mac[6] = { 0x00, 0x11, 0x22, 0x33, 0x44, 0x55 };
    uint8_t frame[128];
    int frame_len = mt7921_build_probe_request(frame, sizeof(frame), mac, "test_ssid", 42);
    assert(frame_len == 41);

    uint8_t txwi[64];
    int txwi_len = mt7921_build_txwi(txwi, frame, frame_len, 42, 5);
    assert(txwi_len == 64);

    const uint8_t expected_txwi[] = {
        0x69, 0x00, 0x80, 0x20, 0x00, 0x60, 0x02, 0x80,
        0x04, 0x24, 0x00, 0x80, 0x01, 0x78, 0x2a, 0x90,
        0x00, 0x00, 0x00, 0x00, 0x05, 0x04, 0x00, 0x00,
        0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
    };
    assert(sizeof(expected_txwi) == 64);
    assert(memcmp(txwi, expected_txwi, 64) == 0);
    printf("PASS: test_build_txwi\n");
}

static void test_decode_phy_telemetry(void) {
    mt7921_phy_info_t phy;

    /* CCK 1M */
    int ret = mt7921_decode_rxv(0x00000000, 0, &phy);
    assert(ret == 0);
    assert(phy.mode == MT_PHY_TYPE_CCK);
    assert(strcmp(phy.mode_name, "CCK") == 0);
    assert(phy.mcs == 0);
    assert(phy.nss == 1);
    assert(phy.bw_mhz == 20);
    assert(phy.rate_mbps == 1.0);

    /* OFDM 6M (hw idx 11) */
    ret = mt7921_decode_rxv(0x0100000B, 0, &phy);
    assert(ret == 0);
    assert(phy.mode == MT_PHY_TYPE_OFDM);
    assert(strcmp(phy.mode_name, "OFDM") == 0);
    assert(phy.mcs == 11);
    assert(phy.rate_mbps == 6.0);

    /* HT MCS 7 (20MHz, long GI) */
    ret = mt7921_decode_rxv(0x02000007, 0, &phy);
    assert(ret == 0);
    assert(phy.mode == MT_PHY_TYPE_HT);
    assert(strcmp(phy.mode_name, "HT") == 0);
    assert(phy.mcs == 7);
    assert(phy.nss == 1);
    assert(phy.bw_mhz == 20);
    assert(phy.rate_mbps == 65.0);

    /* VHT MCS 9 (80MHz, 2 streams, short GI) */
    uint32_t rxv_vht = (4U << 24) | (1U << 15) | (2U << 12) | (1U << 7) | 9U;
    ret = mt7921_decode_rxv(rxv_vht, 0, &phy);
    assert(ret == 0);
    assert(phy.mode == MT_PHY_TYPE_VHT);
    assert(strcmp(phy.mode_name, "VHT") == 0);
    assert(phy.mcs == 9);
    assert(phy.nss == 2);
    assert(phy.bw_mhz == 80);
    assert(phy.gi == 1);
    assert(phy.rate_mbps == 866.7);

    /* HE-SU MCS 11 (160MHz, 2 streams, 0.8us GI) */
    uint32_t rxv_he = (8U << 24) | (0U << 15) | (3U << 12) | (1U << 7) | 11U;
    ret = mt7921_decode_rxv(rxv_he, 0, &phy);
    assert(ret == 0);
    assert(phy.mode == MT_PHY_TYPE_HE_SU);
    assert(strcmp(phy.mode_name, "HE-SU") == 0);
    assert(phy.mcs == 11);
    assert(phy.nss == 2);
    assert(phy.bw_mhz == 160);
    assert(phy.rate_mbps == 2402.0);

    /* HE-SU MCS 0 without DCM (20MHz, 1 stream, 0.8us GI) -> 8.6 Mbps */
    uint32_t rxv_he_mcs0 = (8U << 24) | (0U << 15) | (0U << 12) | (0U << 7) | 0U;
    ret = mt7921_decode_rxv(rxv_he_mcs0, 0, &phy);
    assert(ret == 0);
    assert(!phy.dcm);
    assert(phy.rate_mbps == 8.6);

    /* HE-SU MCS 0 WITH DCM -> 4.3 Mbps (verifies DCM halves MCS 0 without clamping to 1) */
    uint32_t rxv_he_mcs0_dcm = (8U << 24) | (0U << 15) | (0U << 12) | (0U << 7) | (1U << 4) | 0U;
    ret = mt7921_decode_rxv(rxv_he_mcs0_dcm, 0, &phy);
    assert(ret == 0);
    assert(phy.dcm);
    assert(phy.rate_mbps == 4.3);

    /* HE-MU MCS 0 on 26-tone RU (ru=0) -> 0.9 Mbps */
    uint32_t rxv_he_mu = (11U << 24) | (0U << 15) | (0U << 12) | (0U << 7) | 0U;
    ret = mt7921_decode_rxv(rxv_he_mu, 0, &phy);
    assert(ret == 0);
    assert(phy.ru_tones == 26);
    assert(phy.rate_mbps == 0.9);

    /* HE-EXT-SU MCS 0 on 106-tone RU (bit 5 in rxv0 set) -> 3.8 Mbps */
    uint32_t rxv_he_er = (9U << 24) | (1U << 5) | (0U << 15) | (0U << 12) | (0U << 7) | 0U;
    ret = mt7921_decode_rxv(rxv_he_er, 0, &phy);
    assert(ret == 0);
    assert(phy.ru_tones == 106);
    assert(phy.ru_offset == 0);
    assert(phy.rate_mbps == 3.8);

    /* HE-SU with STBC (80MHz, 2 space-time streams, STBC=1) */
    uint32_t rxv_he_stbc = (8U << 24) | (1U << 22) /* STBC */ | (1U << 15) | (2U << 12) | (1U << 7) /* nsts=1 -> 2 */ | 7U;
    ret = mt7921_decode_rxv(rxv_he_stbc, 0, &phy);
    assert(ret == 0);
    assert(phy.stbc);
    assert(phy.nss == 1);   /* Halved for data rate calculation */
    assert(phy.nsts == 2);  /* Space-time streams preserved for NSTS radiotap */
    assert(phy.rate_mbps == 340.3);

    /* HE-MU on 52-tone RU (ru=40: ru_low=8, ru_high=2 -> ru_offset = 40 - 37 = 3) */
    uint32_t rxv0_mu52 = (11U << 24) | (8U << 28) | (0U << 15) | (0U << 12) | (0U << 7) | 5U;
    uint32_t rxv1_mu52 = 2U;
    ret = mt7921_decode_rxv(rxv0_mu52, rxv1_mu52, &phy);
    assert(ret == 0);
    assert(phy.ru_alloc == 40);
    assert(phy.ru_tones == 52);
    assert(phy.ru_offset == 3);

    printf("PASS: test_decode_phy_telemetry\n");
}

int main(void) {
    printf("Running mt7921_rxd offline unit tests...\n");
    test_decode_24ghz_beacon();
    test_decode_5ghz_data();
    test_decode_6ghz_psc();
    test_pcap_writer();
    test_parse_ram_bounds_check();
    test_build_probe_request();
    test_build_txwi();
    test_decode_phy_telemetry();
    printf("All offline unit tests passed successfully!\n");
    return 0;
}
