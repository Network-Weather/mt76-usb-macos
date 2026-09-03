/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Redacted passive MT7921U hardware smoke validator in pure C. */

#include "mt7921_dev.h"
#include "mt7921_rxd.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>
#include <time.h>

#define PATCH_NAME "WIFI_MT7961_patch_mcu_1_2_hdr.bin"
#define RAM_NAME   "WIFI_RAM_CODE_MT7961_1.bin"

typedef struct {
    const char *band;
    uint8_t channel;
    uint8_t band_idx; /* 0 = 2.4GHz, 1 = 5GHz, 2 = 6GHz */
} chan_spec_t;

static const chan_spec_t PLAN_QUICK[] = {
    {"2.4GHz", 1, 0},
    {"5GHz", 36, 1},
    {"6GHz", 53, 2},
};

static const chan_spec_t PLAN_24[] = {
    {"2.4GHz", 1, 0},
    {"2.4GHz", 6, 0},
    {"2.4GHz", 11, 0},
};

static const chan_spec_t PLAN_5[] = {
    {"5GHz", 36, 1}, {"5GHz", 40, 1}, {"5GHz", 44, 1}, {"5GHz", 48, 1},
    {"5GHz", 52, 1}, {"5GHz", 56, 1}, {"5GHz", 60, 1}, {"5GHz", 64, 1},
    {"5GHz", 100, 1}, {"5GHz", 104, 1}, {"5GHz", 108, 1}, {"5GHz", 112, 1},
    {"5GHz", 116, 1}, {"5GHz", 120, 1}, {"5GHz", 124, 1}, {"5GHz", 128, 1},
    {"5GHz", 132, 1}, {"5GHz", 136, 1}, {"5GHz", 140, 1}, {"5GHz", 144, 1},
    {"5GHz", 149, 1}, {"5GHz", 153, 1}, {"5GHz", 157, 1}, {"5GHz", 161, 1},
    {"5GHz", 165, 1},
};

static const chan_spec_t PLAN_6[] = {
    {"6GHz", 5, 2}, {"6GHz", 21, 2}, {"6GHz", 37, 2}, {"6GHz", 53, 2},
    {"6GHz", 69, 2}, {"6GHz", 85, 2}, {"6GHz", 101, 2}, {"6GHz", 117, 2},
    {"6GHz", 133, 2}, {"6GHz", 149, 2}, {"6GHz", 165, 2}, {"6GHz", 181, 2},
    {"6GHz", 197, 2}, {"6GHz", 213, 2}, {"6GHz", 229, 2},
};

typedef struct {
    uint32_t channels_attempted;
    uint32_t channels_with_transfers;
    uint32_t channels_with_frames;
    uint32_t usb_transfers;
    uint32_t usb_timeouts;
    uint32_t usb_errors;
    uint32_t decoded_frames;
    uint32_t undecoded_transfers;
    uint32_t frame_mgmt;
    uint32_t frame_ctrl;
    uint32_t frame_data;
    uint32_t frame_other;
} band_stats_t;

static uint8_t *read_file(const char *path, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz <= 0) {
        fclose(f);
        return NULL;
    }
    uint8_t *buf = (uint8_t*)malloc(sz);
    if (!buf) {
        fclose(f);
        return NULL;
    }
    if (fread(buf, 1, sz, f) != (size_t)sz) {
        free(buf);
        fclose(f);
        return NULL;
    }
    fclose(f);
    *out_len = (size_t)sz;
    return buf;
}

static double get_time_sec(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (double)tv.tv_sec + (double)tv.tv_usec / 1000000.0;
}

static void log_dummy(const char *fmt, ...) {
    (void)fmt;
}

static void log_stderr(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
}

int main(int argc, char **argv) {
    const char *plan_name = "all";
    double dwell = 0.75;
    const char *fw_dir = NULL;
    const char *pcap_file = NULL;
    bool verbose = false;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--plan") == 0 && i + 1 < argc) {
            plan_name = argv[++i];
        } else if (strcmp(argv[i], "--dwell") == 0 && i + 1 < argc) {
            dwell = atof(argv[++i]);
        } else if (strcmp(argv[i], "--fw") == 0 && i + 1 < argc) {
            fw_dir = argv[++i];
        } else if (strcmp(argv[i], "--pcap") == 0 && i + 1 < argc) {
            pcap_file = argv[++i];
        } else if (strcmp(argv[i], "-v") == 0 || strcmp(argv[i], "--verbose") == 0) {
            verbose = true;
        } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            printf("Usage: %s [--plan quick|2.4|5|6|all] [--dwell <sec>] [--fw <fw_dir>] [--pcap <file>] [-v]\n", argv[0]);
            return 0;
        }
    }

    if (dwell < 0.05) dwell = 0.05;
    if (dwell > 10.0) dwell = 10.0;

    if (!fw_dir) {
        fw_dir = getenv("MT7921_FW_DIR");
        if (!fw_dir) fw_dir = "./firmware";
    }

    double t0 = get_time_sec();

    /* Load firmware files */
    char patch_path[1024], ram_path[1024];
    snprintf(patch_path, sizeof(patch_path), "%s/%s", fw_dir, PATCH_NAME);
    snprintf(ram_path, sizeof(ram_path), "%s/%s", fw_dir, RAM_NAME);

    size_t patch_len = 0, ram_len = 0;
    uint8_t *patch_blob = read_file(patch_path, &patch_len);
    uint8_t *ram_blob = read_file(ram_path, &ram_len);

    if (!patch_blob || !ram_blob) {
        fprintf(stderr, "Error: missing firmware files in %s\n", fw_dir);
        free(patch_blob);
        free(ram_blob);
        return 1;
    }

    /* Open PCAP if requested */
    FILE *pcap_f = NULL;
    if (pcap_file) {
        if (pcap_writer_open(pcap_file, &pcap_f) != 0) {
            fprintf(stderr, "Error: failed to open pcap file %s\n", pcap_file);
        }
    }

    /* Select channel plan */
    const chan_spec_t *plan_chans = NULL;
    size_t plan_count = 0;
    chan_spec_t *all_chans = NULL;

    bool req_24 = false, req_5 = false, req_6 = false;

    if (strcmp(plan_name, "quick") == 0) {
        plan_chans = PLAN_QUICK;
        plan_count = sizeof(PLAN_QUICK) / sizeof(PLAN_QUICK[0]);
        req_24 = req_5 = req_6 = true;
    } else if (strcmp(plan_name, "2.4") == 0) {
        plan_chans = PLAN_24;
        plan_count = sizeof(PLAN_24) / sizeof(PLAN_24[0]);
        req_24 = true;
    } else if (strcmp(plan_name, "5") == 0) {
        plan_chans = PLAN_5;
        plan_count = sizeof(PLAN_5) / sizeof(PLAN_5[0]);
        req_5 = true;
    } else if (strcmp(plan_name, "6") == 0) {
        plan_chans = PLAN_6;
        plan_count = sizeof(PLAN_6) / sizeof(PLAN_6[0]);
        req_6 = true;
    } else { /* "all" */
        plan_name = "all";
        size_t c24 = sizeof(PLAN_24) / sizeof(PLAN_24[0]);
        size_t c5 = sizeof(PLAN_5) / sizeof(PLAN_5[0]);
        size_t c6 = sizeof(PLAN_6) / sizeof(PLAN_6[0]);
        plan_count = c24 + c5 + c6;
        all_chans = (chan_spec_t*)malloc(plan_count * sizeof(chan_spec_t));
        memcpy(all_chans, PLAN_24, c24 * sizeof(chan_spec_t));
        memcpy(all_chans + c24, PLAN_5, c5 * sizeof(chan_spec_t));
        memcpy(all_chans + c24 + c5, PLAN_6, c6 * sizeof(chan_spec_t));
        plan_chans = all_chans;
        req_24 = req_5 = req_6 = true;
    }

    band_stats_t stats_24 = {0};
    band_stats_t stats_5 = {0};
    band_stats_t stats_6 = {0};

    mt7921_dev_t dev;
    if (mt7921_dev_open(&dev) != 0) {
        fprintf(stderr, "Error: MT7921 device not found via IOKit\n");
        free(all_chans);
        free(patch_blob);
        free(ram_blob);
        if (pcap_f) pcap_writer_close(pcap_f);
        return 3; /* unsupported */
    }

    if (verbose) {
        fprintf(stderr, "Device opened via IOKit. Starting bringup...\n");
    }

    void (*log_fn)(const char *fmt, ...) = verbose ? log_stderr : log_dummy;
    if (mt7921_bringup(&dev, patch_blob, patch_len, ram_blob, ram_len, log_fn) != 0) {
        fprintf(stderr, "Error: Bringup failed\n");
        mt7921_dev_close(&dev);
        free(all_chans);
        free(patch_blob);
        free(ram_blob);
        if (pcap_f) pcap_writer_close(pcap_f);
        return 1;
    }

    mt7921_set_monitor_mode(&dev);
    mt7921_set_sniffer(&dev, true, 0);

    uint8_t raw_buf[8192];

    for (size_t i = 0; i < plan_count; i++) {
        const chan_spec_t *spec = &plan_chans[i];
        band_stats_t *bs = (spec->band_idx == 0) ? &stats_24 :
                           (spec->band_idx == 1) ? &stats_5 : &stats_6;

        bs->channels_attempted++;
        mt7921_set_chan_info(&dev, spec->channel, spec->channel, CMD_CBW_20MHZ, spec->band_idx);
        mt7921_config_sniffer(&dev, spec->channel, spec->channel, spec->band, SNIFFER_BW_20);

        usleep(50000); /* 50ms settling */

        double deadline = get_time_sec() + dwell;
        uint32_t ch_transfers = 0;
        uint32_t ch_frames = 0;

        while (get_time_sec() < deadline) {
            uint32_t read_len = sizeof(raw_buf);
            int ret = mt7921_rx_read(&dev, raw_buf, &read_len, 250);
            if (ret != 0) {
                bs->usb_timeouts++;
                continue;
            }

            ch_transfers++;
            bs->usb_transfers++;

            mt7921_rxd_frame_t rf;
            if (mt7921_rxd_decode(raw_buf, read_len, &rf) != 0 || !rf.frame || rf.frame_len == 0) {
                bs->undecoded_transfers++;
                continue;
            }

            ch_frames++;
            bs->decoded_frames++;

            if (rf.frame_family == FRAME_FAMILY_MGMT) bs->frame_mgmt++;
            else if (rf.frame_family == FRAME_FAMILY_CTRL) bs->frame_ctrl++;
            else if (rf.frame_family == FRAME_FAMILY_DATA) bs->frame_data++;
            else bs->frame_other++;

            if (pcap_f) {
                pcap_writer_write_frame(pcap_f, &rf);
            }
        }

        if (ch_transfers > 0) bs->channels_with_transfers++;
        if (ch_frames > 0) bs->channels_with_frames++;
    }

    mt7921_dev_close(&dev);
    if (pcap_f) pcap_writer_close(pcap_f);
    free(all_chans);
    free(patch_blob);
    free(ram_blob);

    double duration = get_time_sec() - t0;

    /* Status determination */
    bool pass = true;
    if (req_24 && stats_24.decoded_frames == 0) pass = false;
    if (req_5 && stats_5.decoded_frames == 0) pass = false;
    if (req_6 && stats_6.decoded_frames == 0) pass = false;
    const char *status = pass ? "pass" : "inconclusive";

    /* Emit JSON summary */
    printf("{\n");
    printf("  \"bands\": {\n");
    if (req_24) {
        printf("    \"2.4GHz\": {\n");
        printf("      \"channels_attempted\": %u,\n", stats_24.channels_attempted);
        printf("      \"channels_with_frames\": %u,\n", stats_24.channels_with_frames);
        printf("      \"channels_with_transfers\": %u,\n", stats_24.channels_with_transfers);
        printf("      \"decoded_frames\": %u,\n", stats_24.decoded_frames);
        printf("      \"frame_types\": {\n");
        printf("        \"control\": %u,\n", stats_24.frame_ctrl);
        printf("        \"data\": %u,\n", stats_24.frame_data);
        printf("        \"management\": %u,\n", stats_24.frame_mgmt);
        printf("        \"other\": %u\n", stats_24.frame_other);
        printf("      },\n");
        printf("      \"undecoded_transfers\": %u,\n", stats_24.undecoded_transfers);
        printf("      \"usb_errors\": %u,\n", stats_24.usb_errors);
        printf("      \"usb_timeouts\": %u,\n", stats_24.usb_timeouts);
        printf("      \"usb_transfers\": %u\n", stats_24.usb_transfers);
        printf("    }%s\n", (req_5 || req_6) ? "," : "");
        first_band = false;
    }
    if (req_5) {
        printf("    \"5GHz\": {\n");
        printf("      \"channels_attempted\": %u,\n", stats_5.channels_attempted);
        printf("      \"channels_with_frames\": %u,\n", stats_5.channels_with_frames);
        printf("      \"channels_with_transfers\": %u,\n", stats_5.channels_with_transfers);
        printf("      \"decoded_frames\": %u,\n", stats_5.decoded_frames);
        printf("      \"frame_types\": {\n");
        printf("        \"control\": %u,\n", stats_5.frame_ctrl);
        printf("        \"data\": %u,\n", stats_5.frame_data);
        printf("        \"management\": %u,\n", stats_5.frame_mgmt);
        printf("        \"other\": %u\n", stats_5.frame_other);
        printf("      },\n");
        printf("      \"undecoded_transfers\": %u,\n", stats_5.undecoded_transfers);
        printf("      \"usb_errors\": %u,\n", stats_5.usb_errors);
        printf("      \"usb_timeouts\": %u,\n", stats_5.usb_timeouts);
        printf("      \"usb_transfers\": %u\n", stats_5.usb_transfers);
        printf("    }%s\n", req_6 ? "," : "");
    }
    if (req_6) {
        printf("    \"6GHz\": {\n");
        printf("      \"channels_attempted\": %u,\n", stats_6.channels_attempted);
        printf("      \"channels_with_frames\": %u,\n", stats_6.channels_with_frames);
        printf("      \"channels_with_transfers\": %u,\n", stats_6.channels_with_transfers);
        printf("      \"decoded_frames\": %u,\n", stats_6.decoded_frames);
        printf("      \"frame_types\": {\n");
        printf("        \"control\": %u,\n", stats_6.frame_ctrl);
        printf("        \"data\": %u,\n", stats_6.frame_data);
        printf("        \"management\": %u,\n", stats_6.frame_mgmt);
        printf("        \"other\": %u\n", stats_6.frame_other);
        printf("      },\n");
        printf("      \"undecoded_transfers\": %u,\n", stats_6.undecoded_transfers);
        printf("      \"usb_errors\": %u,\n", stats_6.usb_errors);
        printf("      \"usb_timeouts\": %u,\n", stats_6.usb_timeouts);
        printf("      \"usb_transfers\": %u\n", stats_6.usb_transfers);
        printf("    }\n");
    }
    printf("  },\n");

    uint32_t tot_decoded = stats_24.decoded_frames + stats_5.decoded_frames + stats_6.decoded_frames;
    uint32_t tot_undecoded = stats_24.undecoded_transfers + stats_5.undecoded_transfers + stats_6.undecoded_transfers;
    uint32_t tot_errors = stats_24.usb_errors + stats_5.usb_errors + stats_6.usb_errors;
    uint32_t tot_timeouts = stats_24.usb_timeouts + stats_5.usb_timeouts + stats_6.usb_timeouts;
    uint32_t tot_transfers = stats_24.usb_transfers + stats_5.usb_transfers + stats_6.usb_transfers;

    printf("  \"device\": {\n");
    printf("    \"driver\": \"mt7921_c_iokit\",\n");
    printf("    \"usb_id\": \"0e8d:7961\",\n");
    printf("    \"wifi_interface\": 3\n");
    printf("  },\n");
    printf("  \"duration_seconds\": %.3f,\n", duration);
    printf("  \"plan\": {\n");
    printf("    \"channels\": %zu,\n", plan_count);
    printf("    \"dwell_seconds\": %.2f,\n", dwell);
    printf("    \"name\": \"%s\"\n", plan_name);
    printf("  },\n");
    printf("  \"status\": \"%s\",\n", status);
    printf("  \"totals\": {\n");
    printf("    \"decoded_frames\": %u,\n", tot_decoded);
    printf("    \"undecoded_transfers\": %u,\n", tot_undecoded);
    printf("    \"usb_errors\": %u,\n", tot_errors);
    printf("    \"usb_timeouts\": %u,\n", tot_timeouts);
    printf("    \"usb_transfers\": %u\n", tot_transfers);
    printf("  }\n");
    printf("}\n");

    return pass ? 0 : 2;
}
