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

## Architectural Boundary

This driver focuses strictly on MediaTek chipset-specific primitives:
- Native IOKit USB pipe management and control requests
- MCU command framing (standard and UNI formats)
- Firmware scatter download and efuse calibration push
- Connac2 TXWI (transmit) and RXD (receive) descriptor processing
- Hardware monitor drop filters and channel switching
- On-die thermal monitoring and raw efuse block access

Generic 802.11 Information Element (IE) parsing intentionally does not belong in this driver. Traffic is exported as standard IEEE 802.11 Radiotap frames to PCAP, delegating upper-layer protocol analysis to external tools such as Wireshark, `tcpdump`, or libpcap.

## Architecture

- `mt7921_regs.h`: Register addresses, bitmasks, endpoint numbers, TXWI layout, and MCU vendor request opcodes transcribed from `mt76`.
- `mt7921_usb.h` / `mt7921_usb.c`: Native IOKit device discovery, interface claim, pipe management, vendor control transfers, and bulk I/O with timeout differentiation (`MT7921_ERR_TIMEOUT` vs `MT7921_ERR_IO`).
- `mt7921_mcu.h` / `mt7921_mcu.c`: MCU command framing (both non-UNI and UNI), sequence numbering, response demultiplexing on shared RX bulk endpoint, ROM patch parser/downloader, RAM firmware parser/downloader, on-die temperature sensor query, and raw efuse block reads.
- `mt7921_dev.h` / `mt7921_dev.c`: WFSYS reset, DMA engine initialization, device bringup orchestration, monitor mode filters, channel tuning for 2.4 GHz, 5 GHz, and 6 GHz bands, 802.11 probe request generation, Connac2 TXWI descriptor framing, and packet injection.
- `mt7921_rxd.h` / `mt7921_rxd.c`: Connac2 RX descriptor decoding, 802.11 frame extraction, RCPI-to-RSSI translation, frame family classification (Management, Control, Data), and standard radiotap pcap writing.
- `mt7921_smoke.c`: Standalone CLI validator mimicking `scripts/hardware_smoke.py`. Emits structured, redacted JSON telemetry to stdout conforming to `docs/hardware-smoke.schema.json`.
- `test_rxd.c`: Offline unit test suite validating descriptor parsing, frame extraction, radiotap output, RAM firmware bounds checks, probe request framing, and TXWI descriptor layout without hardware.

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

# Test packet injection across channels (5 probe requests per channel)
./mt7921_smoke --plan quick --dwell 0.5 --inject 5

# Query on-die temperature sensor
./mt7921_smoke --temp

# Read a raw 16-byte efuse block
./mt7921_smoke --read-efuse 0x000
```

## Hardware Validation Baseline

Validated live on macOS against ALFA AWUS036AXML (`0e8d:7961`):
- Cold & warm bringup: Verified (including retained `FW_STATE` WFSYS reset recovery)
- 2.4 GHz, 5 GHz, and 6 GHz PSC capture: Verified (1,333 frames decoded across all 43 channels on `--plan all`)
- Packet injection: Verified (5 probe requests sent per channel with chip alive)
- Die temperature: Verified (returns active sensor reading, e.g. 32°C)
- Raw EFUSE read: Verified (block 0x000 returns MT7961 chip ID `61 79` with valid flag)
- Radiotap pcap export: Verified readable by `tcpdump` and Wireshark
