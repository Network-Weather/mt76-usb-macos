/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#include "mt7921_dev.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int mt7921_dev_open(mt7921_dev_t *dev) {
    if (!dev) return -1;
    memset(dev, 0, sizeof(*dev));
    if (mt7921_usb_open(&dev->usb) != 0) {
        return -1;
    }
    mt7921_mcu_init(&dev->mcu, &dev->usb);
    return 0;
}

void mt7921_dev_close(mt7921_dev_t *dev) {
    if (!dev) return;
    mt7921_usb_close(&dev->usb);
}

static void dma_prefetch(mt7921_dev_t *dev) {
    static const struct { uint32_t idx; uint32_t cnt; uint32_t base; } rings[] = {
        {0, 4, 0x080},
        {1, 4, 0x0C0},
        {2, 4, 0x100},
        {3, 4, 0x140},
        {4, 4, 0x180},
        {16, 4, 0x280},
        {17, 4, 0x2C0},
    };
    for (size_t i = 0; i < sizeof(rings)/sizeof(rings[0]); i++) {
        uint32_t val = (rings[i].cnt & 0xFF) | ((rings[i].base << 16) & MT_WPDMA0_BASE_PTR_MASK);
        mt7921_rmw(&dev->usb,
                   MT_UWFDMA0_TX_RING_EXT_CTRL(rings[i].idx),
                   MT_WPDMA0_MAX_CNT_MASK | MT_WPDMA0_BASE_PTR_MASK,
                   val);
    }
}

static void wfdma_init(mt7921_dev_t *dev) {
    dma_prefetch(dev);
    mt7921_clear_bits(&dev->usb, MT_UWFDMA0_GLO_CFG, MT_WFDMA0_GLO_CFG_OMIT_RX_INFO);
    mt7921_set_bits(&dev->usb,
                    MT_UWFDMA0_GLO_CFG,
                    MT_WFDMA0_GLO_CFG_OMIT_TX_INFO |
                    MT_WFDMA0_GLO_CFG_OMIT_RX_INFO_PFET2 |
                    MT_WFDMA0_GLO_CFG_FW_DWLD_BYPASS_DMASHDL |
                    MT_WFDMA0_GLO_CFG_TX_DMA_EN |
                    MT_WFDMA0_GLO_CFG_RX_DMA_EN);

    mt7921_rmw(&dev->usb, MT_DMASHDL_REFILL, MT_DMASHDL_REFILL_MASK, 0xFFE00000);
    mt7921_clear_bits(&dev->usb, MT_DMASHDL_PAGE, MT_DMASHDL_GROUP_SEQ_ORDER);
    mt7921_rmw(&dev->usb,
               MT_DMASHDL_PKT_MAX_SIZE,
               MT_DMASHDL_PKT_MAX_SIZE_PLE | MT_DMASHDL_PKT_MAX_SIZE_PSE,
               1);

    for (int i = 0; i < 5; i++) {
        mt7921_wr(&dev->usb, MT_DMASHDL_GROUP_QUOTA(i), 0x3 | (0xFFF << 16));
    }
    for (int i = 5; i < 16; i++) {
        mt7921_wr(&dev->usb, MT_DMASHDL_GROUP_QUOTA(i), 0);
    }

    mt7921_wr(&dev->usb, MT_DMASHDL_Q_MAP(0), 0x32013201);
    mt7921_wr(&dev->usb, MT_DMASHDL_Q_MAP(1), 0x32013201);
    mt7921_wr(&dev->usb, MT_DMASHDL_Q_MAP(2), 0x55555444);
    mt7921_wr(&dev->usb, MT_DMASHDL_Q_MAP(3), 0x55555444);
    mt7921_wr(&dev->usb, MT_DMASHDL_SCHED_SET(0), 0x76540132);
    mt7921_wr(&dev->usb, MT_DMASHDL_SCHED_SET(1), 0xFEDCBA98);
    mt7921_set_bits(&dev->usb, MT_WFDMA_DUMMY_CR, MT_WFDMA_NEED_REINIT);
}

static int dma_rx_evt_ep4(mt7921_dev_t *dev) {
    if (!mt7921_poll(&dev->usb, MT_UWFDMA0_GLO_CFG, MT_WFDMA0_GLO_CFG_RX_DMA_BUSY, 0, 1000)) {
        return -1;
    }
    mt7921_clear_bits(&dev->usb, MT_UWFDMA0_GLO_CFG, MT_WFDMA0_GLO_CFG_RX_DMA_EN);
    mt7921_set_bits(&dev->usb, MT_WFDMA_HOST_CONFIG, MT_WFDMA_HOST_CONFIG_USB_RXEVT_EP4_EN);
    mt7921_set_bits(&dev->usb, MT_UWFDMA0_GLO_CFG, MT_WFDMA0_GLO_CFG_RX_DMA_EN);
    dev->mcu.evt_ep4 = true;
    return 0;
}

static void epctl_rst_opt(mt7921_dev_t *dev, bool reset) {
    uint32_t mask = 0x3F0 | 0x700000;
    uint32_t val = mt7921_uhw_rr(&dev->usb, MT_SSUSB_EPCTL_CSR_EP_RST_OPT);
    val = reset ? (val | mask) : (val & ~mask);
    mt7921_uhw_wr(&dev->usb, MT_SSUSB_EPCTL_CSR_EP_RST_OPT, val);
}

static int dma_init(mt7921_dev_t *dev, bool resume) {
    wfdma_init(dev);
    mt7921_clear_bits(&dev->usb, MT_UDMA_WLCFG_0, MT_WL_RX_FLUSH);
    mt7921_set_bits(&dev->usb,
                    MT_UDMA_WLCFG_0,
                    MT_WL_RX_EN | MT_WL_TX_EN | MT_WL_RX_MPSZ_PAD0 | MT_TICK_1US_EN);
    mt7921_rmw(&dev->usb,
               MT_UDMA_WLCFG_1,
               MT_WL_TX_TMOUT_LMT,
               (MT792X_USB_TX_TIMEOUT_LIMIT << 8) & MT_WL_TX_TMOUT_LMT);
    mt7921_set_bits(&dev->usb, MT_UDMA_WLCFG_0, MT_WL_TX_TMOUT_FUNC_EN);
    mt7921_clear_bits(&dev->usb, MT_UDMA_WLCFG_0, MT_WL_RX_AGG_TO | MT_WL_RX_AGG_LMT);
    mt7921_clear_bits(&dev->usb, MT_UDMA_WLCFG_1, MT_WL_RX_AGG_PKT_LMT);

    if (resume) return 0;

    if (dma_rx_evt_ep4(dev) != 0) return -1;
    epctl_rst_opt(dev, false);
    return 0;
}

static void wait_udma_idle(mt7921_dev_t *dev) {
    mt7921_set_bits(&dev->usb, MT_UDMA_WLCFG_0, MT_WL_RX_FLUSH);
    mt7921_poll(&dev->usb, MT_UDMA_WLCFG_0, MT_WL_RX_BUSY | MT_WL_TX_BUSY, 0, MT792X_USB_UDMA_IDLE_TIMEOUT);
}

static int wfsys_reset(mt7921_dev_t *dev) {
    wait_udma_idle(dev);
    epctl_rst_opt(dev, false);

    uint32_t val = mt7921_uhw_rr(&dev->usb, MT_CBTOP_RGU_WF_SUBSYS_RST);
    mt7921_uhw_wr(&dev->usb, MT_CBTOP_RGU_WF_SUBSYS_RST, val | MT_CBTOP_RGU_WF_SUBSYS_RST_WF_WHOLE_PATH);
    usleep(1000);
    val = mt7921_uhw_rr(&dev->usb, MT_CBTOP_RGU_WF_SUBSYS_RST);
    mt7921_uhw_wr(&dev->usb, MT_CBTOP_RGU_WF_SUBSYS_RST, val & ~MT_CBTOP_RGU_WF_SUBSYS_RST_WF_WHOLE_PATH);

    mt7921_uhw_wr(&dev->usb, MT_UDMA_CONN_INFRA_STATUS_SEL, 0);

    for (int i = 0; i < MT792x_WFSYS_INIT_RETRY_COUNT; i++) {
        val = mt7921_uhw_rr(&dev->usb, MT_UDMA_CONN_INFRA_STATUS);
        if (val & MT_UDMA_CONN_WFSYS_INIT_DONE) return 0;
        usleep(100000);
    }
    return -1;
}

int mt7921_bringup(mt7921_dev_t *dev, const uint8_t *patch_blob, size_t patch_len,
                   const uint8_t *ram_blob, size_t ram_len,
                   void (*log_fn)(const char *fmt, ...)) {
    if (log_fn) log_fn("resetting USB device\n");
    mt7921_usb_reset(&dev->usb);
    usleep(500000);

    uint32_t misc = mt7921_rr(&dev->usb, MT_CONN_ON_MISC);
    if (log_fn) log_fn("MT_CONN_ON_MISC = 0x%08x\n", misc);
    if (misc & MT_TOP_MISC2_FW_N9_RDY) {
        if (log_fn) log_fn("  retained FW_STATE bits; running WFSYS reset\n");
        wfsys_reset(dev);
        if (log_fn) log_fn("  MT_CONN_ON_MISC = 0x%08x\n", mt7921_rr(&dev->usb, MT_CONN_ON_MISC));
    }

    if (log_fn) log_fn("powering on MCU\n");
    if (!mt7921_power_on(&dev->usb)) {
        if (log_fn) log_fn("  timeout waiting for FW_PWR_ON\n");
        return -1;
    }
    if (log_fn) log_fn("  MT_CONN_ON_MISC = 0x%08x\n", mt7921_rr(&dev->usb, MT_CONN_ON_MISC));

    if (log_fn) log_fn("initialising DMA\n");
    if (dma_init(dev, false) != 0) {
        if (log_fn) log_fn("  DMA init failed\n");
        return -1;
    }

    mt7921_wr(&dev->usb, MT_SWDEF_MODE, MT_SWDEF_NORMAL_MODE);

    if (log_fn) log_fn("enabling firmware download path\n");
    mt7921_set_bits(&dev->usb, MT_UDMA_TX_QSEL, MT_FW_DL_EN);

    if (log_fn) log_fn("restarting MCU before download\n");
    mt7921_nic_power_ctrl(&dev->mcu, 1);
    if (!mt7921_poll(&dev->usb, MT_CONN_ON_MISC, MT_TOP_MISC_FW_STATE, MT_TOP_MISC2_FW_PWR_ON, 1000)) {
        if (log_fn) log_fn("  warning: MCU not reporting ready for download\n");
    }

    if (log_fn) log_fn("loading ROM patch\n");
    if (mt7921_load_patch(&dev->mcu, patch_blob, patch_len, log_fn) != 0) {
        return -1;
    }

    if (log_fn) log_fn("loading RAM firmware\n");
    if (mt7921_load_ram(&dev->mcu, ram_blob, ram_len, log_fn) != 0) {
        return -1;
    }

    if (log_fn) log_fn("waiting for N9 ready\n");
    if (!mt7921_poll(&dev->usb, MT_CONN_ON_MISC, MT_TOP_MISC2_FW_N9_RDY, MT_TOP_MISC2_FW_N9_RDY, 1500)) {
        if (log_fn) log_fn("  timeout waiting for N9_RDY\n");
        return -1;
    }

    mt7921_clear_bits(&dev->usb, MT_UDMA_TX_QSEL, MT_FW_DL_EN);
    if (log_fn) log_fn("firmware is running\n");

    if (mt7921_get_nic_capability(&dev->mcu) != 0) {
        if (log_fn) log_fn("  failed to get nic capability\n");
        return -1;
    }
    if (mt7921_set_eeprom(&dev->mcu) != 0) {
        if (log_fn) log_fn("  failed to push efuse calibration\n");
        return -1;
    }
    if (log_fn) log_fn("efuse pushed\n");

    return 0;
}

int mt7921_set_rxfilter(mt7921_dev_t *dev, uint32_t fif, uint8_t bit_op, uint32_t bit_map) {
    uint8_t data[68] = {0};
    data[4] = fif ? 1 : 2; /* mode */

    uint32_t le_fif = CFSwapInt32HostToLittle(fif);
    uint32_t le_bitmap = CFSwapInt32HostToLittle(bit_map);
    memcpy(data + 8, &le_fif, 4);
    memcpy(data + 12, &le_bitmap, 4);
    data[16] = bit_op;

    return mt7921_mcu_cmd_word(&dev->mcu, MCU_CE_CMD(MCU_CE_CMD_SET_RX_FILTER), data, sizeof(data), false, NULL, NULL, 3000);
}

int mt7921_set_monitor_mode(mt7921_dev_t *dev) {
    int ret = mt7921_set_rxfilter(dev, MONITOR_FILTER, 0, 0);
    if (ret != 0) return ret;
    return mt7921_set_rxfilter(dev, 0, MT7921_FIF_BIT_CLR, MONITOR_DROP_CLEAR);
}

int mt7921_set_sniffer(mt7921_dev_t *dev, bool enable, uint8_t band_idx) {
    uint8_t payload[12] = {0};
    payload[0] = band_idx;
    uint16_t tag = 0;
    uint16_t len = 8;
    uint16_t le_tag = CFSwapInt16HostToLittle(tag);
    uint16_t le_len = CFSwapInt16HostToLittle(len);
    memcpy(payload + 4, &le_tag, 2);
    memcpy(payload + 6, &le_len, 2);
    payload[8] = enable ? 1 : 0;
    return mt7921_mcu_uni(&dev->mcu, MCU_UNI_CMD_SNIFFER, payload, sizeof(payload), true, NULL, NULL, 3000);
}

int mt7921_config_sniffer(mt7921_dev_t *dev, uint8_t control_ch, uint8_t center_ch,
                          const char *band_name, uint8_t bw) {
    uint8_t sco = 0;
    if (control_ch < center_ch) sco = 1;
    else if (control_ch > center_ch) sco = 3;

    uint8_t sniffer_band = SNIFFER_BAND_24;
    if (strcmp(band_name, "5GHz") == 0) sniffer_band = SNIFFER_BAND_5;
    else if (strcmp(band_name, "6GHz") == 0) sniffer_band = SNIFFER_BAND_6;

    uint8_t payload[20] = {0};
    payload[0] = 0; /* band_idx */

    uint16_t tag = CFSwapInt16HostToLittle(1);
    uint16_t len = CFSwapInt16HostToLittle(16);
    uint16_t aid = 0;

    memcpy(payload + 4, &tag, 2);
    memcpy(payload + 6, &len, 2);
    memcpy(payload + 8, &aid, 2);

    payload[10] = sniffer_band;
    payload[11] = bw;
    payload[12] = control_ch;
    payload[13] = sco;
    payload[14] = center_ch;
    payload[15] = 0; /* center_ch2 */
    payload[16] = 1; /* drop_err */

    return mt7921_mcu_uni(&dev->mcu, MCU_UNI_CMD_SNIFFER, payload, sizeof(payload), true, NULL, NULL, 3000);
}

int mt7921_set_chan_info(mt7921_dev_t *dev, uint8_t control_ch, uint8_t center_ch,
                         uint8_t bw, uint8_t band) {
    uint8_t req[76] = {0};
    req[0] = control_ch;
    req[1] = center_ch;
    req[2] = bw;
    req[3] = 2; /* tx_streams_num: antenna_mask 0x3 bit_count = 2 */
    req[4] = 2; /* rx_streams = 2 */
    req[5] = CH_SWITCH_NORMAL;
    req[6] = 0; /* band_idx */
    req[7] = 0; /* center_ch2 */

    req[10] = band; /* channel_band (0=2.4GHz, 1=5GHz, 2=6GHz) */

    return mt7921_mcu_cmd_word(&dev->mcu, MCU_EXT_CMD(MCU_EXT_CMD_CHANNEL_SWITCH), req, sizeof(req), true, NULL, NULL, 3000);
}

int mt7921_rx_read(mt7921_dev_t *dev, void *buf, uint32_t *len, uint32_t timeout_ms) {
    return mt7921_bulk_in(&dev->usb, EP_IN_PKT_RX, buf, len, timeout_ms);
}
