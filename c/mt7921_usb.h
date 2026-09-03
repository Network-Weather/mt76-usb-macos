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

#define MT7921_OK           0
#define MT7921_ERR_TIMEOUT  1
#define MT7921_ERR_IO      -1

typedef struct {
    IOUSBDeviceInterface **dev;
    IOUSBInterfaceInterface **intf;
    UInt8 pipe_rx;          /* EP 0x84 IN */
    UInt8 pipe_cmd_resp;    /* EP 0x85 IN */
    UInt8 pipe_out_cmd;     /* EP 0x08 OUT */
    UInt8 pipe_out_scatter; /* EP 0x04 OUT */
    bool verbose;
} mt7921_usb_t;

/* Lifecycle */
int mt7921_usb_open(mt7921_usb_t *usb);
void mt7921_usb_close(mt7921_usb_t *usb);
int mt7921_usb_reset(mt7921_usb_t *usb);

/* Vendor control requests */
int mt7921_usb_vendor_req(mt7921_usb_t *usb, uint8_t req, uint8_t req_type,
                          uint16_t value, uint16_t index, void *data,
                          uint16_t length, uint32_t timeout_ms);

/* Register access */
uint32_t mt7921_rr(mt7921_usb_t *usb, uint32_t addr);
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

/* Bulk transfers */
int mt7921_bulk_out(mt7921_usb_t *usb, uint8_t ep, const void *data, uint32_t len, uint32_t timeout_ms);
int mt7921_bulk_in(mt7921_usb_t *usb, uint8_t ep, void *data, uint32_t *len, uint32_t timeout_ms);

#endif /* MT7921_USB_H */
