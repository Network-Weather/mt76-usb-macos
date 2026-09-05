/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Bounded, redacted native acquisition experiment. No system networking. */
#include "mt7921_radio.h"
#include "mt7921_rxd.h"
#include <CommonCrypto/CommonDigest.h>
#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static void stop_handler(int sig) { (void)sig; stopping = 1; }
static void quiet(const char *fmt, ...) { (void)fmt; }
static int number(const char *s, int lo, int hi, int *out) {
    char *end;
    errno = 0;
    long n = strtol(s, &end, 10);
    if (errno || !*s || *end || n < lo || n > hi) return -1;
    *out = (int)n;
    return 0;
}
static uint8_t *firmware(const char *dir, const char *name, const char *pin, size_t *len) {
    char path[4096], digest[65];
    int n = snprintf(path, sizeof(path), "%s/%s", dir, name);
    if (n < 0 || (size_t)n >= sizeof(path)) return NULL;
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END)) { fclose(f); return NULL; }
    long size = ftell(f);
    if (size <= 0 || size > 8 * 1024 * 1024 || fseek(f, 0, SEEK_SET)) { fclose(f); return NULL; }
    uint8_t *p = malloc((size_t)size);
    if (!p || fread(p, 1, (size_t)size, f) != (size_t)size) { free(p); fclose(f); return NULL; }
    fclose(f);
    unsigned char sha[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(p, (CC_LONG)size, sha);
    for (unsigned i = 0; i < sizeof(sha); i++) snprintf(digest + 2 * i, 3, "%02x", sha[i]);
    if (strcmp(digest, pin)) { free(p); return NULL; }
    *len = (size_t)size;
    return p;
}
static int controlled_frame(uint8_t *frame, unsigned seq, int rate) {
    static const uint8_t source[] = {2, 0, 0, 0, 0, 1};
    int len = mt7921_build_probe_request(frame, 128, source, "NW-C-parity", (uint16_t)seq);
    if (len < 0) return len;
    if (rate != MT_PROBE_CCK1) {
        len -= 6;
        frame[len++] = 1; frame[len++] = 2;
        frame[len++] = 0x8c; frame[len++] = 0x6c;
    }
    return len;
}
static void sample_json(const mt_mib_sample_t *s) {
    printf("{\"opened_us\":%" PRIu64 ",\"closed_us\":%" PRIu64
           ",\"counter_bits\":%u,\"dropped_frames\":%u,\"values\":{",
           s->opened_us, s->closed_us, s->counter_bits, s->dropped_frames);
    for (size_t i = 0; i < s->count; i++)
        printf("%s\"%u\":%" PRIu64, i ? "," : "", s->offsets[i], s->values[i]);
    printf("}}");
}
static int dwell(mt7921_dev_t *dev, const char *phase, int seconds, bool mib,
                  int count, int rate, int power, FILE *pcap) {
    const uint32_t offsets[] = {dev->usb.chip == MT_CHIP_MT7925 ? 19 : 11, 20};
    size_t n = dev->usb.chip == MT_CHIP_MT7925 ? 2 : 1;
    mt_mib_sample_t before = {0}, after = {0};
    bool before_ok = !mib || mt_mib_read(dev, offsets, n, &before) == 0;
    if (!before_ok) { fprintf(stderr, "MIB baseline failed\n"); return -1; }
    unsigned frames = 0, timestamps = 0, g5 = 0, timeouts = 0, errors = 0, decode_errors = 0;
    unsigned sent = 0, exact = 0, unique = 0, rate_matches = 0, marker_frames = 0;
    unsigned masks[32] = {0}, seen[60] = {0};
    uint32_t first_ts = 0, last_ts = 0;
    int signal_sum = 0;
    uint64_t started = mt_radio_monotonic_us(), next_tx = started + 200000;
    int result = 0;
    while (!stopping && mt_radio_monotonic_us() - started < (uint64_t)seconds * 1000000) {
        uint64_t now = mt_radio_monotonic_us();
        if (sent < (unsigned)count && now >= next_tx) {
            uint8_t frame[128];
            int len = controlled_frame(frame, sent, rate);
            if (len < 0 || mt_probe_transmit(dev, frame, (size_t)len, sent, rate, power)) {
                result = -1; break;
            }
            sent++;
            next_tx = mt_radio_monotonic_us() + 50000;
        }
        uint8_t raw[65536];
        uint32_t len = sizeof(raw);
        int ret = mt7921_rx_read(dev, raw, &len, count ? 5 : 100);
        if (ret == MT7921_ERR_TIMEOUT) { timeouts++; continue; }
        if (ret) { errors++; result = -1; break; }
        if (len >= 4 && (raw[3] >> 3) == 0) {
            mt_tx_status_t statuses[128];
            int total = mt_tx_status_parse(dev->usb.chip, raw, len, statuses, 128);
            if (total < 0) { decode_errors++; continue; }
            for (int i = 0; i < total; i++) {
                mt_tx_status_t *s = &statuses[i];
                printf("{\"event\":\"tx_status\",\"format\":%u,\"sequence\":%u,"
                       "\"rate_raw\":%u,\"power_raw\":%u,\"power_signed\":%d,"
                       "\"pid\":%u,\"error_bits_16_22\":%u,\"tx_count\":",
                       s->format, s->sequence, s->rate_raw, s->power_raw, s->power_signed,
                       s->pid, s->error_bits_16_22);
                if (s->has_tx_count) printf("%u", s->tx_count); else printf("null");
                puts("}");
            }
            continue;
        }
        mt7921_rxd_frame_t f;
        ret = mt7921_rxd_decoder_for_chip(dev->usb.chip)(raw, len, &f);
        if (ret) {
            if (len >= 24 && (f.pkt_type == PKT_TYPE_NORMAL || f.pkt_type == PKT_TYPE_NORMAL_MCU))
                decode_errors++;
            continue;
        }
        if (!f.frame_len) continue;
        frames++; masks[f.group_mask]++;
        g5 += f.g5_words != 0;
        if (f.has_timestamp) {
            if (!timestamps) first_ts = f.timestamp;
            last_ts = f.timestamp;
            timestamps++;
        }
        if (pcap && pcap_writer_write_frame(pcap, &f)) { result = -1; break; }
        if (f.fcs_err || f.frame_len < 37 || f.frame[0] != 0x40 || f.frame[1] ||
            f.frame[24] != 0 || f.frame[25] != 11 || memcmp(f.frame + 26, "NW-C-parity", 11)) continue;
        marker_frames++;
        unsigned seq = (f.frame[22] | (unsigned)f.frame[23] << 8) >> 4;
        if (seq >= 60) continue;
        uint8_t expected[128];
        int expected_len = controlled_frame(expected, seq, rate);
        if (expected_len != (int)f.frame_len || memcmp(expected, f.frame, f.frame_len)) continue;
        exact++;
        if (!seen[seq]) { unique++; seen[seq] = 1; signal_sum += f.rssi; }
        double expected_rate = rate == MT_PROBE_CCK1 ? 1 : rate == MT_PROBE_OFDM6 ? 6 : 54;
        rate_matches += f.has_phy && f.phy.rate_mbps == expected_rate;
    }
    uint64_t elapsed = mt_radio_monotonic_us() - started;
    bool after_ok = !mib || mt_mib_read(dev, offsets, n, &after) == 0;
    printf("{\"event\":\"dwell\",\"phase\":\"%s\",\"elapsed_us\":%" PRIu64
           ",\"frames\":%u,\"timestamps\":%u,\"first_timestamp\":%u,\"last_timestamp\":%u,"
           "\"group5_frames\":%u,\"timeouts\":%u,\"usb_errors\":%u,\"decode_errors\":%u,"
           "\"submitted\":%u,\"synthetic_marker_frames\":%u,\"synthetic_exact\":%u,"
           "\"synthetic_unique\":%u,\"synthetic_rate_matches\":%u,\"synthetic_mean_rssi\":",
           phase, elapsed, frames, timestamps, first_ts, last_ts, g5, timeouts, errors, decode_errors,
           sent, marker_frames, exact, unique, rate_matches);
    if (unique) printf("%.2f", (double)signal_sum / unique); else printf("null");
    printf(",\"group_masks\":{");
    bool comma = false;
    for (unsigned i = 0; i < 32; i++) if (masks[i]) {
        printf("%s\"%02x\":%u", comma ? "," : "", i, masks[i]); comma = true;
    }
    printf("},\"mib_before\":"); sample_json(&before);
    printf(",\"mib_after\":"); sample_json(&after);
    printf(",\"mib_ok\":%s,\"counter_window_us\":", after_ok ? "true" : "false");
    if (mib && after_ok) printf("%.1f", ((double)after.opened_us + after.closed_us -
                                       before.opened_us - before.closed_us) / 2);
    else printf("null");
    puts("}");
    return result || !after_ok || sent != (unsigned)count ? -1 : 0;
}
static void usage(void) {
    fprintf(stderr, "mt76_radio_probe --usb-id VVVV:PPPP [--fw DIR] [--seconds 1..60]\n"
            "  [--band 2.4GHz|5GHz|6GHz --channel 6|36|149|37] [--mib] [--g5-cycle]\n"
            "  [--pcap PATH] [--transmit 1..60 --rate cck1|ofdm6|ofdm54 --power-code 0|-8|-16|-32\n"
            "   --acknowledge-experimental-transmit]\n"
            "20 MHz only in this bounded experiment; existing smoke supports wider capture.\n");
}
int main(int argc, char **argv) {
    const char *id = NULL, *dir = getenv("MT76_FW_DIR"), *band = "5GHz", *pcap_path = NULL;
    int channel = 36, seconds = 6, count = 0, rate = MT_PROBE_OFDM6, power = 0;
    bool mib = false, cycle = false, ack = false;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "--help")) { usage(); return 0; }
        if (!strcmp(a, "--mib")) { mib = true; continue; }
        if (!strcmp(a, "--g5-cycle")) { cycle = true; continue; }
        if (!strcmp(a, "--acknowledge-experimental-transmit")) { ack = true; continue; }
        if (++i >= argc) { usage(); return 2; }
        const char *v = argv[i];
        if (!strcmp(a, "--usb-id")) id = v;
        else if (!strcmp(a, "--fw")) dir = v;
        else if (!strcmp(a, "--band")) band = v;
        else if (!strcmp(a, "--pcap")) pcap_path = v;
        else if (!strcmp(a, "--channel")) { if (number(v, 1, 233, &channel)) return 2; }
        else if (!strcmp(a, "--seconds")) { if (number(v, 1, 60, &seconds)) return 2; }
        else if (!strcmp(a, "--transmit")) { if (number(v, 1, 60, &count)) return 2; }
        else if (!strcmp(a, "--power-code")) { if (number(v, -32, 0, &power)) return 2; }
        else if (!strcmp(a, "--rate")) {
            if (!strcmp(v, "cck1")) rate = MT_PROBE_CCK1;
            else if (!strcmp(v, "ofdm6")) rate = MT_PROBE_OFDM6;
            else if (!strcmp(v, "ofdm54")) rate = MT_PROBE_OFDM54;
            else return 2;
        } else { usage(); return 2; }
    }
    uint16_t vid, pid;
    if (!id || mt7921_parse_usb_id(id, &vid, &pid)) { usage(); return 2; }
    int chip = mt7921_chip_for_usb_id(vid, pid);
    if (chip < 0 || (cycle && (chip != MT_CHIP_MT7921 || count))) return 2;
    if (!((!strcmp(band, "5GHz") && (channel == 36 || channel == 149)) ||
          (!strcmp(band, "2.4GHz") && channel == 6) ||
          (!strcmp(band, "6GHz") && channel == 37))) return 2;
    uint8_t test_frame[128], test_txd[64];
    int test_len = controlled_frame(test_frame, 0, rate);
    if (count && (!ack || seconds * 1000 < 500 + count * 50 ||
        mt_probe_txwi(chip, test_frame, (size_t)test_len, 0, rate, power, test_txd) < 0 ||
        (rate == MT_PROBE_CCK1 ? strcmp(band, "2.4GHz") : strcmp(band, "5GHz")))) {
        fprintf(stderr, "Refusing unsupported/unacknowledged TX or insufficient dwell\n"); return 2;
    }
    if (!count && power) { fprintf(stderr, "Power code requires transmit\n"); return 2; }
    if (!dir) dir = "firmware";
    const mt7921_chip_profile_t *prof = mt7921_chip_profile(chip);
    size_t patch_len = 0, ram_len = 0;
    uint8_t *patch = firmware(dir, prof->patch_file, prof->patch_sha256, &patch_len);
    uint8_t *ram = firmware(dir, prof->ram_file, prof->ram_sha256, &ram_len);
    if (!patch || !ram) { free(patch); free(ram); fprintf(stderr, "Missing/unpinned firmware\n"); return 1; }
    mt7921_dev_t dev;
    if (mt7921_dev_open(&dev, id)) { free(patch); free(ram); fprintf(stderr, "USB open failed\n"); return 1; }
    signal(SIGINT, stop_handler); signal(SIGTERM, stop_handler); signal(SIGPIPE, SIG_IGN);
    setvbuf(stdout, NULL, _IOLBF, 0);
    FILE *pcap = NULL;
    mt_g5_guard_t guard = {0};
    int result = 1;
    bool reload = false, reloaded = false;
    if (pcap_path && pcap_writer_open(pcap_path, &pcap)) goto cleanup;
    if (mt7921_bringup(&dev, patch, patch_len, ram, ram_len, quiet) ||
        mt7921_set_monitor_mode(&dev) || mt7921_set_sniffer(&dev, true, 0) ||
        mt7921_tune(&dev, band, (uint8_t)channel, (uint8_t)channel, 20) || stopping) goto cleanup;
    if (count) {
        reload = true;
        if (mt_probe_prepare(&dev, rate)) goto cleanup;
    }
    printf("{\"event\":\"ready\",\"chip\":\"%s\",\"usb_id\":\"%04x:%04x\","
           "\"band\":\"%s\",\"channel\":%d,\"width_mhz\":20,\"power_code\":%d,"
           "\"rate_code\":%d,\"patch_sha256\":\"%s\",\"ram_sha256\":\"%s\"}\n",
           prof->name, vid, pid, band, channel, power, rate, prof->patch_sha256, prof->ram_sha256);
    if (dwell(&dev, "baseline", seconds, mib, count, rate, power, pcap)) goto cleanup;
    if (cycle && !stopping) {
        if (mt_g5_begin_device(&dev, &guard) ||
            dwell(&dev, "enabled", seconds, mib, 0, rate, power, pcap) ||
            mt_g5_restore(&guard)) goto cleanup;
        if (!stopping && dwell(&dev, "restored", seconds, mib, 0, rate, power, pcap)) goto cleanup;
    }
    result = 0;
cleanup:;
    bool restored = mt_g5_restore(&guard) == 0;
    bool alive = mt7921_is_alive(&dev);
    if (!restored || !alive) result = 1;
    if (reload || dev.experimental_tx_dirty) {
        reloaded = !mt7921_bringup(&dev, patch, patch_len, ram, ram_len, quiet) &&
                   !mt7921_set_monitor_mode(&dev) && !mt7921_set_sniffer(&dev, true, 0) &&
                   !mt7921_tune(&dev, band, (uint8_t)channel, (uint8_t)channel, 20) &&
                   mt7921_is_alive(&dev);
        if (!reloaded) result = 1;
    }
    if (pcap) {
        if (fflush(pcap) || ferror(pcap)) result = 1;
        pcap_writer_close(pcap);
    }
    if (stopping && !result) result = 130;
    printf("{\"event\":\"cleanup\",\"g5_restored\":%s,\"alive_before_cleanup\":%s,"
           "\"firmware_reloaded\":%s,\"exit_code\":%d}\n",
           restored ? "true" : "false", alive ? "true" : "false", reloaded ? "true" : "false", result);
    mt7921_dev_close(&dev); free(patch); free(ram);
    return result;
}
