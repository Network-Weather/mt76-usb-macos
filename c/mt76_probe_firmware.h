/* SPDX-License-Identifier: BSD-3-Clause-Clear */
#ifndef MT76_PROBE_FIRMWARE_H
#define MT76_PROBE_FIRMWARE_H
#include <CommonCrypto/CommonDigest.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Probe-only local-file loader, not a firmware distributor or network fetcher. */
static inline uint8_t *mt_probe_firmware(const char *dir, const char *name, const char *pin, size_t *len) {
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
#endif
