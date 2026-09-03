/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather */
/* Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear). */

#include "mt7921_usb.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/time.h>
#include <stdarg.h>

#define VEND_TIMEOUT_MS 1000
#define VEND_RETRIES    10

static uint64_t current_time_ms(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (uint64_t)tv.tv_sec * 1000ULL + (uint64_t)tv.tv_usec / 1000ULL;
}

static char g_last_error[256];

const char *mt7921_usb_last_error(void) { return g_last_error; }

static void set_error(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(g_last_error, sizeof(g_last_error), fmt, ap);
    va_end(ap);
}

static int registry_u16(io_service_t service, CFStringRef key, uint16_t *out) {
    CFTypeRef ref = IORegistryEntryCreateCFProperty(service, key, kCFAllocatorDefault, 0);
    if (!ref) return -1;
    int ok = -1;
    if (CFGetTypeID(ref) == CFNumberGetTypeID()) {
        SInt32 v = 0;
        if (CFNumberGetValue((CFNumberRef)ref, kCFNumberSInt32Type, &v)) {
            *out = (uint16_t)v;
            ok = 0;
        }
    }
    CFRelease(ref);
    return ok;
}

/* Walk one interface's pipes the way mt76u_set_endpoints walks its endpoint descriptors:
 * bulk endpoints only, positional, first MT_N_BULK_IN IN and MT_N_BULK_OUT OUT. Returns 1 when
 * the interface qualifies and fills the role tables, 0 when it does not. */
static int assign_endpoints(IOUSBInterfaceInterface **intf, mt7921_usb_t *out) {
    UInt8 num_pipes = 0;
    if ((*intf)->GetNumEndpoints(intf, &num_pipes) != KERN_SUCCESS) return 0;
    int n_in = 0, n_out = 0;
    for (UInt8 i = 1; i <= num_pipes; i++) {
        UInt8 direction = 0, number = 0, transfer_type = 0, interval = 0;
        UInt16 mps = 0;
        if ((*intf)->GetPipeProperties(intf, i, &direction, &number, &transfer_type, &mps, &interval) != KERN_SUCCESS) {
            continue;
        }
        if (transfer_type != kUSBBulk) continue;
        if (direction == kUSBIn) {
            if (n_in < MT_N_BULK_IN) {
                out->in_eps[n_in] = (uint8_t)(0x80 | number);
                out->in_pipes[n_in] = i;
                n_in++;
            }
        } else if (n_out < MT_N_BULK_OUT) {
            out->out_eps[n_out] = number;
            out->out_pipes[n_out] = i;
            n_out++;
        }
    }
    return (n_in == MT_N_BULK_IN && n_out == MT_N_BULK_OUT) ? 1 : 0;
}

int mt7921_usb_open(mt7921_usb_t *usb, const char *usb_id) {
    if (!usb) return -1;
    memset(usb, 0, sizeof(*usb));
    g_last_error[0] = '\0';

    uint16_t want_vid = 0, want_pid = 0;
    bool filter = false;
    if (!usb_id) usb_id = getenv("MT76_USB_ID");
    if (usb_id && usb_id[0]) {
        if (mt7921_parse_usb_id(usb_id, &want_vid, &want_pid) != 0) {
            set_error("usb id must look like 0e8d:7961, got '%s'", usb_id);
            return -1;
        }
        filter = true;
    }

    /* Enumerate every USB device and keep the supported ones (registry properties only;
     * nothing is opened yet). */
    CFMutableDictionaryRef matching = IOServiceMatching(kIOUSBDeviceClassName);
    if (!matching) return -1;
    io_iterator_t iterator;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, matching, &iterator) != KERN_SUCCESS) return -1;

    io_service_t chosen = 0;
    int chosen_chip = -1;
    uint16_t chosen_vid = 0, chosen_pid = 0;
    int candidates = 0;
    char seen[128] = "";
    io_service_t service;
    while ((service = IOIteratorNext(iterator)) != 0) {
        uint16_t vid = 0, pid = 0;
        if (registry_u16(service, CFSTR("idVendor"), &vid) == 0 && registry_u16(service, CFSTR("idProduct"), &pid) == 0) {
            int chip = mt7921_chip_for_usb_id(vid, pid);
            bool wanted = filter ? (vid == want_vid && pid == want_pid) : (chip >= 0);
            if (wanted && chip >= 0) {
                candidates++;
                size_t used = strlen(seen);
                snprintf(seen + used, sizeof(seen) - used, "%s%04x:%04x", used ? ", " : "", vid, pid);
                if (!chosen) {
                    chosen = service;
                    chosen_chip = chip;
                    chosen_vid = vid;
                    chosen_pid = pid;
                    continue; /* keep the reference */
                }
            } else if (wanted) {
                set_error("device %04x:%04x is not a supported chip", vid, pid);
            }
        }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);

    if (!chosen) {
        if (!g_last_error[0]) {
            set_error("device not found (looked for %s)", filter ? usb_id : "any supported id");
        }
        return -1;
    }
    if (candidates > 1) {
        IOObjectRelease(chosen);
        set_error("%d supported devices attached (%s); pass --usb-id or set MT76_USB_ID", candidates, seen);
        return -1;
    }

    IOCFPlugInInterface **plugin = NULL;
    SInt32 score;
    kern_return_t kr = IOCreatePlugInInterfaceForService(chosen, kIOUSBDeviceUserClientTypeID,
                                                         kIOCFPlugInInterfaceID, &plugin, &score);
    IOObjectRelease(chosen);
    if (kr != KERN_SUCCESS || !plugin) {
        set_error("IOCreatePlugInInterfaceForService failed (0x%x)", kr);
        return -1;
    }
    IOUSBDeviceInterface **dev = NULL;
    HRESULT res = (*plugin)->QueryInterface(plugin, CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID), (LPVOID*)&dev);
    (*plugin)->Release(plugin);
    if (res || !dev) {
        set_error("QueryInterface(kIOUSBDeviceInterfaceID) failed");
        return -1;
    }

    kr = (*dev)->USBDeviceOpen(dev);
    if (kr != KERN_SUCCESS) {
        kr = (*dev)->USBDeviceOpenSeize(dev);
        if (kr != KERN_SUCCESS) {
            (*dev)->Release(dev);
            set_error("USBDeviceOpen failed (0x%x)", kr);
            return -1;
        }
    }
    usb->dev = dev;
    usb->vid = chosen_vid;
    usb->pid = chosen_pid;
    usb->chip = chosen_chip;
    (*dev)->GetDeviceSpeed(dev, &usb->usb_speed);

    /* Interface selection: class ff/ff/ff and exactly one interface with the required bulk
     * endpoint shape (mt7925u_device_table / mt7921u_device_table match on class, and
     * mt76u_set_endpoints fails unless it finds 2 IN and 6 OUT). */
    IOUSBFindInterfaceRequest request = {
        .bInterfaceClass = kIOUSBFindInterfaceDontCare,
        .bInterfaceSubClass = kIOUSBFindInterfaceDontCare,
        .bInterfaceProtocol = kIOUSBFindInterfaceDontCare,
        .bAlternateSetting = kIOUSBFindInterfaceDontCare
    };
    io_iterator_t intf_iter;
    if ((*dev)->CreateInterfaceIterator(dev, &request, &intf_iter) != KERN_SUCCESS) {
        mt7921_usb_close(usb);
        set_error("CreateInterfaceIterator failed");
        return -1;
    }

    int qualifying = 0;
    char layout[160] = "";
    io_service_t intf_service;
    while ((intf_service = IOIteratorNext(intf_iter)) != 0) {
        IOCFPlugInInterface **intf_plugin = NULL;
        kr = IOCreatePlugInInterfaceForService(intf_service, kIOUSBInterfaceUserClientTypeID,
                                               kIOCFPlugInInterfaceID, &intf_plugin, &score);
        IOObjectRelease(intf_service);
        if (kr != KERN_SUCCESS || !intf_plugin) continue;
        IOUSBInterfaceInterface **intf = NULL;
        res = (*intf_plugin)->QueryInterface(intf_plugin, CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID), (LPVOID*)&intf);
        (*intf_plugin)->Release(intf_plugin);
        if (res || !intf) continue;

        UInt8 number = 0, cls = 0, sub = 0, proto = 0, neps = 0;
        (*intf)->GetInterfaceNumber(intf, &number);
        (*intf)->GetInterfaceClass(intf, &cls);
        (*intf)->GetInterfaceSubClass(intf, &sub);
        (*intf)->GetInterfaceProtocol(intf, &proto);
        (*intf)->GetNumEndpoints(intf, &neps);
        size_t used = strlen(layout);
        snprintf(layout + used, sizeof(layout) - used, "%sintf %u class %02x/%02x/%02x eps %u",
                 used ? "; " : "", number, cls, sub, proto, neps);

        if (cls != 0xFF || sub != 0xFF || proto != 0xFF) {
            (*intf)->Release(intf);
            continue;
        }
        kr = (*intf)->USBInterfaceOpen(intf);
        if (kr != KERN_SUCCESS) kr = (*intf)->USBInterfaceOpenSeize(intf);
        if (kr != KERN_SUCCESS) {
            (*intf)->Release(intf);
            continue;
        }
        mt7921_usb_t probe = *usb;
        if (assign_endpoints(intf, &probe)) {
            qualifying++;
            if (!usb->intf) {
                memcpy(usb->in_eps, probe.in_eps, sizeof(probe.in_eps));
                memcpy(usb->out_eps, probe.out_eps, sizeof(probe.out_eps));
                memcpy(usb->in_pipes, probe.in_pipes, sizeof(probe.in_pipes));
                memcpy(usb->out_pipes, probe.out_pipes, sizeof(probe.out_pipes));
                usb->wifi_interface = number;
                usb->intf = intf;
                continue;
            }
        }
        (*intf)->USBInterfaceClose(intf);
        (*intf)->Release(intf);
    }
    IOObjectRelease(intf_iter);

    if (qualifying != 1 || !usb->intf) {
        set_error(qualifying == 0
                      ? "no interface with class ff/ff/ff and %d bulk IN + %d bulk OUT endpoints (%s)"
                      : "ambiguous layout: %d interfaces qualify (%s)",
                  qualifying == 0 ? MT_N_BULK_IN : qualifying,
                  qualifying == 0 ? MT_N_BULK_OUT : 0, layout);
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

/* ep is an MT_ROLE_* handle: bit 7 selects the IN table, the low bits index the role. */
static UInt8 pipe_for_ep(mt7921_usb_t *usb, uint8_t ep) {
    unsigned idx = ep & 0x7F;
    if (ep & 0x80) return idx < MT_N_BULK_IN ? usb->in_pipes[idx] : 0;
    return idx < MT_N_BULK_OUT ? usb->out_pipes[idx] : 0;
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
