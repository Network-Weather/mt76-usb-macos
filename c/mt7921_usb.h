/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#ifndef MT7921_USB_H
#define MT7921_USB_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>

#include "mt7921_regs.h"
#include "mt7921_chip.h"

#define MT7921_OK           0
#define MT7921_ERR_TIMEOUT  1
#define MT7921_ERR_IO      -1

typedef struct {
    IOUSBDeviceInterface **dev;
    IOUSBInterfaceInterface **intf;
    uint16_t vid;
    uint16_t pid;
    int chip;                          /* mt7921_chip_t */
    uint8_t wifi_interface;            /* bInterfaceNumber of the claimed vendor interface */
    uint8_t usb_speed;                 /* IOKit kUSBDeviceSpeed* code */
    /* Endpoint addresses and IOKit pipe refs by mt76 role (usb.c mt76u_set_endpoints:
     * the first MT_N_BULK_IN bulk IN and MT_N_BULK_OUT bulk OUT endpoints in descriptor
     * order of the class ff/ff/ff interface). */
    uint8_t in_eps[MT_N_BULK_IN];
    uint8_t out_eps[MT_N_BULK_OUT];
    UInt8 in_pipes[MT_N_BULK_IN];
    UInt8 out_pipes[MT_N_BULK_OUT];
    bool verbose;
} mt7921_usb_t;

/* Lifecycle */
/* Open one supported adapter. usb_id is "vvvv:pppp" to pick one when several are attached,
 * or NULL to honor $MT76_USB_ID and otherwise require exactly one supported device. Fails
 * closed (-1) on no device, more than one candidate, an unsupported id, or a descriptor layout
 * without a class ff/ff/ff interface carrying 2 bulk IN and 6 bulk OUT endpoints; the reason is
 * left in mt7921_usb_last_error(). */
int mt7921_usb_open(mt7921_usb_t *usb, const char *usb_id);
const char *mt7921_usb_last_error(void);
void mt7921_usb_close(mt7921_usb_t *usb);
int mt7921_usb_reset(mt7921_usb_t *usb);

/* Vendor control requests */
int mt7921_usb_vendor_req(mt7921_usb_t *usb, uint8_t req, uint8_t req_type,
                          uint16_t value, uint16_t index, void *data,
                          uint16_t length, uint32_t timeout_ms);

/* Register access */
uint32_t mt7921_rr(mt7921_usb_t *usb, uint32_t addr);
/* Unlike the legacy sentinel API, distinguishes a failed read from all-one data. */
int mt7921_rr_checked(mt7921_usb_t *usb, uint32_t addr, uint32_t *value);
int mt7921_wr(mt7921_usb_t *usb, uint32_t addr, uint32_t val);
uint32_t mt7921_rmw(mt7921_usb_t *usb, uint32_t addr, uint32_t mask, uint32_t val);

static inline uint32_t mt7921_set_bits(mt7921_usb_t *usb, uint32_t addr, uint32_t bits) {
    return mt7921_rmw(usb, addr, bits, bits);
}

static inline uint32_t mt7921_clear_bits(mt7921_usb_t *usb, uint32_t addr, uint32_t bits) {
    return mt7921_rmw(usb, addr, bits, 0);
}

uint32_t mt7921_uhw_rr(mt7921_usb_t *usb, uint32_t addr);
int mt7921_uhw_wr(mt7921_usb_t *usb, uint32_t addr, uint32_t val);
int mt7921_copy(mt7921_usb_t *usb, uint32_t offset, const uint8_t *data, size_t len);

/* Polling & power */
int mt7921_poll(mt7921_usb_t *usb, uint32_t addr, uint32_t mask, uint32_t expect, uint32_t timeout_ms);
int mt7921_power_on(mt7921_usb_t *usb);

/* Bulk transfers; ep is an MT_ROLE_* handle, not a raw endpoint address */
int mt7921_bulk_out(mt7921_usb_t *usb, uint8_t ep, const void *data, uint32_t len, uint32_t timeout_ms);
int mt7921_bulk_in(mt7921_usb_t *usb, uint8_t ep, void *data, uint32_t *len, uint32_t timeout_ms);

#endif /* MT7921_USB_H */
