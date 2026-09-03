/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#ifndef MT7921_DEV_H
#define MT7921_DEV_H

#include "mt7921_mcu.h"

typedef struct {
    mt7921_usb_t usb;
    mt7921_mcu_t mcu;
} mt7921_dev_t;

int mt7921_dev_open(mt7921_dev_t *dev);
void mt7921_dev_close(mt7921_dev_t *dev);

/* Bringup orchestration */
int mt7921_bringup(mt7921_dev_t *dev, const uint8_t *patch_blob, size_t patch_len,
                   const uint8_t *ram_blob, size_t ram_len,
                   void (*log_fn)(const char *fmt, ...));

/* Monitor Mode & Sniffer */
int mt7921_set_rxfilter(mt7921_dev_t *dev, uint32_t fif, uint8_t bit_op, uint32_t bit_map);
int mt7921_set_monitor_mode(mt7921_dev_t *dev);
int mt7921_set_sniffer(mt7921_dev_t *dev, bool enable, uint8_t band_idx);
int mt7921_config_sniffer(mt7921_dev_t *dev, uint8_t control_ch, uint8_t center_ch,
                          const char *band_name, uint8_t bw);
int mt7921_set_chan_info(mt7921_dev_t *dev, uint8_t control_ch, uint8_t center_ch,
                         uint8_t bw, uint8_t band);

int mt7921_rx_read(mt7921_dev_t *dev, void *buf, uint32_t *len, uint32_t timeout_ms);

#endif /* MT7921_DEV_H */
