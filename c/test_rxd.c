/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Offline unit test for mt7921_rxd without hardware. */

#include "mt7921_rxd.h"
#include "mt7921_chip.h"
#include "mt7921_mcu.h"
#include "mt7921_dev.h"
#include "mt7921_mcu.h"
#include "mt7921_regs.h"

#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <unistd.h>

static bool g_keep_pcap = false;
static const char *g_tmp_pcap = "/tmp/test_c_writer.pcap";

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
    const char *tmp_pcap = g_tmp_pcap;
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

    /* Frame 8: HE-ER-SU 40 MHz full-bandwidth (non-106T, 484-tone, MCS 0, rate 17.2 Mbps) */
    memset(&rf, 0, sizeof(rf));
    rf.frame = frame_body;
    rf.frame_len = sizeof(frame_body);
    strncpy(rf.band, "5GHz", sizeof(rf.band));
    rf.channel = 36;
    rf.has_phy = true;
    rf.phy.mode = MT_PHY_TYPE_HE_EXT_SU;
    rf.phy.mode_name = "HE-ER-SU";
    rf.phy.mcs = 0;
    rf.phy.nss = 1;
    rf.phy.nsts = 1;
    rf.phy.bw_mhz = 40;
    rf.phy.gi = 0;
    rf.phy.stbc = false;
    rf.phy.ru_tones = 484;
    rf.phy.ru_offset = 0;
    rf.phy.rate_mbps = 17.2;
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
    off += 16 + he4_incl_len;

    /* 8th packet is HE-ER-SU 40 MHz full-bandwidth (non-106T) */
    assert(off + 16 <= rd);
    uint32_t he5_incl_len = read_le32(pcap_buf + off + 8);
    assert(off + 16 + he5_incl_len <= rd);

    uint8_t *rt5 = pcap_buf + off + 16;
    uint16_t he5_d1 = read_le16(rt5 + 16);
    uint16_t he5_d5 = read_le16(rt5 + 24);

    assert((he5_d1 & 0x0003) == 1);         /* Format: HE-EXT-SU */
    assert((he5_d5 & 0x0F) == 1);           /* DATA_BW_RU_ALLOC_40MHZ == 1 */

    if (!g_keep_pcap) {
        unlink(tmp_pcap);
    }
    printf("PASS: test_pcap_writer%s\n", g_keep_pcap ? " (preserved test PCAP)" : "");
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

    /* HE-EXT-SU MCS 0 on 106-tone RU (bw=40MHz, bit 5 in rxv0 set) -> 3.8 Mbps */
    uint32_t rxv_he_er = (9U << 24) | (1U << 5) | (0U << 15) | (1U << 12) | (0U << 7) | 0U;
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

    /* HE-ER-SU 40MHz without 106-tone flag (full 40 MHz, nsd=468, rate=17.2 Mbps at MCS 0, GI 0.8us) */
    uint32_t rxv_he_er_40mhz = (9U << 24) /* mode 9 */ | (0U << 15) /* GI 0.8us */ | (1U << 12) /* 40 MHz */ | (0U << 7) | 0U /* MCS 0 */;
    ret = mt7921_decode_rxv(rxv_he_er_40mhz, 0, &phy);
    assert(ret == 0);
    assert(phy.mode == MT_PHY_TYPE_HE_EXT_SU);
    assert(phy.bw_mhz == 40);
    assert(phy.ru_tones == 484);
    assert(phy.rate_mbps == 17.2);

    printf("PASS: test_decode_phy_telemetry\n");
}


/* ---------------- connac3 (MT7925) and chip-profile tests ---------------- */

static void put_le32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

/* A connac3 descriptor: 8 fixed words, optional groups (4/1/2/3[/5] order), then a beacon. */
static size_t build_c3(uint8_t *buf, uint32_t rxd1_groups, bool fcs_err, uint8_t hdr_offset,
                       const uint32_t prxv[4], uint8_t chfreq) {
    static const uint8_t beacon[] = {
        0x80, 0x00, 0x00, 0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
        0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00, 0x01, 0x10, 0x00,
        0, 0, 0, 0, 0, 0, 0, 0, 0x64, 0x00, 0x11, 0x04, 0x00, 0x04, 't', 'e', 's', 't', 0x03, 0x01, 0x06,
        0xde, 0xad, 0xbe, 0xef
    };
    size_t off = 32;
    memset(buf, 0, 512);
    if (rxd1_groups & MT_RXD3_NORMAL_GROUP_4) { put_le32(buf + off, 0x0080); off += 16; }
    if (rxd1_groups & MT_RXD3_NORMAL_GROUP_1) { memset(buf + off, 0x11, 16); off += 16; }
    if (rxd1_groups & MT_RXD3_NORMAL_GROUP_2) { put_le32(buf + off, 0xDEADBEEF); off += 16; }
    if (rxd1_groups & MT_RXD3_NORMAL_GROUP_3) {
        for (int i = 0; i < 4; i++) put_le32(buf + off + 4 * i, prxv ? prxv[i] : 0);
        off += 16;
        if (rxd1_groups & MT_RXD3_NORMAL_GROUP_5) { memset(buf + off, 0x55, 96); off += 96; }
    }
    off += 2 * hdr_offset;
    memcpy(buf + off, beacon, sizeof(beacon));
    size_t total = off + sizeof(beacon);
    put_le32(buf + 0, ((uint32_t)PKT_TYPE_NORMAL << 27) | (uint32_t)total);
    put_le32(buf + 4, rxd1_groups | 5 /* wlan_idx */ | (1U << 27) /* band_idx 1 */);
    put_le32(buf + 8, ((uint32_t)hdr_offset << C3_RXD2_NORMAL_HDR_OFFSET_SHIFT) | (1U << 30));
    put_le32(buf + 12, ((uint32_t)chfreq << 8) | (fcs_err ? C3_RXD3_NORMAL_FCS_ERR : 0));
    return total + 6; /* trailing padding the transfer carries */
}

static uint32_t prxv0(uint32_t rate_idx, uint32_t nsts, bool ldpc, uint32_t ru) {
    return (rate_idx & 0x7F) | ((nsts & 0xF) << 7) | (ldpc ? (1U << 12) : 0) | ((ru & 0x1FF) << 22);
}
static uint32_t prxv2(uint32_t mode, uint32_t frame_mode, uint32_t gi, uint32_t stbc, bool dcm) {
    return (frame_mode & 0x7) | ((gi & 0x3) << 3) | (dcm ? (1U << 5) : 0) | ((stbc & 0x3) << 9) | ((mode & 0xF) << 11);
}

static void test_connac3_decode_groups_and_fcs(void) {
    uint8_t buf[512];
    mt7921_rxd_frame_t rf;
    static const struct { uint32_t groups; uint32_t gap; } cases[] = {
        {0, 32},
        {MT_RXD3_NORMAL_GROUP_4, 48},
        {MT_RXD3_NORMAL_GROUP_4 | MT_RXD3_NORMAL_GROUP_1 | MT_RXD3_NORMAL_GROUP_2, 80},
        {MT_RXD3_NORMAL_GROUP_4 | MT_RXD3_NORMAL_GROUP_1 | MT_RXD3_NORMAL_GROUP_2 | MT_RXD3_NORMAL_GROUP_3, 96},
        {MT_RXD3_NORMAL_GROUP_4 | MT_RXD3_NORMAL_GROUP_1 | MT_RXD3_NORMAL_GROUP_2 | MT_RXD3_NORMAL_GROUP_3 | MT_RXD3_NORMAL_GROUP_5, 192},
        {MT_RXD3_NORMAL_GROUP_3 | MT_RXD3_NORMAL_GROUP_5, 144},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        size_t len = build_c3(buf, cases[i].groups, false, 0, NULL, 6);
        assert(mt7921_rxd_decode_connac3(buf, (uint32_t)len, &rf) == 0);
        assert(rf.frame == buf + cases[i].gap);
        assert(rf.frame_len == 49);           /* beacon (45) + FCS (4); padding excluded via dma_len */
        assert(rf.frame_family == FRAME_FAMILY_MGMT);
        assert(strcmp(rf.band, "2.4GHz") == 0 && rf.channel == 6);
        assert(!rf.fcs_err);
    }
    /* FCS error is RXD3 bit 24 on connac3; band index sits where connac2 kept FCS (RXD1 bit 27). */
    size_t len = build_c3(buf, 0, true, 0, NULL, 6);
    assert(mt7921_rxd_decode_connac3(buf, (uint32_t)len, &rf) == 0 && rf.fcs_err);
    len = build_c3(buf, 0, false, 0, NULL, 6);
    mt7921_rxd_frame_t rf2;
    assert(mt7921_rxd_decode(buf, (uint32_t)len, &rf2) == 0 && rf2.fcs_err); /* connac2 misreads it */
    /* header offset pads in two-byte units */
    len = build_c3(buf, MT_RXD3_NORMAL_GROUP_4, false, 1, NULL, 194);
    assert(mt7921_rxd_decode_connac3(buf, (uint32_t)len, &rf) == 0);
    assert(rf.frame == buf + 50 && strcmp(rf.band, "6GHz") == 0 && rf.channel == 53);
    /* too short, and a non-frame packet type */
    assert(mt7921_rxd_decode_connac3(buf, 31, &rf) == -1);
    put_le32(buf, (0u << 27) | 64);
    assert(mt7921_rxd_decode_connac3(buf, 64, &rf) == -1 && rf.pkt_type == 0);
    printf("PASS: test_connac3_decode_groups_and_fcs\n");
}

static void test_connac3_prxv_rates_and_rssi(void) {
    uint8_t buf[512];
    mt7921_rxd_frame_t rf;
    /* HE-SU MCS 11, NSTS 2, 160 MHz, 0.8 us GI, RCPI 110/90/0/220 -> 2402.0 Mb/s, -55 dBm */
    uint32_t prxv[4] = { prxv0(11, 1, true, 0), 0, prxv2(MT_PHY_TYPE_HE_SU, 3, 0, 0, false), 110 | (90 << 8) | (220u << 24) };
    size_t len = build_c3(buf, MT_RXD3_NORMAL_GROUP_3, false, 0, prxv, 194);
    assert(mt7921_rxd_decode_connac3(buf, (uint32_t)len, &rf) == 0 && rf.has_phy);
    assert(rf.rssi == -55);
    assert(rf.phy.mode == MT_PHY_TYPE_HE_SU && rf.phy.bw_mhz == 160 && rf.phy.nss == 2 && rf.phy.mcs == 11 && rf.phy.ldpc);
    assert(rf.phy.rate_mbps > 2401.9 && rf.phy.rate_mbps < 2402.1);
    /* EHT-MU MCS 13, 2 streams, 160 MHz -> 2882.4 Mb/s */
    mt7921_phy_info_t phy;
    assert(mt7921_decode_prxv3(prxv0(13, 1, false, 0), prxv2(MT_PHY_TYPE_EHT_MU, 3, 0, 0, false), &phy) == 0);
    assert(strcmp(phy.mode_name, "EHT-MU") == 0 && phy.rate_mbps > 2882.3 && phy.rate_mbps < 2882.5);
    /* frame modes 4 and 5 are both 320 MHz, with no rate */
    for (uint32_t fm = 4; fm <= 5; fm++) {
        assert(mt7921_decode_prxv3(prxv0(0, 0, false, 0), prxv2(MT_PHY_TYPE_EHT_SU, fm, 0, 0, false), &phy) == 0);
        assert(phy.bw_mhz == 320 && phy.rate_mbps == 0.0);
    }
    /* VHT MCS 9, 3 streams, 80 MHz, short GI; MCS 12 is refused for VHT */
    assert(mt7921_decode_prxv3(prxv0(9, 2, false, 0), prxv2(MT_PHY_TYPE_VHT, 2, 1, 0, false), &phy) == 0);
    assert(phy.nss == 3 && phy.bw_mhz == 80 && phy.rate_mbps > 1299.9 && phy.rate_mbps < 1300.1);
    assert(mt7921_decode_prxv3(prxv0(12, 0, false, 0), prxv2(MT_PHY_TYPE_VHT, 0, 0, 0, false), &phy) == 0);
    assert(phy.rate_mbps == 0.0);
    /* HE-ER-SU 106-tone flag: width stays 40 MHz, RU 106, DCM halves the rate */
    assert(mt7921_decode_prxv3(prxv0(0x20 | 2, 0, false, 0), prxv2(MT_PHY_TYPE_HE_EXT_SU, 1, 0, 0, true), &phy) == 0);
    assert(phy.bw_mhz == 40 && phy.ru_tones == 106 && phy.dcm && phy.mcs == 2);
    /* OFDM 6 Mb/s */
    assert(mt7921_decode_prxv3(prxv0(11, 0, false, 0), prxv2(MT_PHY_TYPE_OFDM, 0, 0, 0, false), &phy) == 0);
    assert(phy.rate_mbps == 6.0);
    printf("PASS: test_connac3_prxv_rates_and_rssi\n");
}

static void test_chip_table_and_profiles(void) {
    assert(mt7921_chip_for_usb_id(0x0E8D, 0x7961) == MT_CHIP_MT7921);
    assert(mt7921_chip_for_usb_id(0x0846, 0x9072) == MT_CHIP_MT7925);
    assert(mt7921_chip_for_usb_id(0x0846, 0x9050) == MT_CHIP_MT7925);
    assert(mt7921_chip_for_usb_id(0x0E8D, 0x7925) == MT_CHIP_MT7925);
    assert(mt7921_chip_for_usb_id(0x0E8D, 0x6639) == -1); /* MT7927: no blobs, not supported */
    uint16_t vid, pid;
    assert(mt7921_parse_usb_id("0846:9072", &vid, &pid) == 0 && vid == 0x0846 && pid == 0x9072);
    assert(mt7921_parse_usb_id("nope", &vid, &pid) == -1);
    assert(mt7921_parse_usb_id("0846:90721", &vid, &pid) == -1);

    const mt7921_chip_profile_t *p21 = mt7921_chip_profile(MT_CHIP_MT7921);
    const mt7921_chip_profile_t *p25 = mt7921_chip_profile(MT_CHIP_MT7925);
    assert(p21 && p25 && mt7921_chip_profile((mt7921_chip_t)7) == NULL);
    assert(p21->mcu_rxd_len == 36 && p21->rxd_seq_offset == 29 && p21->rxd_status_offset == 32);
    assert(p21->txd1 == ((1U << 31) | (1U << 16)) && p21->chip_id == 0x7961);
    assert(p25->mcu_rxd_len == 44 && p25->rxd_seq_offset == 37 && p25->rxd_status_offset == 40);
    assert(p25->txd1 == 0x4000 && p25->chip_id == 0x7925);
    assert(p25->wfsys_rst_reg == 0x70028600 && p25->wfsys_done_reg == 0x184C1604);
    assert(p25->wfsys_done_mask == 0xFFFFFFFFu && p25->wfsys_done_val == 0x1D1E);
    assert(p25->wfsys_delay_us == 20000 && !p25->wfsys_need_status_sel && p21->wfsys_need_status_sel);
    assert(strncmp(p25->patch_file, "mt7925/", 7) == 0 && strlen(p25->patch_sha256) == 64);

    /* mt7925_mcu_fill_message option byte vs the mt7921 constant */
    assert(mt7921_uni_option(p21, MCU_UNI_CMD_CHIP_CONFIG, true) == MCU_CMD_UNI_EXT_ACK);
    assert(mt7921_uni_option(p25, MCU_UNI_CMD_SNIFFER, false) == 0x7);
    assert(mt7921_uni_option(p25, MCU_UNI_CMD_EFUSE_CTRL, true) == 0x3);
    assert(mt7921_uni_option(p25, MCU_UNI_CMD_CHIP_CONFIG, false) == 0x6);
    assert(mt7921_uni_option(p25, MCU_UNI_CMD_HIF_CTRL, false) == 0x6);
    assert(mt7921_uni_option(p25, MCU_UNI_CMD_CHIP_CONFIG, true) == 0x2);
    assert(mt7921_rxd_decoder_for_chip(MT_CHIP_MT7925) == mt7921_rxd_decode_connac3);
    assert(mt7921_rxd_decoder_for_chip(MT_CHIP_MT7921) == mt7921_rxd_decode);
    printf("PASS: test_chip_table_and_profiles\n");
}

static void test_mt7925_mcu_txd_builders(void) {
    mt7921_usb_t usb;
    memset(&usb, 0, sizeof(usb));
    usb.chip = MT_CHIP_MT7925;
    mt7921_mcu_t mcu;
    mt7921_mcu_init(&mcu, &usb);
    assert(mcu.prof->chip == MT_CHIP_MT7925);

    uint8_t txd[64];
    mt7921_mcu_build_txd(&mcu, txd, 64 + 4, MCU_CMD_PATCH_SEM_CONTROL, 1, 0, MCU_Q_NA, MCU_S2D_H2N);
    assert(read_le32(txd + 4) == 0x4000);                   /* HDR_FORMAT_CMD << 14, no LONG_FORMAT */
    assert((read_le32(txd) & 0xFFFF) == 68);
    assert(read_le16(txd + 32) == 68 - 32 && txd[36] == MCU_CMD_PATCH_SEM_CONTROL && txd[37] == MCU_PKT_ID && txd[39] == 1);

    uint8_t uni[48];
    mt7921_mcu_build_uni_txd(&mcu, uni, 48 + 12, MCU_UNI_CMD_EFUSE_CTRL, 2, false);
    assert(read_le32(uni + 4) == 0x4000);
    assert(read_le16(uni + 34) == MCU_UNI_CMD_EFUSE_CTRL && uni[39] == 2 && uni[42] == MCU_S2D_H2N && uni[43] == 0x7);
    mt7921_mcu_build_uni_txd(&mcu, uni, 48 + 8, MCU_UNI_CMD_CHIP_CONFIG, 3, false);
    assert(uni[43] == 0x6);
    mt7921_mcu_build_uni_txd(&mcu, uni, 48 + 8, MCU_UNI_CMD_EFUSE_CTRL, 4, true);
    assert(uni[43] == 0x3);

    /* The MT7921 builders are unchanged: connac2 word 1 and the fixed EXT_ACK option. */
    usb.chip = MT_CHIP_MT7921;
    mt7921_mcu_init(&mcu, &usb);
    mt7921_mcu_build_txd(&mcu, txd, 68, MCU_CMD_PATCH_SEM_CONTROL, 1, 0, MCU_Q_NA, MCU_S2D_H2N);
    assert(read_le32(txd + 4) == ((1U << 31) | (1U << 16)));
    mt7921_mcu_build_uni_txd(&mcu, uni, 60, MCU_UNI_CMD_CHIP_CONFIG, 2, true);
    assert(read_le32(uni + 4) == ((1U << 31) | (1U << 16)) && uni[43] == MCU_CMD_UNI_EXT_ACK);

    /* Reply body offset follows the profile. */
    uint8_t resp[64] = {0};
    usb.chip = MT_CHIP_MT7925;
    mt7921_mcu_init(&mcu, &usb);
    uint32_t body_len = 0;
    const uint8_t *body = mt7921_mcu_reply_body(&mcu, resp, 60, &body_len);
    assert(body == resp + 44 && body_len == 16);
    assert(mt7921_mcu_reply_body(&mcu, resp, 40, &body_len) == NULL);
    printf("PASS: test_mt7925_mcu_txd_builders\n");
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--keep-pcap") == 0) {
            g_keep_pcap = true;
        } else if (strcmp(argv[i], "--pcap") == 0 && i + 1 < argc) {
            g_keep_pcap = true;
            g_tmp_pcap = argv[++i];
        }
    }
    if (getenv("KEEP_TEST_PCAP")) {
        g_keep_pcap = true;
    }

    printf("Running mt7921_rxd offline unit tests...\n");
    test_decode_24ghz_beacon();
    test_decode_5ghz_data();
    test_decode_6ghz_psc();
    test_pcap_writer();
    test_parse_ram_bounds_check();
    test_build_probe_request();
    test_build_txwi();
    test_decode_phy_telemetry();
    test_connac3_decode_groups_and_fcs();
    test_connac3_prxv_rates_and_rssi();
    test_chip_table_and_profiles();
    test_mt7925_mcu_txd_builders();
    printf("All offline unit tests passed successfully!\n");
    return 0;
}
