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
        .frame_family = FRAME_FAMILY_MGMT
    };

    ret = pcap_writer_write_frame(f, &rf);
    assert(ret == 0);
    pcap_writer_close(f);

    /* Verify file size is > 24 + 16 + 15 + frame_len */
    FILE *chk = fopen(tmp_pcap, "rb");
    assert(chk != NULL);
    fseek(chk, 0, SEEK_END);
    long sz = ftell(chk);
    fclose(chk);
    assert(sz == 24 + 16 + 15 + (long)sizeof(frame_body));
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

int main(void) {
    printf("Running mt7921_rxd offline unit tests...\n");
    test_decode_24ghz_beacon();
    test_decode_5ghz_data();
    test_decode_6ghz_psc();
    test_pcap_writer();
    test_parse_ram_bounds_check();
    test_build_probe_request();
    test_build_txwi();
    printf("All offline unit tests passed successfully!\n");
    return 0;
}
