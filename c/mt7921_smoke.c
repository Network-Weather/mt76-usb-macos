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
#include <sys/utsname.h>
#include <sys/sysctl.h>
#include <time.h>
#include <CommonCrypto/CommonDigest.h>

#define PATCH_NAME "WIFI_MT7961_patch_mcu_1_2_hdr.bin"
#define RAM_NAME   "WIFI_RAM_CODE_MT7961_1.bin"
#define PATCH_SHA256 "a276c06c2b772adb50b86639d33c82824ff4c21d617feb78caea74c040b873f6"
#define RAM_SHA256   "b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9"

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

static uint8_t *read_file(const char *path, size_t *out_len, char *out_sha256) {
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

    if (out_sha256) {
        unsigned char md[CC_SHA256_DIGEST_LENGTH];
        CC_SHA256(buf, (CC_LONG)sz, md);
        for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) {
            sprintf(out_sha256 + (i * 2), "%02x", md[i]);
        }
        out_sha256[64] = '\0';
    }

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

static void get_iso_time(char *out, size_t max_len) {
    time_t now = time(NULL);
    struct tm tm_utc;
    gmtime_r(&now, &tm_utc);
    strftime(out, max_len, "%Y-%m-%dT%H:%M:%SZ", &tm_utc);
}

static void emit_json(const char *status,
                      const char *plan_name,
                      double dwell,
                      size_t total_channels,
                      bool req_24,
                      bool req_5,
                      bool req_6,
                      const band_stats_t *s24,
                      const band_stats_t *s5,
                      const band_stats_t *s6,
                      const char *patch_sha,
                      const char *ram_sha,
                      bool device_opened,
                      const char *err_type,
                      const char *err_msg,
                      double duration) {
    char iso_time[64];
    get_iso_time(iso_time, sizeof(iso_time));

    struct utsname uts;
    memset(&uts, 0, sizeof(uts));
    uname(&uts);

    char macos_ver[64] = "unknown";
    size_t sz = sizeof(macos_ver);
    sysctlbyname("kern.osproductversion", macos_ver, &sz, NULL, 0);

    printf("{\n");
    printf("  \"bands\": {\n");

    bool has_printed_band = false;
    if (req_24) {
        printf("    \"2.4GHz\": {\n");
        printf("      \"channels_attempted\": %u,\n", s24 ? s24->channels_attempted : 0);
        printf("      \"channels_with_frames\": %u,\n", s24 ? s24->channels_with_frames : 0);
        printf("      \"channels_with_transfers\": %u,\n", s24 ? s24->channels_with_transfers : 0);
        printf("      \"decoded_frames\": %u,\n", s24 ? s24->decoded_frames : 0);
        printf("      \"frame_types\": {\n");
        printf("        \"control\": %u,\n", s24 ? s24->frame_ctrl : 0);
        printf("        \"data\": %u,\n", s24 ? s24->frame_data : 0);
        printf("        \"management\": %u,\n", s24 ? s24->frame_mgmt : 0);
        printf("        \"other\": %u\n", s24 ? s24->frame_other : 0);
        printf("      },\n");
        printf("      \"undecoded_transfers\": %u,\n", s24 ? s24->undecoded_transfers : 0);
        printf("      \"usb_errors\": %u,\n", s24 ? s24->usb_errors : 0);
        printf("      \"usb_timeouts\": %u,\n", s24 ? s24->usb_timeouts : 0);
        printf("      \"usb_transfers\": %u\n", s24 ? s24->usb_transfers : 0);
        printf("    }");
        has_printed_band = true;
    }
    if (req_5) {
        if (has_printed_band) printf(",\n");
        printf("    \"5GHz\": {\n");
        printf("      \"channels_attempted\": %u,\n", s5 ? s5->channels_attempted : 0);
        printf("      \"channels_with_frames\": %u,\n", s5 ? s5->channels_with_frames : 0);
        printf("      \"channels_with_transfers\": %u,\n", s5 ? s5->channels_with_transfers : 0);
        printf("      \"decoded_frames\": %u,\n", s5 ? s5->decoded_frames : 0);
        printf("      \"frame_types\": {\n");
        printf("        \"control\": %u,\n", s5 ? s5->frame_ctrl : 0);
        printf("        \"data\": %u,\n", s5 ? s5->frame_data : 0);
        printf("        \"management\": %u,\n", s5 ? s5->frame_mgmt : 0);
        printf("        \"other\": %u\n", s5 ? s5->frame_other : 0);
        printf("      },\n");
        printf("      \"undecoded_transfers\": %u,\n", s5 ? s5->undecoded_transfers : 0);
        printf("      \"usb_errors\": %u,\n", s5 ? s5->usb_errors : 0);
        printf("      \"usb_timeouts\": %u,\n", s5 ? s5->usb_timeouts : 0);
        printf("      \"usb_transfers\": %u\n", s5 ? s5->usb_transfers : 0);
        printf("    }");
        has_printed_band = true;
    }
    if (req_6) {
        if (has_printed_band) printf(",\n");
        printf("    \"6GHz\": {\n");
        printf("      \"channels_attempted\": %u,\n", s6 ? s6->channels_attempted : 0);
        printf("      \"channels_with_frames\": %u,\n", s6 ? s6->channels_with_frames : 0);
        printf("      \"channels_with_transfers\": %u,\n", s6 ? s6->channels_with_transfers : 0);
        printf("      \"decoded_frames\": %u,\n", s6 ? s6->decoded_frames : 0);
        printf("      \"frame_types\": {\n");
        printf("        \"control\": %u,\n", s6 ? s6->frame_ctrl : 0);
        printf("        \"data\": %u,\n", s6 ? s6->frame_data : 0);
        printf("        \"management\": %u,\n", s6 ? s6->frame_mgmt : 0);
        printf("        \"other\": %u\n", s6 ? s6->frame_other : 0);
        printf("      },\n");
        printf("      \"undecoded_transfers\": %u,\n", s6 ? s6->undecoded_transfers : 0);
        printf("      \"usb_errors\": %u,\n", s6 ? s6->usb_errors : 0);
        printf("      \"usb_timeouts\": %u,\n", s6 ? s6->usb_timeouts : 0);
        printf("      \"usb_transfers\": %u\n", s6 ? s6->usb_transfers : 0);
        printf("    }");
    }
    printf("\n  },\n");

    if (device_opened) {
        printf("  \"device\": {\n");
        printf("    \"driver\": \"mt7921_c_iokit\",\n");
        printf("    \"usb_id\": \"0e8d:7961\",\n");
        printf("    \"usb_speed_code\": 4,\n");
        printf("    \"wifi_interface\": 3\n");
        printf("  },\n");
    } else {
        printf("  \"device\": null,\n");
    }

    printf("  \"duration_seconds\": %.3f,\n", duration);

    if (err_type && err_msg) {
        printf("  \"error\": {\n");
        printf("    \"message\": \"%s\",\n", err_msg);
        printf("    \"type\": \"%s\"\n", err_type);
        printf("  },\n");
    }

    if (patch_sha && ram_sha) {
        printf("  \"firmware\": {\n");
        printf("    \"patch_sha256\": \"%s\",\n", patch_sha);
        printf("    \"ram_sha256\": \"%s\"\n", ram_sha);
        printf("  },\n");
    } else {
        printf("  \"firmware\": {},\n");
    }

    printf("  \"generated_at_utc\": \"%s\",\n", iso_time);
    printf("  \"host\": {\n");
    printf("    \"machine\": \"%s\",\n", uts.machine);
    printf("    \"macos\": \"%s\"\n", macos_ver);
    printf("  },\n");

    printf("  \"plan\": {\n");
    printf("    \"channels\": %zu,\n", total_channels);
    printf("    \"dwell_seconds\": %.2f,\n", dwell);
    printf("    \"name\": \"%s\",\n", plan_name);
    printf("    \"requested_bands\": [\n");
    bool first_req = true;
    if (req_24) {
        printf("      \"2.4GHz\"");
        first_req = false;
    }
    if (req_5) {
        if (!first_req) printf(",\n");
        printf("      \"5GHz\"");
        first_req = false;
    }
    if (req_6) {
        if (!first_req) printf(",\n");
        printf("      \"6GHz\"");
    }
    printf("\n    ]\n");
    printf("  },\n");

    printf("  \"schema_version\": 1,\n");
    printf("  \"software\": {\n");
    printf("    \"c_driver\": \"mt7921_c_iokit\",\n");
    printf("    \"mt76_usb_macos\": \"0.1.0\"\n");
    printf("  },\n");
    printf("  \"status\": \"%s\",\n", status);

    uint32_t tot_decoded = (s24 ? s24->decoded_frames : 0) + (s5 ? s5->decoded_frames : 0) + (s6 ? s6->decoded_frames : 0);
    uint32_t tot_undecoded = (s24 ? s24->undecoded_transfers : 0) + (s5 ? s5->undecoded_transfers : 0) + (s6 ? s6->undecoded_transfers : 0);
    uint32_t tot_errors = (s24 ? s24->usb_errors : 0) + (s5 ? s5->usb_errors : 0) + (s6 ? s6->usb_errors : 0);
    uint32_t tot_timeouts = (s24 ? s24->usb_timeouts : 0) + (s5 ? s5->usb_timeouts : 0) + (s6 ? s6->usb_timeouts : 0);
    uint32_t tot_transfers = (s24 ? s24->usb_transfers : 0) + (s5 ? s5->usb_transfers : 0) + (s6 ? s6->usb_transfers : 0);

    printf("  \"totals\": {\n");
    printf("    \"decoded_frames\": %u,\n", tot_decoded);
    printf("    \"undecoded_transfers\": %u,\n", tot_undecoded);
    printf("    \"usb_errors\": %u,\n", tot_errors);
    printf("    \"usb_timeouts\": %u,\n", tot_timeouts);
    printf("    \"usb_transfers\": %u\n", tot_transfers);
    printf("  }\n");
    printf("}\n");
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

    /* Resolve firmware path */
    if (!fw_dir) {
        fw_dir = getenv("MT7921_FW_DIR");
        if (!fw_dir) {
            if (access("./firmware", F_OK) == 0) {
                fw_dir = "./firmware";
            } else if (access("../firmware", F_OK) == 0) {
                fw_dir = "../firmware";
            } else {
                fw_dir = "./firmware";
            }
        }
    }

    double t0 = get_time_sec();

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

    /* Check firmware files */
    char patch_path[1024], ram_path[1024];
    snprintf(patch_path, sizeof(patch_path), "%s/%s", fw_dir, PATCH_NAME);
    snprintf(ram_path, sizeof(ram_path), "%s/%s", fw_dir, RAM_NAME);

    size_t patch_len = 0, ram_len = 0;
    char patch_sha[65] = {0}, ram_sha[65] = {0};
    uint8_t *patch_blob = read_file(patch_path, &patch_len, patch_sha);
    uint8_t *ram_blob = read_file(ram_path, &ram_len, ram_sha);

    if (!patch_blob || !ram_blob) {
        free(all_chans);
        free(patch_blob);
        free(ram_blob);
        emit_json("fail", plan_name, dwell, plan_count, req_24, req_5, req_6,
                  NULL, NULL, NULL, NULL, NULL, false,
                  "FileNotFoundError", "required firmware is missing; run bash setup.sh",
                  get_time_sec() - t0);
        return 1;
    }

    if (strcmp(patch_sha, PATCH_SHA256) != 0 || strcmp(ram_sha, RAM_SHA256) != 0) {
        free(all_chans);
        free(patch_blob);
        free(ram_blob);
        emit_json("fail", plan_name, dwell, plan_count, req_24, req_5, req_6,
                  NULL, NULL, NULL, patch_sha, ram_sha, false,
                  "RuntimeError", "firmware checksum mismatch; run bash setup.sh",
                  get_time_sec() - t0);
        return 1;
    }

    /* Open PCAP if requested */
    FILE *pcap_f = NULL;
    if (pcap_file) {
        if (pcap_writer_open(pcap_file, &pcap_f) != 0) {
            fprintf(stderr, "warning: failed to open pcap file %s\n", pcap_file);
        }
    }

    band_stats_t stats_24 = {0};
    band_stats_t stats_5 = {0};
    band_stats_t stats_6 = {0};

    mt7921_dev_t dev;
    if (mt7921_dev_open(&dev) != 0) {
        free(all_chans);
        free(patch_blob);
        free(ram_blob);
        if (pcap_f) pcap_writer_close(pcap_f);
        emit_json("unsupported", plan_name, dwell, plan_count, req_24, req_5, req_6,
                  NULL, NULL, NULL, patch_sha, ram_sha, false,
                  "RuntimeError", "device 0e8d:7961 not found",
                  get_time_sec() - t0);
        return 3; /* unsupported */
    }

    if (verbose) {
        fprintf(stderr, "Device opened via IOKit. Starting bringup...\n");
    }

    void (*log_fn)(const char *fmt, ...) = verbose ? log_stderr : log_dummy;
    if (mt7921_bringup(&dev, patch_blob, patch_len, ram_blob, ram_len, log_fn) != 0) {
        mt7921_dev_close(&dev);
        free(all_chans);
        free(patch_blob);
        free(ram_blob);
        if (pcap_f) pcap_writer_close(pcap_f);
        emit_json("fail", plan_name, dwell, plan_count, req_24, req_5, req_6,
                  &stats_24, &stats_5, &stats_6, patch_sha, ram_sha, true,
                  "RuntimeError", "bringup or calibration failed",
                  get_time_sec() - t0);
        return 1;
    }

    if (mt7921_set_monitor_mode(&dev) != 0 || mt7921_set_sniffer(&dev, true, 0) != 0) {
        mt7921_dev_close(&dev);
        free(all_chans);
        free(patch_blob);
        free(ram_blob);
        if (pcap_f) pcap_writer_close(pcap_f);
        emit_json("fail", plan_name, dwell, plan_count, req_24, req_5, req_6,
                  &stats_24, &stats_5, &stats_6, patch_sha, ram_sha, true,
                  "RuntimeError", "failed to set monitor or sniffer mode",
                  get_time_sec() - t0);
        return 1;
    }

    uint8_t raw_buf[8192];

    for (size_t i = 0; i < plan_count; i++) {
        const chan_spec_t *spec = &plan_chans[i];
        band_stats_t *bs = (spec->band_idx == 0) ? &stats_24 :
                           (spec->band_idx == 1) ? &stats_5 : &stats_6;

        bs->channels_attempted++;
        if (mt7921_set_chan_info(&dev, spec->channel, spec->channel, CMD_CBW_20MHZ, spec->band_idx) != 0) {
            bs->usb_errors++;
            continue;
        }
        if (mt7921_config_sniffer(&dev, spec->channel, spec->channel, spec->band, SNIFFER_BW_20) != 0) {
            bs->usb_errors++;
            continue;
        }

        usleep(50000); /* 50ms settling */

        double deadline = get_time_sec() + dwell;
        uint32_t ch_transfers = 0;
        uint32_t ch_frames = 0;

        while (get_time_sec() < deadline) {
            uint32_t read_len = sizeof(raw_buf);
            int ret = mt7921_rx_read(&dev, raw_buf, &read_len, 250);
            if (ret == MT7921_ERR_TIMEOUT) {
                bs->usb_timeouts++;
                continue;
            } else if (ret != MT7921_OK) {
                bs->usb_errors++;
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

    emit_json(status, plan_name, dwell, plan_count, req_24, req_5, req_6,
              &stats_24, &stats_5, &stats_6, patch_sha, ram_sha, true,
              NULL, NULL, duration);

    return pass ? 0 : 2;
}
