/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Protocol facts: gen4m 8fddb9d7, pinned firmware22; docs/STATION_CSI.md.
 * Independent bounded implementation; no firmware code, USB I/O or calibration. */
#include "mt76_csi.h"
#include <string.h>

static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static unsigned le16(const uint8_t *p) { return p[0] | (unsigned)p[1] << 8; }
static bool address_ok(const uint8_t *p) {
    if (!p || (p[0] & 1)) return false;
    unsigned any = 0;
    for (unsigned i = 0; i < 6; i++) any |= p[i];
    return any != 0;
}
int mt_csi_request(int chip, int action, unsigned receivers, const uint8_t *ta,
                    uint8_t *out, size_t capacity) {
    if (chip != MT_CHIP_MT7925 || action < MT_CSI_STOP || action > MT_CSI_REMOVE_TRANSMITTER || !out)
        return -1;
    if ((receivers && action != MT_CSI_RECEIVER_COUNT) ||
        (ta && action != MT_CSI_ADD_TRANSMITTER && action != MT_CSI_REMOVE_TRANSMITTER)) return -1;
    unsigned len = action < 2 ? 8 : action == 2 ? 15 : action == 3 ? 12 : 16;
    if (capacity < len || (action == 3 && receivers != 1 && receivers != 2) ||
        (action >= 4 && !address_ok(ta))) return -1;
    uint8_t request[16] = {0};
    request[4] = action <= 3 ? (uint8_t)action : 4;
    request[6] = (uint8_t)(len - 4);
    if (action == 2) request[9] = 0x20;
    if (action == 3) request[8] = (uint8_t)receivers;
    if (action >= 4) { request[8] = action == MT_CSI_ADD_TRANSMITTER; memcpy(request + 10, ta, 6); }
    memcpy(out, request, len);
    return (int)len;
}
static int event_body(int chip, const uint8_t *raw, size_t len, unsigned eid, unsigned seq) {
    if (chip != MT_CHIP_MT7925 || !raw || len < 44 || seq > 15) return -1;
    uint32_t word = le32(raw), size = word & 65535;
    if (size < 44 || size > len || word >> 27 != 7 || ((word >> 16) & 15) == 1 ||
        raw[36] != eid || raw[37] != seq) return -1;
    return (int)(size - 44);
}
int mt_csi_ack(int chip, const uint8_t *raw, size_t len, uint8_t seq, uint32_t *status) {
    if (!seq || !status || event_body(chip, raw, len, 1, seq) != 8 || le32(raw + 44) != 0x4a) return -1;
    *status = le32(raw + 48);
    return 0;
}
int mt_beacon_csi_parse(int chip, const uint8_t *raw, size_t len, mt_beacon_csi_report_t *out) {
    int length = event_body(chip, raw, len, 0x4a, 0);
    if (!out || length < 8 || length > 8192) return -1;
    const uint8_t *body = raw + 44;
    if (le16(body + 4) || le16(body + 6) != (unsigned)length - 4) return -1;
    const uint8_t *fields[64] = {0};
    uint32_t sizes[64] = {0};
    unsigned pos = 8, last = 64;
    while (pos < (unsigned)length) {
        if ((unsigned)length - pos == 36 && last == 25 && sizes[25] == 4) {
            unsigned any = 0;
            for (unsigned i = pos; i < (unsigned)length; i++) any |= body[i];
            if (!any) break;
        }
        if ((unsigned)length - pos < 8) return -1;
        unsigned tag = le32(body + pos), size = le32(body + pos + 4);
        pos += 8;
        if (tag > 63 || size > 8192 || fields[tag] || size > (unsigned)length - pos) return -1;
        fields[tag] = body + pos; sizes[tag] = size; last = tag;
        pos += size;
    }
    const unsigned required[] = {0, 1, 2, 3, 4, 5, 8, 9, 12, 18, 20, 21, 25};
    for (unsigned i = 0; i < sizeof(required)/sizeof(*required); i++)
        if (sizes[required[i]] != 4) return -1;
    if (le32(fields[0]) != 22 || le32(fields[5]) != 64 || le32(fields[12]) != (11U << 16 | 1) ||
        le32(fields[18]) > 1 || le32(fields[1]) || le32(fields[4]) || le32(fields[8]) ||
        le32(fields[20]) || le32(fields[21]) || sizes[10] != 8 || sizes[6] != 128 || sizes[7] != 128 ||
        !address_ok(fields[10])) return -1;
    mt_beacon_csi_report_t report = {0};
    report.version = 22; report.data_count = 64; report.rx_index = le32(fields[18]);
    report.rx_mode_raw = 1; report.rx_rate_raw = 11; report.channel_index_raw = le32(fields[9]);
    unsigned rssi = le32(fields[2]) & 255;
    report.rssi_raw_s8 = rssi < 128 ? (int)rssi : (int)rssi - 256;
    report.snr_raw = le32(fields[3]); report.mcu_gpt_raw = le32(fields[25]);
    memcpy(report.transmitter, fields[10], 6);
    for (unsigned i = 0; i < 64; i++) {
        unsigned a = le16(fields[6] + 2*i), b = le16(fields[7] + 2*i);
        report.i[i] = (int16_t)(a < 32768 ? (int)a : (int)a - 65536);
        report.q[i] = (int16_t)(b < 32768 ? (int)b : (int)b - 65536);
    }
    *out = report;
    return 0;
}
