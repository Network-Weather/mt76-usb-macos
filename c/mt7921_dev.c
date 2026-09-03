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

int mt7921_build_probe_request(uint8_t *buf, size_t max_len, const uint8_t src_mac[6], const char *ssid, uint16_t seq) {
    if (!buf || !src_mac) return -1;
    size_t ssid_len = ssid ? strlen(ssid) : 0;
    if (ssid_len > 32) return -1;
    size_t total_len = 24 + 2 + ssid_len + 6;
    if (max_len < total_len) return -1;

    memset(buf, 0, total_len);
    /* Frame Control: 0x0040 (type 0 mgmt, subtype 4 probe req) */
    uint16_t fc = CFSwapInt16HostToLittle(0x0040);
    memcpy(buf + 0, &fc, 2);
    /* Duration: 0 */
    memset(buf + 2, 0, 2);
    /* Addr1: Broadcast (FF:FF:FF:FF:FF:FF) */
    memset(buf + 4, 0xFF, 6);
    /* Addr2: Source MAC */
    memcpy(buf + 10, src_mac, 6);
    /* Addr3: Broadcast (FF:FF:FF:FF:FF:FF) */
    memset(buf + 16, 0xFF, 6);
    /* Sequence Control: (seq & 0xFFF) << 4 */
    uint16_t sc = CFSwapInt16HostToLittle((seq & 0x0FFF) << 4);
    memcpy(buf + 22, &sc, 2);

    /* Tag 0: SSID parameter set */
    buf[24] = 0;
    buf[25] = (uint8_t)ssid_len;
    if (ssid_len > 0) {
        memcpy(buf + 26, ssid, ssid_len);
    }

    /* Tag 1: Supported Rates (1M, 2M, 5.5M, 11M basic rates) */
    size_t rate_off = 26 + ssid_len;
    buf[rate_off + 0] = 1;
    buf[rate_off + 1] = 4;
    buf[rate_off + 2] = 0x82;
    buf[rate_off + 3] = 0x84;
    buf[rate_off + 4] = 0x8B;
    buf[rate_off + 5] = 0x96;

    return (int)total_len;
}

int mt7921_build_txwi(uint8_t *txwi_out, const uint8_t *frame, size_t frame_len, uint16_t seq, uint8_t pid) {
    if (!txwi_out || !frame || frame_len < 24) return -1;

    uint16_t fc = CFSwapInt16LittleToHost(*(const uint16_t*)frame);
    uint32_t fc_type = (fc >> 2) & 0x3;
    uint32_t fc_stype = (fc >> 4) & 0xF;
    uint32_t hdrlen = 24;
    bool multicast = (frame[4] & 0x01) != 0;

    uint32_t txwi[16] = {0};

    txwi[0] = (((uint32_t)frame_len + MT_SDIO_TXD_SIZE) & MT_TXD0_TX_BYTES_M)
            | (((uint32_t)MT_TX_TYPE_SF & 0x3) << 23)
            | (((uint32_t)MT_LMAC_ALTX0 & 0x7F) << 25);

    txwi[1] = MT_TXD1_LONG_FORMAT
            | (GLOBAL_WCID & 0x3FF)
            | (0 << MT_TXD1_OWN_MAC_SHIFT)
            | (MT_HDR_FORMAT_802_11 << MT_TXD1_HDR_FORMAT_SHIFT)
            | ((hdrlen / 2) << MT_TXD1_HDR_INFO_SHIFT);

    txwi[2] = (fc_type << MT_TXD2_FRAME_TYPE_SHIFT)
            | (fc_stype << MT_TXD2_SUB_TYPE_SHIFT)
            | (multicast ? MT_TXD2_MULTICAST : 0)
            | MT_TXD2_FIX_RATE
            | MT_TXD2_HTC_VLD;

    txwi[3] = (15 << MT_TXD3_REM_TX_COUNT_SHIFT)
            | MT_TXD3_NO_ACK
            | MT_TXD3_BA_DISABLE
            | MT_TXD3_SN_VALID
            | (((uint32_t)seq & 0xFFF) << MT_TXD3_SEQ_SHIFT);

    txwi[5] = pid & 0xFF;
    if (pid >= MT_PACKET_ID_FIRST) {
        txwi[5] |= MT_TXD5_TX_STATUS_HOST;
    }

    txwi[6] = MT_TXD6_FIXED_BW | (TX_RATE_1M_CCK << MT_TXD6_TX_RATE_SHIFT);

    txwi[8] = (fc_type << MT_TXD8_L_TYPE_SHIFT) | (fc_stype << MT_TXD8_L_SUB_TYPE_SHIFT);

    for (int i = 0; i < 16; i++) {
        uint32_t le = CFSwapInt32HostToLittle(txwi[i]);
        memcpy(txwi_out + (i * 4), &le, 4);
    }
    return MT_SDIO_TXD_SIZE;
}

int mt7921_inject(mt7921_dev_t *dev, const uint8_t *frame, size_t frame_len, uint8_t ep, uint16_t seq, uint8_t pid) {
    if (!dev || !frame || frame_len < 24) return -1;
    if (ep == 0) ep = EP_OUT_AC_BE;

    uint8_t txwi[MT_SDIO_TXD_SIZE];
    if (mt7921_build_txwi(txwi, frame, frame_len, seq, pid) != MT_SDIO_TXD_SIZE) {
        return -1;
    }

    size_t body_len = MT_SDIO_TXD_SIZE + frame_len;
    size_t out_len = 4 + body_len;
    size_t pad = (((out_len + 3) & ~3) - out_len) + 4;
    size_t total_alloc = out_len + pad;

    uint8_t *packet = (uint8_t*)malloc(total_alloc);
    if (!packet) return -1;

    uint32_t sdio_hdr = CFSwapInt32HostToLittle((uint32_t)body_len & 0xFFFF);
    memcpy(packet, &sdio_hdr, 4);
    memcpy(packet + 4, txwi, MT_SDIO_TXD_SIZE);
    memcpy(packet + 4 + MT_SDIO_TXD_SIZE, frame, frame_len);
    memset(packet + out_len, 0, pad);

    int ret = mt7921_bulk_out(&dev->usb, ep, packet, (uint32_t)total_alloc, 1000);
    free(packet);
    return ret;
}

bool mt7921_is_alive(mt7921_dev_t *dev) {
    if (!dev) return false;
    uint32_t chipid = mt7921_rr(&dev->usb, MT_HW_CHIPID);
    return (chipid & 0xFFFF) == 0x7961;
}

int mt7921_dev_get_temperature(mt7921_dev_t *dev, int32_t *temp_c) {
    if (!dev) return -1;
    return mt7921_get_temperature(&dev->mcu, temp_c);
}

int mt7921_dev_read_efuse(mt7921_dev_t *dev, uint32_t offset, uint8_t data[16], uint32_t *valid) {
    if (!dev) return -1;
    return mt7921_read_efuse(&dev->mcu, offset, data, valid);
}
