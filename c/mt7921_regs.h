/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#ifndef MT7921_REGS_H
#define MT7921_REGS_H

#include <stdint.h>

#define MT_VID                      0x0E8D
#define MT_PID                      0x7961
#define WIFI_INTERFACE              3

/* USB request types */
#define USB_TYPE_VENDOR             0x40
#define USB_DIR_IN                  0x80
#define USB_DIR_OUT                 0x00

#define MT_USB_TYPE_VENDOR          (USB_TYPE_VENDOR | 0x1F) /* 0x5F */
#define MT_USB_TYPE_UHW_VENDOR      (USB_TYPE_VENDOR | 0x1E) /* 0x5E */

/* mt_vendor_req */
#define MT_VEND_DEV_MODE            0x01
#define MT_VEND_WRITE               0x02
#define MT_VEND_POWER_ON            0x04
#define MT_VEND_MULTI_WRITE         0x06
#define MT_VEND_MULTI_READ          0x07
#define MT_VEND_READ_EXT            0x63
#define MT_VEND_WRITE_EXT           0x66
#define MT_VEND_FEATURE_SET         0x91

/* Endpoints */
#define EP_OUT_INBAND_CMD           0x08
#define EP_OUT_AC_BE                0x04
#define EP_IN_PKT_RX                0x84
#define EP_IN_CMD_RESP              0x85

/* Hardware registers */
#define MT_HW_CHIPID                0x70010200
#define MT_HW_REV                   0x70010204
#define MT_CONN_ON_MISC             0x7C0600F0
#define MT_TOP_MISC_FW_STATE        0x7
#define MT_TOP_MISC2_FW_PWR_ON      (1U << 0)
#define MT_TOP_MISC2_FW_N9_ON       (1U << 1)
#define MT_TOP_MISC2_FW_N9_RDY      0x3
#define MT_CONN_ON_LPCTL            0x7C060010
#define PCIE_LPCR_HOST_SET_OWN      (1U << 0)
#define PCIE_LPCR_HOST_CLR_OWN      (1U << 1)
#define PCIE_LPCR_HOST_OWN_SYNC     (1U << 2)
#define MT_CONN_STATUS              0x7C053C10
#define MT_WIFI_PATCH_DL_STATE      (1U << 0)

#define MT_UMAC(ofs)                (0x74000000U + (ofs))
#define MT_UDMA_TX_QSEL             MT_UMAC(0x008)
#define MT_FW_DL_EN                 (1U << 3)
#define MT_UDMA_WLCFG_0             MT_UMAC(0x018)
#define MT_UDMA_WLCFG_1             MT_UMAC(0x00C)
#define MT_WL_RX_EN                 (1U << 22)
#define MT_WL_TX_EN                 (1U << 23)
#define MT_WL_RX_FLUSH              (1U << 19)
#define MT_WL_RX_AGG_PKT_LMT        0xFFU
#define MT_WL_TX_TMOUT_LMT          0x0FFFFF00U
#define MT_WL_RX_AGG_TO             0xFFU
#define MT_WL_RX_AGG_LMT            0xFF00U
#define MT_WL_TX_TMOUT_FUNC_EN      (1U << 16)
#define MT_WL_RX_MPSZ_PAD0          (1U << 18)
#define MT_TICK_1US_EN              (1U << 20)
#define MT792X_USB_TX_TIMEOUT_LIMIT 50000

#define MT_UDMA_CONN_INFRA_STATUS   MT_UMAC(0xA20)
#define MT_UDMA_CONN_WFSYS_INIT_DONE (1U << 22)
#define MT_UDMA_CONN_INFRA_STATUS_SEL MT_UMAC(0xA24)
#define MT_WL_RX_BUSY               (1U << 30)
#define MT_WL_TX_BUSY               (1U << 31)

#define MT_SSUSB_EPCTL_CSR_EP_RST_OPT (0x74011800U + 0x090)

#define MT_UWFDMA0(ofs)             (0x7C024000U + (ofs))
#define MT_UWFDMA0_GLO_CFG          MT_UWFDMA0(0x208)
#define MT_WFDMA0_GLO_CFG_TX_DMA_EN (1U << 0)
#define MT_WFDMA0_GLO_CFG_RX_DMA_EN (1U << 2)
#define MT_WFDMA0_GLO_CFG_RX_DMA_BUSY (1U << 3)
#define MT_WFDMA0_GLO_CFG_FW_DWLD_BYPASS_DMASHDL (1U << 9)
#define MT_WFDMA0_GLO_CFG_OMIT_RX_INFO_PFET2 (1U << 21)
#define MT_WFDMA0_GLO_CFG_OMIT_RX_INFO (1U << 27)
#define MT_WFDMA0_GLO_CFG_OMIT_TX_INFO (1U << 28)

#define MT_WPDMA0_MAX_CNT_MASK      0xFFU
#define MT_WPDMA0_BASE_PTR_MASK     0xFFFF0000U
#define MT_WFDMA_DUMMY_CR           (0x54000000U + 0x120)
#define MT_WFDMA_NEED_REINIT        (1U << 1)
#define MT_WFDMA_HOST_CONFIG        0x7C027030U
#define MT_WFDMA_HOST_CONFIG_USB_RXEVT_EP4_EN (1U << 6)

#define MT_DMA_SHDL(ofs)            (0x7C026000U + (ofs))
#define MT_DMASHDL_PAGE             MT_DMA_SHDL(0x00C)
#define MT_DMASHDL_GROUP_SEQ_ORDER  (1U << 16)
#define MT_DMASHDL_REFILL           MT_DMA_SHDL(0x010)
#define MT_DMASHDL_REFILL_MASK      0xFFFF0000U
#define MT_DMASHDL_PKT_MAX_SIZE     MT_DMA_SHDL(0x01C)
#define MT_DMASHDL_PKT_MAX_SIZE_PLE 0x00000FFFU
#define MT_DMASHDL_PKT_MAX_SIZE_PSE 0x0FFF0000U
#define MT_DMASHDL_GROUP_QUOTA(n)   MT_DMA_SHDL(0x020 + ((n) << 2))
#define MT_DMASHDL_Q_MAP(n)         MT_DMA_SHDL(0x060 + ((n) << 2))
#define MT_DMASHDL_SCHED_SET(n)     MT_DMA_SHDL(0x070 + ((n) << 2))
#define MT_UWFDMA0_TX_RING_EXT_CTRL(n) MT_UWFDMA0(0x600 + ((n) << 2))

#define MT_WFSYS_SW_RST_B           0x18000140U
#define WFSYS_SW_RST_B              (1U << 0)
#define WFSYS_SW_INIT_DONE          (1U << 4)
#define MT_CBTOP_RGU_WF_SUBSYS_RST  (0x70002000U + 0x600)
#define MT_CBTOP_RGU_WF_SUBSYS_RST_WF_WHOLE_PATH (1U << 0)
#define MT792x_WFSYS_INIT_RETRY_COUNT 2
#define MT792X_USB_UDMA_IDLE_TIMEOUT 1000

#define MT_SWDEF_MODE               (0x41F200U + 0x3C)
#define MT_SWDEF_NORMAL_MODE        0

/* MCU constants */
#define MT_HDR_FORMAT_CMD           1
#define MT_TX_TYPE_CMD              2
#define MT_TX_MCU_PORT_RX_Q0        0x20
#define MT_TX_PORT_IDX_MCU          1

#define MCU_PKT_ID                  0xA0
#define MCU_Q_QUERY                 0
#define MCU_Q_SET                   1
#define MCU_Q_RESERVED              2
#define MCU_Q_NA                    3

#define MCU_S2D_H2N                 0
#define MCU_S2D_C2N                 1
#define MCU_S2D_H2C                 2
#define MCU_S2D_H2CN                3

#define MCU_CMD_TARGET_ADDRESS_LEN_REQ 0x01
#define MCU_CMD_FW_START_REQ        0x02
#define MCU_CMD_NIC_POWER_CTRL      0x04
#define MCU_CMD_PATCH_START_REQ     0x05
#define MCU_CMD_PATCH_FINISH_REQ    0x07
#define MCU_CMD_PATCH_SEM_CONTROL   0x10
#define MCU_CMD_FW_SCATTER          0xEE

#define PATCH_SEM_RELEASE           0
#define PATCH_SEM_GET               1
#define PATCH_NOT_DL_SEM_FAIL       0
#define PATCH_IS_DL                 1
#define PATCH_NOT_DL_SEM_SUCCESS    2
#define PATCH_REL_SEM_SUCCESS       3

#define DL_MODE_ENCRYPT             (1U << 0)
#define DL_MODE_KEY_IDX_SHIFT       1
#define DL_MODE_RESET_SEC_IV        (1U << 3)
#define DL_MODE_WORKING_PDA_CR4     (1U << 4)
#define DL_CONFIG_ENCRY_MODE_SEL    (1U << 6)
#define DL_MODE_NEED_RSP            (1U << 31)

#define FW_START_OVERRIDE           (1U << 0)
#define FW_START_WORKING_PDA_CR4    (1U << 2)

#define FW_FEATURE_SET_ENCRYPT      (1U << 0)
#define FW_FEATURE_SET_KEY_IDX      0x6
#define FW_FEATURE_ENCRY_MODE       (1U << 4)
#define FW_FEATURE_OVERRIDE_ADDR    (1U << 5)
#define FW_FEATURE_NON_DL           (1U << 6)

#define PATCH_SEC_TYPE_MASK         0xFFFFU
#define PATCH_SEC_TYPE_INFO         0x2
#define PATCH_SEC_NOT_SUPPORT       0xFFFFFFFFU
#define PATCH_SEC_ENC_TYPE_PLAIN    0x00
#define PATCH_SEC_ENC_TYPE_AES      0x01
#define PATCH_SEC_ENC_TYPE_SCRAMBLE 0x02

#define MCU_TXD_LEN                 64
#define MCU_RXD_LEN                 36
#define RXD_SEQ_OFFSET              29
#define RXD_STATUS_OFFSET           32
#define PKT_TYPE_RX_EVENT           7
#define PKT_TYPE_NORMAL             2
#define RXD0_PKT_FLAG_SHIFT         16
#define RXD0_PKT_FLAG_MASK          0xFU
#define PKT_FLAG_NORMAL_MCU         1
#define FW_SCATTER_MAX              4096

/* Full command word fields */
#define MCU_CMD_FIELD_ID            0x000000FFU
#define MCU_CMD_FIELD_EXT_ID        0x0000FF00U
#define MCU_CMD_FIELD_QUERY         (1U << 16)
#define MCU_CMD_FIELD_UNI           (1U << 17)
#define MCU_CMD_FIELD_CE            (1U << 18)
#define MCU_CMD_FIELD_WA            (1U << 19)
#define MCU_CMD_FIELD_WM            (1U << 20)

#define MCU_CMD_EXT_CID             0xED
#define MCU_EXT_CMD_CHANNEL_SWITCH  0x08
#define MCU_EXT_CMD_SET_RX_PATH     0x4E
#define MCU_EXT_CMD_EFUSE_BUFFER_MODE 0x21
#define MCU_CE_CMD_GET_NIC_CAPAB    0x8A
#define MCU_CE_CMD_SET_RX_FILTER    0x0A

#define MCU_EXT_CMD(ext_id)         (MCU_CMD_EXT_CID | (((ext_id) << 8) & MCU_CMD_FIELD_EXT_ID))
#define MCU_CE_CMD(ce_id)           (MCU_CMD_FIELD_CE | ((ce_id) & MCU_CMD_FIELD_ID))

#define CMD_CBW_20MHZ               0
#define CMD_CBW_40MHZ               1
#define CMD_CBW_80MHZ               2
#define CMD_CBW_160MHZ              3
#define CH_SWITCH_NORMAL            0

#define MT7921_FILTER_FCSFAIL       (1U << 2)
#define MT7921_FILTER_CONTROL       (1U << 5)
#define MT7921_FILTER_OTHER_BSS     (1U << 6)
#define MT7921_FILTER_ENABLE        (1U << 31)

#define MONITOR_FILTER              (MT7921_FILTER_ENABLE | MT7921_FILTER_FCSFAIL | \
                                     MT7921_FILTER_CONTROL | MT7921_FILTER_OTHER_BSS)

#define MT7921_FIF_BIT_SET          (1U << 0)
#define MT7921_FIF_BIT_CLR          (1U << 1)

#define MT_WF_RFCR_DROP_STBC_MULTI  (1U << 0)
#define MT_WF_RFCR_DROP_FCSFAIL     (1U << 1)
#define MT_WF_RFCR_DROP_VERSION     (1U << 3)
#define MT_WF_RFCR_DROP_PROBEREQ    (1U << 4)
#define MT_WF_RFCR_DROP_MCAST       (1U << 5)
#define MT_WF_RFCR_DROP_BCAST       (1U << 6)
#define MT_WF_RFCR_DROP_MCAST_FILTERED (1U << 7)
#define MT_WF_RFCR_DROP_A3_MAC      (1U << 8)
#define MT_WF_RFCR_DROP_A3_BSSID    (1U << 9)
#define MT_WF_RFCR_DROP_A2_BSSID    (1U << 10)
#define MT_WF_RFCR_DROP_OTHER_BEACON (1U << 11)
#define MT_WF_RFCR_DROP_FRAME_REPORT (1U << 12)
#define MT_WF_RFCR_DROP_CTL_RSV     (1U << 13)
#define MT_WF_RFCR_DROP_CTS         (1U << 14)
#define MT_WF_RFCR_DROP_RTS         (1U << 15)
#define MT_WF_RFCR_DROP_DUPLICATE   (1U << 16)
#define MT_WF_RFCR_DROP_OTHER_BSS   (1U << 17)
#define MT_WF_RFCR_DROP_OTHER_UC    (1U << 18)
#define MT_WF_RFCR_DROP_OTHER_TIM   (1U << 19)
#define MT_WF_RFCR_DROP_NDPA        (1U << 20)
#define MT_WF_RFCR_DROP_UNWANTED_CTL (1U << 21)

#define MONITOR_DROP_CLEAR          (MT_WF_RFCR_DROP_STBC_MULTI | MT_WF_RFCR_DROP_VERSION | \
                                     MT_WF_RFCR_DROP_PROBEREQ | MT_WF_RFCR_DROP_MCAST | \
                                     MT_WF_RFCR_DROP_BCAST | MT_WF_RFCR_DROP_MCAST_FILTERED | \
                                     MT_WF_RFCR_DROP_A3_MAC | MT_WF_RFCR_DROP_A3_BSSID | \
                                     MT_WF_RFCR_DROP_A2_BSSID | MT_WF_RFCR_DROP_OTHER_BEACON | \
                                     MT_WF_RFCR_DROP_CTL_RSV | MT_WF_RFCR_DROP_DUPLICATE | \
                                     MT_WF_RFCR_DROP_OTHER_BSS | MT_WF_RFCR_DROP_OTHER_UC | \
                                     MT_WF_RFCR_DROP_OTHER_TIM | MT_WF_RFCR_DROP_UNWANTED_CTL)

/* UNI commands */
#define MCU_CMD_ACK                 (1U << 0)
#define MCU_CMD_UNI                 (1U << 1)
#define MCU_CMD_SET                 (1U << 2)
#define MCU_CMD_UNI_EXT_ACK         (MCU_CMD_ACK | MCU_CMD_UNI | MCU_CMD_SET)

#define MCU_UNI_CMD_SNIFFER         0x24
#define MCU_UNI_TXD_LEN             48

#define SNIFFER_BAND_24             1
#define SNIFFER_BAND_5              2
#define SNIFFER_BAND_6              3

#define SNIFFER_BW_20               0
#define SNIFFER_BW_80               1
#define SNIFFER_BW_160              2

#define EE_MODE_EFUSE               0
#define EE_FORMAT_WHOLE             1

/* RXD flags and masks */
#define MT_RXD1_NORMAL_GROUP_1      (1U << 11)
#define MT_RXD1_NORMAL_GROUP_2      (1U << 12)
#define MT_RXD1_NORMAL_GROUP_3      (1U << 13)
#define MT_RXD1_NORMAL_GROUP_4      (1U << 14)
#define MT_RXD1_NORMAL_GROUP_5      (1U << 15)
#define MT_RXD1_NORMAL_SEC_MODE     (0x1FU << 16)
#define MT_RXD1_NORMAL_ICV_ERR      (1U << 25)
#define MT_RXD1_NORMAL_FCS_ERR      (1U << 27)

#define MT_RXD2_NORMAL_AMSDU_ERR    (1U << 23)
#define MT_RXD2_NORMAL_MAX_LEN_ERROR (1U << 24)

#endif /* MT7921_REGS_H */
