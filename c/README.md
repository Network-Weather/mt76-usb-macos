# MT7921U Pure C Monitor-Mode Driver & Smoke Validator

A userspace monitor-mode driver and hardware smoke validator for the MediaTek MT7921AU (USB `0e8d:7961`, e.g. ALFA AWUS036AXML) on macOS, implemented in pure C (C11) with **zero external dependencies**.

## Design & Zero Dependencies

Unlike Python implementations that rely on `pyusb` and dynamic links to Homebrew `libusb-1.0.dylib`, this C driver communicates directly with the macOS kernel USB stack using native Apple system frameworks:
- `IOKit` (`IOUSBDeviceInterface`, `IOUSBInterfaceInterface`)
- `CoreFoundation`

It compiles with standard Apple `clang` included with Xcode / Command Line Tools:
- No Homebrew required
- No libusb required
- No Python runtime or third-party packages required

## Architecture

- `mt7921_regs.h`: Register addresses, bitmasks, endpoint numbers, and vendor request opcodes transcribed from `mt76`.
- `mt7921_usb.h` / `mt7921_usb.c`: Native IOKit device discovery, interface claim, pipe management, vendor control transfers, and bulk I/O with timeouts.
- `mt7921_mcu.h` / `mt7921_mcu.c`: MCU command framing (both non-UNI and UNI), sequence numbering, response demultiplexing on shared RX bulk endpoint, ROM patch parser/downloader, and RAM firmware parser/downloader.
- `mt7921_dev.h` / `mt7921_dev.c`: WFSYS reset, DMA engine initialization, device bringup orchestration, monitor mode filters, and channel tuning for 2.4 GHz, 5 GHz, and 6 GHz bands.
- `mt7921_rxd.h` / `mt7921_rxd.c`: Connac2 RX descriptor decoding, 802.11 frame extraction, RCPI-to-RSSI translation, frame family classification (Management, Control, Data), and standard radiotap pcap writing.
- `mt7921_smoke.c`: Standalone CLI validator mimicking `scripts/hardware_smoke.py`. Emits structured, redacted JSON telemetry to stdout.
- `test_rxd.c`: Offline test suite validating descriptor parsing, frame extraction, and radiotap output without hardware.

## Building

```bash
cd c
make
```

Run offline unit tests:
```bash
make test
```

## Running Hardware Smoke Test

Requires the MT7921AU USB adapter and firmware blobs in `./firmware` (or specified via `--fw <dir>`):

```bash
# Quick 3-band smoke test (channel 1 on 2.4 GHz, 36 on 5 GHz, 53 on 6 GHz PSC)
./mt7921_smoke --plan quick --dwell 0.75

# Full 43-channel sweep across 2.4 GHz, 5 GHz, and 6 GHz PSC
./mt7921_smoke --plan all --dwell 0.75

# Capture live frames to radiotap pcap
./mt7921_smoke --plan quick --dwell 1.0 --pcap capture.pcap
tcpdump -r capture.pcap -c 10
```

## Hardware Validation Baseline

Validated live on macOS against ALFA AWUS036AXML (`0e8d:7961`):
- Cold & warm bringup: Verified (including retained `FW_STATE` WFSYS reset recovery)
- 2.4 GHz, 5 GHz, and 6 GHz PSC capture: Verified (1,333 frames decoded across all 43 channels on `--plan all`)
- Radiotap pcap export: Verified readable by `tcpdump` and Wireshark
