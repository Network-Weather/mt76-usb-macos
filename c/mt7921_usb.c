/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#include "mt7921_usb.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>

#define VEND_TIMEOUT_MS 1000
#define VEND_RETRIES    10

static uint64_t current_time_ms(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000ULL + (uint64_t)tv.tv_usec / 1000ULL;
}

int mt7921_usb_open(mt7921_usb_t *usb) {
    if (!usb) return -1;
    memset(usb, 0, sizeof(*usb));

    CFMutableDictionaryRef matchingDict = IOServiceMatching(kIOUSBDeviceClassName);
    if (!matchingDict) return -1;

    SInt32 vid = MT_VID, pid = MT_PID;
    CFNumberRef vidNum = CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt32Type, &vid);
    CFNumberRef pidNum = CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt32Type, &pid);
    CFDictionarySetValue(matchingDict, CFSTR(kUSBVendorID), vidNum);
    CFDictionarySetValue(matchingDict, CFSTR(kUSBProductID), pidNum);
    CFRelease(vidNum);
    CFRelease(pidNum);

    io_iterator_t iterator;
    kern_return_t kr = IOServiceGetMatchingServices(kIOMainPortDefault, matchingDict, &iterator);
    if (kr != KERN_SUCCESS) return -1;

    io_service_t deviceService = IOIteratorNext(iterator);
    IOObjectRelease(iterator);
    if (!deviceService) return -1;

    IOCFPlugInInterface **plugInInterface = NULL;
    SInt32 score;
    kr = IOCreatePlugInInterfaceForService(deviceService,
                                           kIOUSBDeviceUserClientTypeID,
                                           kIOCFPlugInInterfaceID,
                                           &plugInInterface,
                                           &score);
    IOObjectRelease(deviceService);
    if (kr != KERN_SUCCESS || !plugInInterface) return -1;

    IOUSBDeviceInterface **dev = NULL;
    HRESULT res = (*plugInInterface)->QueryInterface(plugInInterface,
                                                     CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID),
                                                     (LPVOID*)&dev);
    (*plugInInterface)->Release(plugInInterface);
    if (res || !dev) return -1;

    kr = (*dev)->USBDeviceOpen(dev);
    if (kr != KERN_SUCCESS) {
        kr = (*dev)->USBDeviceOpenSeize(dev);
        if (kr != KERN_SUCCESS) {
            (*dev)->Release(dev);
            return -1;
        }
    }
    usb->dev = dev;

    /* Find Interface 3 */
    IOUSBFindInterfaceRequest request = {
        .bInterfaceClass = kIOUSBFindInterfaceDontCare,
        .bInterfaceSubClass = kIOUSBFindInterfaceDontCare,
        .bInterfaceProtocol = kIOUSBFindInterfaceDontCare,
        .bAlternateSetting = kIOUSBFindInterfaceDontCare
    };

    io_iterator_t intfIterator;
    kr = (*dev)->CreateInterfaceIterator(dev, &request, &intfIterator);
    if (kr != KERN_SUCCESS) {
        mt7921_usb_close(usb);
        return -1;
    }

    io_service_t intfService;
    bool found_intf3 = false;
    while ((intfService = IOIteratorNext(intfIterator)) != 0) {
        IOCFPlugInInterface **intfPlugIn = NULL;
        kr = IOCreatePlugInInterfaceForService(intfService,
                                               kIOUSBInterfaceUserClientTypeID,
                                               kIOCFPlugInInterfaceID,
                                               &intfPlugIn,
                                               &score);
        IOObjectRelease(intfService);
        if (kr == KERN_SUCCESS && intfPlugIn) {
            IOUSBInterfaceInterface **intf = NULL;
            res = (*intfPlugIn)->QueryInterface(intfPlugIn,
                                                CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID),
                                                (LPVOID*)&intf);
            (*intfPlugIn)->Release(intfPlugIn);
            if (!res && intf) {
                UInt8 intfNum = 0;
                (*intf)->GetInterfaceNumber(intf, &intfNum);
                if (intfNum == WIFI_INTERFACE) {
                    kr = (*intf)->USBInterfaceOpen(intf);
                    if (kr != KERN_SUCCESS) {
                        kr = (*intf)->USBInterfaceOpenSeize(intf);
                    }
                    if (kr == KERN_SUCCESS) {
                        usb->intf = intf;
                        found_intf3 = true;

                        /* Discover pipe numbers */
                        UInt8 numPipes = 0;
                        (*intf)->GetNumEndpoints(intf, &numPipes);
                        for (UInt8 i = 1; i <= numPipes; i++) {
                            UInt8 direction = 0, number = 0, transferType = 0, interval = 0;
                            UInt16 maxPacketSize = 0;
                            (*intf)->GetPipeProperties(intf, i, &direction, &number,
                                                       &transferType, &maxPacketSize, &interval);
                            uint8_t epAddr = (direction == 1 ? 0x80 : 0x00) | number;
                            if (epAddr == EP_IN_PKT_RX) usb->pipe_rx = i;
                            else if (epAddr == EP_IN_CMD_RESP) usb->pipe_cmd_resp = i;
                            else if (epAddr == EP_OUT_INBAND_CMD) usb->pipe_out_cmd = i;
                            else if (epAddr == EP_OUT_AC_BE) usb->pipe_out_scatter = i;
                        }
                    } else {
                        (*intf)->Release(intf);
                    }
                } else {
                    (*intf)->Release(intf);
                }
            }
        }
        if (found_intf3) break;
    }
    IOObjectRelease(intfIterator);

    if (!found_intf3) {
        mt7921_usb_close(usb);
        return -1;
    }

    return 0;
}

void mt7921_usb_close(mt7921_usb_t *usb) {
    if (!usb) return;
    if (usb->intf) {
        (*usb->intf)->USBInterfaceClose(usb->intf);
        (*usb->intf)->Release(usb->intf);
        usb->intf = NULL;
    }
    if (usb->dev) {
        (*usb->dev)->USBDeviceClose(usb->dev);
        (*usb->dev)->Release(usb->dev);
        usb->dev = NULL;
    }
}

int mt7921_usb_reset(mt7921_usb_t *usb) {
    if (!usb || !usb->dev) return -1;
    kern_return_t kr = (*usb->dev)->ResetDevice(usb->dev);
    usleep(500000); /* 500ms sleep matching Python reset sequence */
    return (kr == KERN_SUCCESS) ? 0 : -1;
}

int mt7921_usb_vendor_req(mt7921_usb_t *usb, uint8_t req, uint8_t req_type,
                          uint16_t value, uint16_t index, void *data,
                          uint16_t length, uint32_t timeout_ms) {
    if (!usb || !usb->dev) return -1;
    (void)timeout_ms;

    IOUSBDevRequest devReq;
    devReq.bmRequestType = req_type;
    devReq.bRequest = req;
    devReq.wValue = value;
    devReq.wIndex = index;
    devReq.wLength = length;
    devReq.pData = data;
    devReq.wLenDone = 0;

    for (int retry = 0; retry < VEND_RETRIES; retry++) {
        kern_return_t kr = (*usb->dev)->DeviceRequest(usb->dev, &devReq);
        if (kr == KERN_SUCCESS) {
            return (int)devReq.wLenDone;
        }
        usleep(5000); /* 5ms retry delay matching Python */
    }
    return -1;
}

uint32_t mt7921_rr(mt7921_usb_t *usb, uint32_t addr) {
    uint32_t val = 0;
    int ret = mt7921_usb_vendor_req(usb,
                                    MT_VEND_READ_EXT,
                                    USB_DIR_IN | MT_USB_TYPE_VENDOR,
                                    (addr >> 16) & 0xFFFF,
                                    addr & 0xFFFF,
                                    &val,
                                    4,
                                    VEND_TIMEOUT_MS);
    if (ret != 4) return 0xFFFFFFFFU;
    return CFSwapInt32LittleToHost(val);
}

int mt7921_wr(mt7921_usb_t *usb, uint32_t addr, uint32_t val) {
    uint32_t le_val = CFSwapInt32HostToLittle(val);
    int ret = mt7921_usb_vendor_req(usb,
                                    MT_VEND_WRITE_EXT,
                                    USB_DIR_OUT | MT_USB_TYPE_VENDOR,
                                    (addr >> 16) & 0xFFFF,
                                    addr & 0xFFFF,
                                    &le_val,
                                    4,
                                    VEND_TIMEOUT_MS);
    return (ret == 4 || ret == 0) ? 0 : -1;
}

uint32_t mt7921_rmw(mt7921_usb_t *usb, uint32_t addr, uint32_t mask, uint32_t val) {
    uint32_t cur = mt7921_rr(usb, addr);
    uint32_t nw = (cur & ~mask) | val;
    mt7921_wr(usb, addr, nw);
    return nw;
}

uint32_t mt7921_uhw_rr(mt7921_usb_t *usb, uint32_t addr) {
    uint32_t val = 0;
    int ret = mt7921_usb_vendor_req(usb,
                                    MT_VEND_DEV_MODE,
                                    USB_DIR_IN | MT_USB_TYPE_UHW_VENDOR,
                                    (addr >> 16) & 0xFFFF,
                                    addr & 0xFFFF,
                                    &val,
                                    4,
                                    VEND_TIMEOUT_MS);
    if (ret != 4) return 0xFFFFFFFFU;
    return CFSwapInt32LittleToHost(val);
}

int mt7921_uhw_wr(mt7921_usb_t *usb, uint32_t addr, uint32_t val) {
    uint32_t le_val = CFSwapInt32HostToLittle(val);
    int ret = mt7921_usb_vendor_req(usb,
                                    MT_VEND_WRITE,
                                    USB_DIR_OUT | MT_USB_TYPE_UHW_VENDOR,
                                    (addr >> 16) & 0xFFFF,
                                    addr & 0xFFFF,
                                    &le_val,
                                    4,
                                    VEND_TIMEOUT_MS);
    return (ret == 4 || ret == 0) ? 0 : -1;
}

int mt7921_copy(mt7921_usb_t *usb, uint32_t offset, const uint8_t *data, size_t len) {
    size_t padded_len = (len + 3) & ~3;
    uint8_t *buf = (uint8_t*)malloc(padded_len);
    if (!buf) return -1;
    memcpy(buf, data, len);
    if (padded_len > len) {
        memset(buf + len, 0, padded_len - len);
    }

    size_t i = 0;
    const size_t chunk = 512;
    while (i < padded_len) {
        size_t n = (padded_len - i < chunk) ? (padded_len - i) : chunk;
        int ret = mt7921_usb_vendor_req(usb,
                                        MT_VEND_WRITE_EXT,
                                        USB_DIR_OUT | MT_USB_TYPE_VENDOR,
                                        ((offset + (uint32_t)i) >> 16) & 0xFFFF,
                                        (offset + (uint32_t)i) & 0xFFFF,
                                        buf + i,
                                        (uint16_t)n,
                                        VEND_TIMEOUT_MS);
        if (ret < 0) {
            free(buf);
            return -1;
        }
        i += n;
    }
    free(buf);
    return 0;
}

int mt7921_poll(mt7921_usb_t *usb, uint32_t addr, uint32_t mask, uint32_t expect, uint32_t timeout_ms) {
    uint64_t deadline = current_time_ms() + timeout_ms;
    while (1) {
        uint32_t val = mt7921_rr(usb, addr);
        if ((val & mask) == expect) {
            return 1;
        }
        if (current_time_ms() > deadline) {
            return 0;
        }
        usleep(10000); /* 10ms */
    }
}

int mt7921_power_on(mt7921_usb_t *usb) {
    mt7921_usb_vendor_req(usb, MT_VEND_POWER_ON, USB_DIR_OUT | MT_USB_TYPE_VENDOR, 0x0, 0x1, NULL, 0, VEND_TIMEOUT_MS);
    return mt7921_poll(usb, MT_CONN_ON_MISC, MT_TOP_MISC2_FW_PWR_ON, MT_TOP_MISC2_FW_PWR_ON, 500);
}

static UInt8 pipe_for_ep(mt7921_usb_t *usb, uint8_t ep) {
    if (ep == EP_IN_PKT_RX) return usb->pipe_rx;
    if (ep == EP_IN_CMD_RESP) return usb->pipe_cmd_resp;
    if (ep == EP_OUT_INBAND_CMD) return usb->pipe_out_cmd;
    if (ep == EP_OUT_AC_BE) return usb->pipe_out_scatter;
    return 0;
}

int mt7921_bulk_out(mt7921_usb_t *usb, uint8_t ep, const void *data, uint32_t len, uint32_t timeout_ms) {
    if (!usb || !usb->intf) return -1;
    UInt8 pipe = pipe_for_ep(usb, ep);
    if (!pipe) return -1;
    kern_return_t kr = (*usb->intf)->WritePipeTO(usb->intf, pipe, (void*)data, len, timeout_ms, timeout_ms);
    return (kr == KERN_SUCCESS) ? 0 : -1;
}

int mt7921_bulk_in(mt7921_usb_t *usb, uint8_t ep, void *data, uint32_t *len, uint32_t timeout_ms) {
    if (!usb || !usb->intf || !data || !len) return MT7921_ERR_IO;
    UInt8 pipe = pipe_for_ep(usb, ep);
    if (!pipe) return MT7921_ERR_IO;
    UInt32 size = *len;
    kern_return_t kr = (*usb->intf)->ReadPipeTO(usb->intf, pipe, data, &size, timeout_ms, timeout_ms);
    *len = size;
    if (kr == KERN_SUCCESS) {
        return MT7921_OK;
    }
    if (kr == kIOUSBTransactionTimeout || kr == kIOReturnTimeout) {
        return MT7921_ERR_TIMEOUT;
    }
    return MT7921_ERR_IO;
}
