# MT7921U / MT7925U Pure C Monitor-Mode Driver & Smoke Validator

A userspace monitor-mode driver and hardware smoke validator for the MediaTek MT7921AU (USB `0e8d:7961`, e.g. ALFA AWUS036AXML) and MT7925U (e.g. Netgear Nighthawk A9000, `0846:9072`) on macOS, implemented in pure C (C11) with **zero external dependencies**. The chip is selected from the adapter's USB id (`mt7921_chip.c`), and everything chip-specific reads a profile from it.

## Research parity status (2026-09-04)

C acquisition parity is in progress. Hardware timestamps and raw Group-3/5 export
are implemented and cross-checked against Python on synthetic bytes for all 32
group masks on both chips, including malformed DMA/group lengths. They are not yet
hardware-qualified in this port. MCU occupancy queries and reversible experimental
Group-5 control are implemented with offline wire and fault-injection tests.
MT7925 controlled TX, the measured OFDM/power controls, and per-chip TX-status
decoding are implemented and cross-checked against the Python research helpers.
Live qualification of these new C paths is pending; these are not general TX APIs.
See the [C parity sprint checklist](../TODO.md#c-parity-sprint-r30).
The [port contract and verification method](../docs/C_PARITY.md) map each Python
primitive to its native C API and state the measurement/cleanup limitations.
Passing the existing C tests is not evidence that those features were ported.

The project remains an interrogation/capture instrument with explicitly gated radio
experiments, not a system networking driver or baseline Internet connection. The
deferred iPad survey spike is a separate transport experiment, not part of this port.

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
- Native IOKit USB device selection from a supported-id table, interface selection by class `ff/ff/ff` with positional bulk endpoint roles (as `mt76u_set_endpoints`), pipe management, and control requests
- MCU command framing (standard and UNI formats) with per-chip geometry: connac2 (MT7921) or connac3 (MT7925) TXD word 1, reply header length, and the UNI ack option
- Firmware scatter download, and the capability query and efuse calibration push in their CE/EXT (MT7921) or UNI (MT7925) encodings
- Connac2 TXWI (transmit) descriptor formatting and frame injection (MT7921 only)
- Radiotap pcap writing through EHT: legacy rate, HT MCS, VHT, HE, and for Wi-Fi 7 frames the U-SIG and EHT TLVs Wireshark 4.6 reads as 802.11be
- Connac2 and connac3 RXD/RXV (receive) processing and **hardware PHY telemetry** (P-RXV decoding: PHY generation CCK/OFDM/HT/VHT/HE/EHT, MCS index incl. EHT 12/13, spatial streams NSS, bandwidth incl. 160 MHz, guard interval, and calculated data rate in Mbps)
- Hardware monitor drop filters and tuning (`mt7921_tune`: CHANNEL_SWITCH plus the sniffer TLV on the MT7921, the TLV alone on the MT7925)
- On-die thermal monitoring and raw efuse block access (MT7921 only)

Generic 802.11 Information Element (IE) parsing intentionally does not belong in this driver. While hardware PHY telemetry is extracted directly from the MediaTek radio descriptors and encoded into standard IEEE 802.11 Radiotap rate/MCS headers, upper-layer protocol analysis is delegated to external tools such as Wireshark, `tcpdump`, or libpcap.

## Architecture

- `mt7921_regs.h`: Register addresses, bitmasks, endpoint roles, TXWI layout, MCU vendor request opcodes, and the MT7925 (connac3) constants transcribed from `mt76`.
- `mt7921_chip.h` / `mt7921_chip.c`: The supported USB-id table, the per-chip profile (chip id, MCU geometry, WFSYS reset descriptor, firmware files and SHA-256 pins), and the UNI option rule.
- `mt7921_rxd_connac3.c`: connac3 (MT7925) RX descriptor and P-RXV decoding into the same frame struct as the connac2 decoder.
- `mt7921_usb.h` / `mt7921_usb.c`: Native IOKit device discovery, interface claim, pipe management, vendor control transfers, and bulk I/O with timeout differentiation (`MT7921_ERR_TIMEOUT` vs `MT7921_ERR_IO`).
- `mt7921_mcu.h` / `mt7921_mcu.c`: MCU command framing (both non-UNI and UNI), sequence numbering, response demultiplexing on shared RX bulk endpoint, ROM patch parser/downloader, RAM firmware parser/downloader, on-die temperature sensor query, and raw efuse block reads.
- `mt7921_dev.h` / `mt7921_dev.c`: WFSYS reset (profile-driven), DMA engine initialization, device bringup orchestration, monitor mode filters (CE or UNI), `mt7921_tune` for 2.4 GHz, 5 GHz, and 6 GHz at 20/40/80/160 MHz, 802.11 probe request generation, Connac2 TXWI descriptor framing, and packet injection.
- `mt7921_rxd.h` / `mt7921_rxd.c`: Connac2 RX descriptor decoding, P-RXV hardware PHY telemetry decoding (`mt7921_decode_rxv`), the shared rate arithmetic (`mt7921_phy_fill_rate`, HT through EHT), the per-chip decoder selector, 802.11 frame extraction, RCPI-to-RSSI translation, frame family classification, and radiotap pcap writing with rate and MCS metadata.
- `mt7921_smoke.c`: Standalone CLI validator mimicking `scripts/hardware_smoke.py`. Emits structured, redacted JSON telemetry to stdout conforming to `docs/hardware-smoke.schema.json`.
- `mt7921_radio.h` / `mt7921_radio.c`: Bounded MIB wire helpers and timed samples,
  reversible Group-5 guards, experimental Probe Request descriptors/submission,
  MT7925 volatile rate-table setup, and TX-status parsing. The register boundary
  is injectable for offline failure and cleanup tests.
- `mt76_radio_probe.c`: Native redacted NDJSON acquisition/experiment CLI. It is
  separate from the existing smoke schema and never enables TX implicitly.
- `test_rxd.c`: Offline unit test suite validating connac2 and connac3 descriptor parsing, frame extraction, radiotap output, RAM firmware bounds checks, probe request framing, TXWI descriptor layout, the chip table and profiles, and the MT7925 MCU TXD builders without hardware.

The frame/device structs have grown for parity metadata and experimental state.
Rebuild embedding consumers; this source library does not promise a stable binary ABI.

## Building

```bash
cd c
make
```

Run offline unit tests:
```bash
make test
```

The bounded native research CLI emits redacted NDJSON and is passive unless
`--transmit` and `--acknowledge-experimental-transmit` are both supplied:

```bash
./mt76_radio_probe --usb-id 0846:9072 --fw ../firmware --mib --seconds 6
./mt76_radio_probe --usb-id 0e8d:7961 --fw ../firmware --mib --g5-cycle --seconds 3
./mt76_radio_probe --usb-id 0846:9072 --fw ../firmware --channel 36 --seconds 6 \
  --transmit 20 --rate ofdm6 --power-code -8 --acknowledge-experimental-transmit
```

This experiment uses 20 MHz only, on 2.4 GHz channel 6, 5 GHz 36/149, or passive
6 GHz 37. OFDM TX is limited to 5 GHz 36/149; CCK1 to MT7921 on channel 6 with
zero power offset. MT7921 supports OFDM6 and offsets 0/-8/-16; MT7925 supports
OFDM6/54 and 0/-8/-16/-32. At most 60 writes per boot, paced at least 50 ms apart.
The CLI reloads firmware after TX/table experiments, including failures, and
restores Group-5 on normal/error/signal exits. SIGKILL, host crash, and unplug can
prevent cleanup; restart/reload before reuse. It does not enforce a regulatory domain.
The older smoke/injection API remains MT7921-only and unchanged in rate.

## Running Hardware Smoke Test

Requires a supported adapter and the firmware blobs in `./firmware` (or `--fw <dir>`, or `$MT76_FW_DIR`); `bash setup.sh` at the repository root fetches both chips' blobs. With two adapters attached, pick one with `--usb-id vvvv:pppp` or `$MT76_USB_ID`. The temperature, efuse, and injection options are MT7921-only and refuse on the MT7925:

```bash
# Quick 3-band smoke test (channel 1 on 2.4 GHz, 36 on 5 GHz, 53 on 6 GHz PSC)
./mt7921_smoke --plan quick --dwell 0.75

# Full 43-channel sweep across 2.4 GHz, 5 GHz, and 6 GHz PSC
./mt7921_smoke --plan all --dwell 0.75

# Capture live frames to radiotap pcap
./mt7921_smoke --plan quick --dwell 1.0 --pcap capture.pcap

# One channel at 160 MHz (MT7925) instead of a plan
./mt7921_smoke --channel 6GHz:53:47:160 --dwell 10 --pcap wide.pcap
tcpdump -r capture.pcap -c 10

# Test experimental packet injection (rate-limited, requires explicit acknowledgement)
./mt7921_smoke --plan quick --dwell 0.5 --inject 3 --acknowledge-experimental-transmit

# Query on-die temperature sensor
./mt7921_smoke --temp

# Read a raw 16-byte efuse block (MAC address masked by default)
./mt7921_smoke --read-efuse 0x000
```

## Hardware Validation Baseline

Detailed dated test criteria, commands, and results are documented in [`docs/TESTING.md`](../docs/TESTING.md#attached-hardware-validation-pure-c-driver-2026-09-02) for the MT7921U and in [its MT7925U section](../docs/TESTING.md#pure-c-driver-on-the-mt7925u-2026-09-03).

MT7925U, Netgear Nighthawk A9000 (`0846:9072`), 2026-09-03: firmware boot, monitor mode, and the full 43-channel sweep pass (1,825 frames decoded, 0 undecoded transfers, 0 USB errors); the sweep's pcap dissects in tshark; the 37 of 1,825 frames tshark flags are complete VHT NDP Announcements whose 8-bit sounding token Wireshark reads as an HE or Ranging variant, and beacons from one AP that carry a zero-length Supported Rates element (details in TESTING.md).

Validation baseline on macOS against ALFA AWUS036AXML (`0e8d:7961`):
- Cold & warm bringup: Verified live on hardware (including retained `FW_STATE` WFSYS reset recovery)
- 2.4 GHz, 5 GHz, and 6 GHz PSC capture: Verified live on hardware (1,333 frames decoded across all 43 channels on `--plan all`)
- Probe request submission to USB: Research-grade and rate-limited. Low-rate probe request constructor and paced bulk submission helper implemented; sustained injection across bands remains explicitly untested per `docs/TESTING.md`. Bulk write acceptance establishes USB transfer completion.
- Die temperature: Verified live on hardware (returns active sensor reading, e.g. 32°C)
- Raw EFUSE read: Verified live on hardware (block 0x000 returns MT7961 chip ID `61 79` with valid flag; MAC bytes masked by default)
- Radiotap pcap export: Live capture verified readable by `tcpdump` and Wireshark for legacy and HT rates; VHT and HE radiotap fields verified via synthetic test pcap writer
