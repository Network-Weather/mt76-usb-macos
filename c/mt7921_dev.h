/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#ifndef MT7921_DEV_H
#define MT7921_DEV_H

#include "mt7921_mcu.h"

typedef struct {
    mt7921_usb_t usb;
    mt7921_mcu_t mcu;
    /* Successful tune state for the new bounded experimental transmitter only. */
    bool tuned;
    uint8_t tuned_band, tuned_control, tuned_center;
    uint16_t tuned_width;
    unsigned experimental_rates, experimental_tx_count;
    bool experimental_tx_dirty; /* firmware reload required after table writes */
    uint64_t experimental_last_tx_us;
} mt7921_dev_t;

/* usb_id: "vvvv:pppp" or NULL (see mt7921_usb_open). */
int mt7921_dev_open(mt7921_dev_t *dev, const char *usb_id);
static inline const mt7921_chip_profile_t *mt7921_dev_profile(const mt7921_dev_t *dev) {
    return dev->mcu.prof;
}
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
/* MT7921 only (MCU_EXT_CMD CHANNEL_SWITCH); returns MT7921_ERR_UNSUPPORTED on the MT7925. */
int mt7921_set_chan_info(mt7921_dev_t *dev, uint8_t control_ch, uint8_t center_ch,
                         uint8_t bw, uint8_t band);
/* Put the sniffer on one channel on either chip: MT7921 sends CHANNEL_SWITCH then the
 * sniffer CONFIG TLV; MT7925 sends the TLV alone. width_mhz is 20, 40, 80, or 160;
 * center_ch 0 means the control channel. */
int mt7921_tune(mt7921_dev_t *dev, const char *band_name, uint8_t control_ch, uint8_t center_ch,
                uint16_t width_mhz);

int mt7921_rx_read(mt7921_dev_t *dev, void *buf, uint32_t *len, uint32_t timeout_ms);

/* Packet Injection & Transmission */
int mt7921_build_probe_request(uint8_t *buf, size_t max_len, const uint8_t src_mac[6], const char *ssid, uint16_t seq);
int mt7921_build_txwi(uint8_t *txwi_out, const uint8_t *frame, size_t frame_len, uint16_t seq, uint8_t pid);
int mt7921_inject(mt7921_dev_t *dev, const uint8_t *frame, size_t frame_len, uint8_t ep, uint16_t seq, uint8_t pid);
bool mt7921_is_alive(mt7921_dev_t *dev);

/* Housekeeping */
int mt7921_dev_get_temperature(mt7921_dev_t *dev, int32_t *temp_c);
int mt7921_dev_read_efuse(mt7921_dev_t *dev, uint32_t offset, uint8_t data[16], uint32_t *valid);

#endif /* MT7921_DEV_H */
