/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Offline unit test for mt7921_rxd without hardware. */

#include "mt7921_rxd.h"
#include "mt7921_regs.h"

#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

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
    assert(strcmp(out.band, "5GHz") == 0);
    assert(out.channel == 36);
    assert(out.frame_family == FRAME_FAMILY_DATA);
    assert(out.frame_len == frame_len);
    printf("PASS: test_decode_5ghz_data\n");
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

int main(void) {
    printf("Running mt7921_rxd offline unit tests...\n");
    test_decode_24ghz_beacon();
    test_decode_5ghz_data();
    test_decode_6ghz_psc();
    test_pcap_writer();
    printf("All offline unit tests passed successfully!\n");
    return 0;
}
