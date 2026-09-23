// SPDX-License-Identifier: BSD-3-Clause-Clear
// Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
// Read-only MT7961 register probe using the Windows SDK, without libusb.
// Pass the DeviceInterfaceGUIDs value registered for USB\VID_0E8D&PID_7961&MI_03.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <setupapi.h>
#include <winusb.h>
#include <objbase.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

static int fail(const char *operation) {
    fprintf(stderr, "%s failed: Windows error %lu\n", operation, GetLastError());
    return 1;
}

static int read_register(WINUSB_INTERFACE_HANDLE usb, ULONG address, UCHAR type, UCHAR request) {
    // mt7921u.py rr(): READ_EXT, vendor recipient 0x1f, address split over value/index.
    WINUSB_SETUP_PACKET setup = {0};
    UCHAR value[4] = {0};
    ULONG transferred = 0;
    setup.RequestType = type;
    setup.Request = request;
    setup.Value = (USHORT)(address >> 16);
    setup.Index = (USHORT)address;
    setup.Length = sizeof(value);
    printf("read type=0x%02x request=0x%02x address=0x%08lx: ", type, request, address);
    if (!WinUsb_ControlTransfer(usb, setup, value, sizeof(value), &transferred, NULL)) {
        printf("Windows error %lu\n", GetLastError());
        return 1;
    }
    if (transferred != sizeof(value)) {
        fprintf(stderr, "Short register read: %lu bytes\n", transferred);
        return 1;
    }
    ULONG decoded = (ULONG)value[0] | ((ULONG)value[1] << 8) |
                    ((ULONG)value[2] << 16) | ((ULONG)value[3] << 24);
    printf("0x%08lx\n", decoded);
    return 0;
}

static int probe(const WCHAR *path) {
    HANDLE file = CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                              FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return fail("CreateFileW");
    WINUSB_INTERFACE_HANDLE usb = NULL;
    if (!WinUsb_Initialize(file, &usb)) {
        int result = fail("WinUsb_Initialize");
        CloseHandle(file);
        return result;
    }
    int result = 1;
    USB_INTERFACE_DESCRIPTOR descriptor;
    if (!WinUsb_QueryInterfaceSettings(usb, 0, &descriptor)) {
        fail("WinUsb_QueryInterfaceSettings");
        goto done;
    }
    printf("interface=%u class=%02x/%02x/%02x endpoints=%u\n",
           descriptor.bInterfaceNumber, descriptor.bInterfaceClass,
           descriptor.bInterfaceSubClass, descriptor.bInterfaceProtocol,
           descriptor.bNumEndpoints);
    if (descriptor.bInterfaceNumber != 3 || descriptor.bInterfaceClass != 0xff ||
        descriptor.bInterfaceSubClass != 0xff || descriptor.bInterfaceProtocol != 0xff) {
        fprintf(stderr, "Refusing unexpected Wi-Fi interface\n");
        goto done;
    }
    for (UCHAR i = 0; i < descriptor.bNumEndpoints; ++i) {
        WINUSB_PIPE_INFORMATION pipe;
        if (!WinUsb_QueryPipe(usb, 0, i, &pipe)) {
            fail("WinUsb_QueryPipe");
            goto done;
        }
        printf("endpoint=0x%02x type=%u max_packet=%u\n",
               pipe.PipeId, (unsigned)pipe.PipeType, pipe.MaximumPacketSize);
    }
    ULONG timeout_ms = 2000;
    if (!WinUsb_SetPipePolicy(usb, 0, PIPE_TRANSFER_TIMEOUT, sizeof(timeout_ms), &timeout_ms)) {
        fail("WinUsb_SetPipePolicy");
        goto done;
    }
    result = read_register(usb, 0x70010200, 0xdf, 0x63);
    if (result == 0)
        result = read_register(usb, 0x70010204, 0xdf, 0x63);
    if (result == 0)
        result = read_register(usb, 0x70010200, 0xde, 0x01);
    if (result == 0)
        result = read_register(usb, 0x74011890, 0xdf, 0x63);
    if (result == 0)
        result = read_register(usb, 0x74011890, 0xde, 0x01);
done:
    WinUsb_Free(usb);
    CloseHandle(file);
    return result;
}

int wmain(int argc, WCHAR **argv) {
    GUID guid;
    if (argc != 2 || FAILED(CLSIDFromString(argv[1], &guid))) {
        fprintf(stderr, "Usage: winusb_probe.exe {Wi-Fi DeviceInterfaceGUID}\n");
        return 2;
    }
    HDEVINFO devices = SetupDiGetClassDevsW(&guid, NULL, NULL,
                                          DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (devices == INVALID_HANDLE_VALUE)
        return fail("SetupDiGetClassDevsW");
    int result = 3;
    for (DWORD index = 0;; ++index) {
        SP_DEVICE_INTERFACE_DATA interface_data = {0};
        interface_data.cbSize = sizeof(interface_data);
        if (!SetupDiEnumDeviceInterfaces(devices, NULL, &guid, index, &interface_data)) {
            if (GetLastError() != ERROR_NO_MORE_ITEMS)
                result = fail("SetupDiEnumDeviceInterfaces");
            break;
        }
        DWORD size = 0;
        SetupDiGetDeviceInterfaceDetailW(devices, &interface_data, NULL, 0, &size, NULL);
        if (GetLastError() != ERROR_INSUFFICIENT_BUFFER || size == 0) {
            result = fail("SetupDiGetDeviceInterfaceDetailW size");
            break;
        }
        PSP_DEVICE_INTERFACE_DETAIL_DATA_W detail = malloc(size);
        if (detail == NULL) {
            fprintf(stderr, "Allocation failed\n");
            result = 1;
            break;
        }
        detail->cbSize = sizeof(*detail);
        if (!SetupDiGetDeviceInterfaceDetailW(devices, &interface_data, detail, size, NULL, NULL)) {
            result = fail("SetupDiGetDeviceInterfaceDetailW");
            free(detail);
            break;
        }
        // Windows device paths are case-insensitive. Do not print identifying paths.
        CharLowerBuffW(detail->DevicePath, (DWORD)wcslen(detail->DevicePath));
        if (wcsstr(detail->DevicePath, L"usb#vid_0e8d&pid_7961&mi_03#") != NULL) {
            result = probe(detail->DevicePath);
            free(detail);
            break;
        }
        free(detail);
    }
    SetupDiDestroyDeviceInfoList(devices);
    if (result == 3)
        fprintf(stderr, "No MT7961 interface 3 found for this GUID\n");
    return result;
}
