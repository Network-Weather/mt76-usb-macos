# Testing and evidence

This document separates repeatable offline tests, current attached-hardware evidence,
older observations, and untested behavior. A passing parser test is not presented as a
hardware result, and a packet seen once is not presented as a reliability guarantee.

## Offline test suite

Run on macOS from the repository root:

```bash
bash setup.sh
./.venv/bin/pip install -e '.[dev]'
./scripts/check.sh
```

As of 2026-09-02, 54 tests pass. They cover:

- MediaTek patch/RAM metadata parsing and truncated-image rejection;
- MCU sequence wrapping, command framing, scatter framing, and endpoint choice without USB;
- 802.11k/v/r, PMF, EasyMesh, 802.11s, four-address, and protected-action parsing;
- channel/RSSI conversion, PHY-rate points, airtime, and A-MPDU grouping;
- radiotap and pcap serialization;
- bounded Probe Request and TXWI input construction without transmitting; and
- random-byte inputs to the descriptor, frame, and IE parsers never raising.

The final wheel was also installed with its declared PyUSB dependency into a newly created
virtual environment. Both modules imported, the module/distribution versions matched `0.1.0`,
and `pip check` reported no broken requirements. This verifies the wheel as an importable
library artifact; [PUBLISHING.md](PUBLISHING.md) explains why `0.1.0` will be distributed as
a GitHub source release rather than a turnkey PyPI application.

The final source distribution was extracted into a new temporary directory and `bash setup.sh`
was run from that copy. It created a fresh environment, installed PyUSB, found Homebrew libusb,
downloaded exactly the two pinned firmware files, and verified both SHA-256 hashes. The scan,
pcap, and hardware-smoke help paths then loaded successfully, while the injection example
refused to run without its explicit transmit acknowledgement flag.

CI runs only on Apple Silicon macOS (`macos-14` and `macos-26`, Python 3.10 and 3.14).
CI has no USB adapter and does not prove firmware boot or RF behavior.

For a redacted attached-device result, run:

```bash
./.venv/bin/python scripts/hardware_smoke.py --plan all > hardware-smoke.json
```

The command is passive-only and emits aggregate counts rather than frames, SSIDs, BSSIDs,
client addresses, payloads, or the USB serial number. Its exit status is 0 for `pass`, 1 for
`fail`, 2 for `inconclusive` (for example, a requested band was quiet), and 3 for
`unsupported` (the exact USB device was absent). The checked-in schema is
[hardware-smoke.schema.json](hardware-smoke.schema.json).

## Attached-hardware validation: 2026-08-31

### Test bed

| Item | Value |
|---|---|
| Host | Apple M1 Max |
| OS | macOS 26.6, build 25G72 |
| Python | 3.14.7 |
| USB device | MediaTek `Wireless_Device`, `0e8d:7961`, USB SuperSpeed |
| Driver access | PyUSB 1.3.1 + Homebrew libusb 1.0.30, unprivileged user |
| RAM firmware SHA-256 | `b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9` |
| Patch firmware SHA-256 | `a276c06c2b772adb50b86639d33c82824ff4c21d617feb78caea74c040b873f6` |
| linux-firmware commit | `e981caea6ed33c48d25b7dbf473327dbd01df163` |

No root process, kernel extension, DriverKit extension, or VM was used.

### Redacted release smoke result

The final aggregate smoke path was run with:

```bash
./.venv/bin/python scripts/hardware_smoke.py --plan all --dwell 0.5
```

It returned `pass` after all 43 requested channels, with 1,156 decoded frames: 316 on
2.4 GHz, 673 on 5 GHz, and 167 on 6 GHz. There were zero undecoded transfers and zero
non-timeout USB errors. Ordinary quiet-channel read timeouts are reported separately (43
in this run) and are not treated as hardware faults. The full aggregate-only result is
[hardware-smoke-reference.json](hardware-smoke-reference.json); its UTC timestamp falls on
2026-09-01 while the America/Los_Angeles test date was 2026-08-31.

### Passive tri-band sweep

```bash
DWELL_SECONDS=0.75 ./.venv/bin/python examples/scan.py all
```

One firmware boot followed by 43 channel changes completed. The scan observed 67 physical
BSSIDs: 24 on 2.4 GHz, 37 on 5 GHz, and 6 on 6 GHz. At least one beacon or Probe Response
was decoded on each band. This proves the tested device could boot, accept monitor/sniffer
commands, retune, receive USB transfers, decode descriptors, and parse management frames
on all three bands in that RF environment.

It does **not** prove that every legal channel, channel width, frame subtype, or regulatory
domain works. A quiet channel returning no packets is not itself a driver failure.

### Independent 6 GHz pcap check

```bash
./.venv/bin/python examples/sniff_to_pcap.py 53 5 /tmp/mt7921u-e2e-6ghz.pcap 6GHz
/Applications/Wireshark.app/Contents/MacOS/capinfos /tmp/mt7921u-e2e-6ghz.pcap
/Applications/Wireshark.app/Contents/MacOS/tshark \
  -r /tmp/mt7921u-e2e-6ghz.pcap -Y '_ws.malformed' -T fields -e frame.number
```

The capture contained 353 packets over 5.008523 seconds at radiotap frequency 6215 MHz.
Wireshark classified 307 as management and 46 as data; its malformed filter returned zero
packets. `capinfos` identified the encapsulation as “IEEE 802.11 plus radiotap radio
header.” The local pcap SHA-256 was
`d4ced0a3929ffab020c06697fe148542e0c47431a3086800eaf1668099920457`.

The pcap is not committed because ambient captures contain third-party MAC addresses and
network names. The hash records the exact artifact that was checked without publishing it.

After the publication edits, the same command path was rerun for two seconds. It produced
57 more 6 GHz packets, again with zero packets matching Wireshark's `_ws.malformed` filter
(pcap SHA-256 `f17e156261f0ade1126e81585ee7fa6e9cc49a78009fcd09d858b97618d8c4c4`).

After the final release-safety changes, a fresh three-second channel 53 capture produced
232 packets over 3.010363 seconds: 189 management and 43 data frames. `capinfos` again
identified radiotap 802.11, strict time order was true, and tshark returned zero packets
for `_ws.malformed`. Its unpublished ambient pcap SHA-256 is
`cbaa4953e9d45f550304e30b8dbe10569f25e5b6c0bd00d017dd556816897a0a`.

## Retune frame loss: 2026-09-02

Same host and firmware as the 2026-08-31 test bed; macOS 26.6, Python 3.14.7, reference adapter.

```bash
./.venv/bin/python scripts/retune_drops.py --retunes 10 --dwell 2
./.venv/bin/python scripts/retune_drops.py --retunes 20 --dwell 1
```

The script listens on seven candidate channels for one second each, picks the two busiest
(2.4 GHz channel 11 and 5 GHz channel 44 in this environment), then alternates between them,
draining frames for the dwell and recording what the two retune commands discard.

| Run | Hops | Frames per dwell | Frames lost per hop | Stale MCU events | Channel switch | Sniffer config |
|---|---|---|---|---|---|---|
| 1 | 10 | 188 to 502 in 2 s | min 0, median 1, max 8, total 14 | 0 | 7.5 to 9.4 ms | 6.1 to 7.1 ms |
| 2 | 20 | 88 to 286 in 1 s | min 0, median 1, max 4, total 21 | 0 | median 9.1 ms | median 6.7 ms |

A retune therefore costs about 16 ms of MCU round trips and, while the caller keeps reading, loses
a median of one frame. This is the cost of hopping while draining; it does not describe what is
lost when a caller stops reading for longer, and it was measured on ambient traffic, not a
controlled load.

## Channel width and 6 GHz access points: 2026-09-02

Same test bed as the retune measurement. `scripts/width_probe.py` configured the sniffer at
several widths and counted decoded frames for six to ten seconds each, with a Wi-Fi 7 phone running a
speed test on the 6 GHz network during the 6 GHz captures.

| Band:channel | Center | Width | Frames | Of which data |
|---|---|---|---|---|
| 5GHz:132 | 132 | 20 MHz | 808 | 419 |
| 5GHz:132 | 138 | 80 MHz | 1007 | 241 data plus 66 BlockAck; 146 frames decoded at 80 MHz |
| 6GHz:53 | 53 | 20 MHz | 470 | 0 (beacons and FILS discovery action frames only) |
| 6GHz:53 | 55 | 80 MHz | 586 | 0 |
| 6GHz:53 | 47 | 160 MHz | 0 | 0 |

The beacons on 6 GHz channels 53 and 101 carry an HE Operation element whose 6 GHz Operation
Information says width 160 with center channel fields 55 and 47 (53) and 103 and 111 (101),
so the client's data frames were 160 MHz transmissions and outside what this adapter decodes.
The 5 GHz beacons carry VHT Operation width 1 with center 138, an 80 MHz block, and 80 MHz
capture worked. The 160 MHz configuration is recorded in [NEGATIVE_RESULTS.md](../NEGATIVE_RESULTS.md).

### Single-radio roaming observation, same day

With the radio locked to the channel of a 160 MHz 6 GHz AP for 120 seconds, a Wi-Fi 7 client
held at -79 dBm on that AP exchanged 443 data frames with it and received no BTM request,
deauthentication, or disassociation. The network's own 802.11v suggestion threshold, checked out of
band, was set below the client's signal level, so no suggestion was due. Over the following ten
minutes the same client, which the network's management view showed as an MLO client with three
links, moved through five APs on three bands and logged two authentication failures during
roams; a radio locked to any one channel observed none of those transitions. Two consequences:
roaming evidence needs either a second radio on the target channel (R16) or the network's own
management log beside the capture, and an MLO client must be tracked by its per-link addresses, not only
the MLD address a management view displays (R15).

## Release smoke for 0.1.0: 2026-09-02

The release commit was run through the full redacted smoke on the reference adapter and host:

```bash
./.venv/bin/python scripts/hardware_smoke.py --plan all --dwell 0.75
```

Result `pass` on all 43 channels with 1,244 decoded frames: 377 on 2.4 GHz, 683 on 5 GHz, 184 on
6 GHz. The aggregate-only result is [hardware-smoke-reference.json](hardware-smoke-reference.json),
which replaces the 2026-08-31 reference file; that earlier run's numbers remain above.

## Attached-hardware validation: Pure C driver: 2026-09-02

### Test bed

| Item | Value |
|---|---|
| Host | Apple M1 Max |
| OS | macOS 26.6, build 25G72 |
| Compiler | Apple clang 17.0.0 (clang-1700.0.13.5), C11, `-Wall -Wextra -O2` |
| USB device | MediaTek `Wireless_Device`, `0e8d:7961`, USB SuperSpeed (speed code 4) |
| Driver access | Native IOKit (`IOUSBDeviceInterface500`, `IOUSBInterfaceInterface500`), unprivileged user |
| RAM firmware SHA-256 | `b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9` |
| Patch firmware SHA-256 | `a276c06c2b772adb50b86639d33c82824ff4c21d617feb78caea74c040b873f6` |

No Python runtime, PyUSB, or libusb was linked or invoked.

### Passive tri-band sweep (`--plan all`)

```bash
./c/mt7921_smoke --plan all --dwell 0.5
```

- **Criterion**: Exit code 0 (`status: pass`), all 43 channels scanned, zero non-timeout USB errors, zero undecoded transfers.
- **Result**: `status: "pass"` across 43 channels (2.4 GHz, 5 GHz, and 6 GHz PSC) with 1,333 decoded frames: 282 on 2.4 GHz, 893 on 5 GHz, and 158 on 6 GHz. Zero undecoded transfers, zero non-timeout USB errors.

### On-die thermal telemetry

```bash
./c/mt7921_smoke --temp
```

- **Criterion**: Send `MCU_EXT_CMD_THERMAL_CTRL` (`0x2c`), read signed temperature in °C, check non-negative and within operating limits (20°C–80°C), exit 0.
- **Result**: Output `Die temperature: 32 C` (exit code 0).

### Raw EFUSE block query and sensitive data masking

```bash
./c/mt7921_smoke --read-efuse 0x000
```

- **Criterion**: Send `MCU_EXT_CMD_EFUSE_ACCESS` (`0x01`) query for block `0x000`, confirm chip ID `0x7961` (`61 79`) in bytes 0–1, `valid=1`, and ensure MAC address bytes (offsets 0x004..0x009) are masked with `xx` unless `--acknowledge-sensitive-raw-efuse` is passed.
- **Result**: Output `EFUSE [0x000] (valid=0x00000001): 61 79 00 00 xx xx xx xx xx xx 00 00 00 00 00 00 [MAC redacted; pass --acknowledge-sensitive-raw-efuse to display]` (exit code 0).

### Rate-limited 2.4 GHz probe request submission to USB

```bash
./c/mt7921_smoke --plan quick --dwell 0.5 --inject 3 --acknowledge-experimental-transmit
```

- **Criterion**: Submit exactly 3 wildcard Probe Requests on 2.4 GHz channel 1 at 50 ms spacing with 1 Mbps CCK rate. Fail closed and submit 0 frames on 5 GHz and 6 GHz. Bulk writes accepted by USB endpoint without timeout or I/O errors, chip alive after submission, exit 0 (`status: pass`).
- **Result**: 3 frames submitted to USB bulk OUT endpoint on 2.4 GHz, 0 on 5 GHz and 6 GHz; bulk writes accepted; device responded to post-submission liveness check; exit code 0 (`status: pass`).
*(Note: Without firmware TX status reporting enabled or an independent RF receiver recording over-the-air packets, bulk-write acceptance establishes successful host-to-device USB delivery and USB transfer completion, but does not prove over-the-air RF radiation.)*

### Radiotap PCAP export (Live Hardware Legacy/HT and Synthetic VHT/HE Writer)

#### 1. Live hardware capture (Legacy and HT rates)

```bash
# Capture live frames across bands
./c/mt7921_smoke --plan quick --dwell 0.5 --pcap /tmp/live_test.pcap
tcpdump -r /tmp/live_test.pcap -c 2
tshark -r /tmp/live_test.pcap -Y "radiotap.mcs" -O radiotap
```

- **Criterion**: Export PCAP with link type `IEEE802_11_RADIO` (127), containing valid Radiotap headers with rate (CCK/OFDM) and MCS (HT) data words matching upstream definitions without malformed errors in `tcpdump` or Wireshark.
- **Result**:
  - Live legacy and HT frames captured over the air and verified via `tcpdump` and `tshark`:
    ```text
    $ tcpdump -r /tmp/live_test.pcap -c 2
    reading from file /tmp/live_test.pcap, link-type IEEE802_11_RADIO (802.11 plus radiotap header)
    20:15:42.673550 1.0 Mb/s 2412 MHz 11b -39dBm signal Data IV:ffc7 Pad 20 KeyID 1
    20:15:42.673653 1.0 Mb/s 2412 MHz 11b -69dBm signal Beacon ([REDACTED_SSID]) [5.5* 11.0* 1.0* 2.0* 6.0 12.0 24.0 48.0 Mbit]
    ```
    ```text
    $ tshark -r /tmp/live_test.pcap -Y "radiotap.mcs" -O radiotap
    MCS information
        Known MCS information: 0x07, Bandwidth, MCS index, Guard interval
        Bandwidth: 20 MHz (0)
        Guard interval: short (1)
        MCS index: 3
    [Data Rate: 28.9 Mb/s]
    ```

#### 2. Synthetic writer validation (VHT, HE-SU, HE-SU+STBC, HE-MU, and HE-ER-SU)

```bash
# Generate reproducible synthetic test PCAP with --keep-pcap
./c/test_rxd --keep-pcap
tshark -r /tmp/test_c_writer.pcap -O radiotap
```

- **Criterion**: Synthetic PCAP writer creates records with VHT (80 MHz MCS 9), HE-SU (160 MHz MCS 11), HE-SU STBC (80 MHz MCS 7 NSTS 2), HE-MU (52-tone RU offset 3), HE-ER-SU (106-tone RU), and HE-ER-SU 40 MHz full-bandwidth without errors in `tshark`.
- **Result**: `tshark` dissects all synthetic VHT and HE records cleanly:
    ```text
    $ tshark -r /tmp/test_c_writer.pcap -O radiotap
    # Frame 3: VHT (80 MHz, MCS 9, NSS 2, SGI)
    VHT information
        Known VHT information: 0x0045, STBC, Guard interval, Bandwidth
        STBC: Off
        Guard interval: short (1)
        Bandwidth: 80 MHz (4)
        User 0: MCS 9, Spatial streams 0: 2, Data Rate: 866.6 Mb/s

    # Frame 5: HE-SU with STBC (80 MHz, MCS 7, NSS 1, NSTS 2)
    HE information
        HE Data 3: STBC known, STBC: 0x1
        HE Data 5: 80 MHz, GI: 1.6us
        HE Data 6: 2 space-time streams (0x2)

    # Frame 6: HE-MU on 52-tone RU (RU offset 3, MCS 5)
    HE information
        HE Data 1: PPDU Format: HE_MU (0x2)
        HE Data 2: RU allocation offset: 0x03, RU allocation offset known: Known
        HE Data 3: data MCS: 0x5
        HE Data 5: data Bandwidth/RU allocation: 52-tone RU (0x5)
        HE Data 6: 1 space-time stream (0x1)

    # Frame 7: HE-ER-SU on 106-tone RU (MCS 0)
    HE information
        HE Data 1: PPDU Format: HE_EXT_SU (0x1)
        HE Data 5: data Bandwidth/RU allocation: 106-tone RU (0x6)
        HE Data 6: 1 space-time stream (0x1)

    # Frame 8: HE-ER-SU 40 MHz full-bandwidth (MCS 0, 40 MHz)
    HE information
        HE Data 1: PPDU Format: HE_EXT_SU (0x1)
        HE Data 5: data Bandwidth/RU allocation: 40 (0x1)
        HE Data 6: 1 space-time stream (0x1)
    ```

## MT7925U descriptor discovery and chip identity: 2026-09-03

Day one with a Netgear Nighthawk A9000, before any firmware was loaded. Host: Apple M4
MacBook Pro, macOS 26.6 (Darwin 25.6.0), Python 3.14.7, PyUSB with Homebrew libusb 1.0.30,
unprivileged user. The MT7921 reference adapter was not attached.

```bash
./.venv/bin/python scripts/usb_descriptors.py --chip-id
```

- **Criterion**: the device enumerates as a supported USB id, `select_wifi_interface` resolves
  exactly one interface with class `ff/ff/ff` and at least 2 bulk IN plus 6 bulk OUT endpoints,
  and `MT_HW_CHIPID` reads a chip id the firmware table knows.
- **Result**: `0846:9072`, USB 3.2 (`bcdUSB 0x0320`), one configuration, **one interface**
  (number 0, class `ff/ff/ff`, 9 endpoints: bulk `0x84 0x85 0x08 0x04 0x05 0x06 0x07 0x09` in
  that order, then interrupt `0x86`). Positional assignment gives `EP_IN_PKT_RX=0x84`,
  `EP_IN_CMD_RESP=0x85`, `EP_OUT_INBAND_CMD=0x08`, `EP_OUT_AC_BE=0x04`, the same roles the
  MT7921 reference adapter exposes on its interface 3. `chip_id=0x7925`, `MT_HW_REV=0x00008a00`,
  `MT_CONN_ON_MISC=0` (no firmware running). The device has no Bluetooth interface, and macOS
  had matched no driver to it (`ioreg`: `!matched`).

### Firmware boot, same day

Same host and adapter. Firmware: `mt7925/WIFI_MT7925_PATCH_MCU_1_1_hdr.bin`
`8eb46014d2a6b4124472eee7476d995008a6f40b1daffef87eb42f30d98699e1`,
`mt7925/WIFI_RAM_CODE_MT7925_1_1.bin`
`23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`, linux-firmware
`e981caea6ed33c48d25b7dbf473327dbd01df163`.

```bash
./.venv/bin/python scripts/firmware_boot.py
```

- **Criterion**: `bringup()` through `Mt7925uDevice` (connac3 WFSYS descriptor, 44-byte MCU
  reply header, TXD without LONG_FORMAT, UNI CHIP_CONFIG capability query, UNI EFUSE_CTRL
  buffer mode) ends with `MT_CONN_ON_MISC` reporting `FW_N9_RDY`, the capability query
  answered with a parseable element list, and the efuse push acknowledged; exit 0.
- **Result**: `status=pass`, exit 0, in 1.5 s. Patch `20260813113015a` (2 sections), RAM
  `20260813113118` (5 regions, one `NON_DL`), `MT_CONN_ON_MISC=0x00000003`. Capability
  elements reported: TX_RESOURCE, SINGLE_SKU, CSUM_OFFLOAD, HW_VER, SW_VER, MAC_ADDR, PHY, MAC,
  FRAME_BUF, BEAM_FORM, LOCATION, MUMIMO, BUFFER_MODE_INFO, HW_ADIE_VERSION, 6G, CHIP_CAP,
  EML_CAP, and unnamed tags `0x15 0x1b 0x1d 0x28 0x38 0x39 0x48`. PHY capability: `nss=2`
  (antenna mask `0x3`), `max_bw=4`, HT/VHT/HE/EHT all 1, `hw_path=0x0f`, DBDC 1. Repeated
  twice with the same result; the second run started from a chip already reporting
  `FW_N9_RDY` and took the WFSYS reset path.

### Monitor mode and receive on three bands, same day

Same host, adapter, and firmware. After `bringup()`: UNI `BAND_CONFIG` RX filter
(`fif = 0x80000064`), UNI `SNIFFER` enable, then the sniffer CONFIG TLV as the only channel
command (`Mt7925uDevice.tune`). Transfers are counted by the RXD packet type in the first
descriptor word, which is the same on both chip generations, so this run needs no connac3
decoder.

```bash
./.venv/bin/python scripts/firmware_boot.py --rx 5 --channel 2.4GHz:6
./.venv/bin/python scripts/firmware_boot.py --rx 5 --channel 5GHz:36
./.venv/bin/python scripts/firmware_boot.py --rx 5 --channel 6GHz:53
```

- **Criterion**: on each band at least one bulk transfer of packet type `NORMAL` arrives
  within 5 s, with zero USB errors; a 6 GHz result proves the UNI efuse push worked.
- **Result**:

  | Channel | `NORMAL` transfers in 5 s | Other types | USB timeouts / errors | Transfer bytes min / median / max |
  |---|---|---|---|---|
  | 2.4 GHz ch 6 | 150 | 0 | 0 / 0 | 492 / 492 / 492 |
  | 5 GHz ch 36 | 261 | 0 | 0 / 0 | 284 / 428 / 460 |
  | 6 GHz ch 53 (PSC) | 495 | 0 | 0 / 0 | 252 / 252 / 604 |

  Each run started from a chip already reporting `FW_N9_RDY` and took the WFSYS reset path.

### connac3 decode, radiotap pcap, and width configuration, same day

Same host, adapter, and firmware. `rxd_connac3.decode` is selected by the device class.

```bash
./.venv/bin/python examples/sniff_to_pcap.py 53 6 out.pcap 6GHz
tshark -r out.pcap -q -z io,phs
tshark -r out.pcap -Y "_ws.malformed || _ws.expert.severity==error" | wc -l
./.venv/bin/python scripts/width_probe.py 6GHz:53 6GHz:53:55:80 6GHz:53:47:160 --seconds 6
```

- **Criterion**: every transfer decodes to a frame, tshark dissects every frame as
  `radiotap/wlan_radio/wlan` with zero malformed packets, radiotap carries a rate for
  legacy-rate frames, and the sniffer accepts 20, 80, and 160 MHz configurations on 6 GHz
  without going silent.
- **Result**: 607 transfers, 607 frames written, 607 dissected (122 Beacon, 485 Action),
  **0 malformed**; radiotap `datarate` 6 Mbps and `wlan_radio.phy` OFDM on all 607, RSSI
  populated from P-RXV word 3. Width probe, 6 s each: 20 MHz 585 frames, 80 MHz (center 55)
  587, **160 MHz (center 47) 587**, all decoded at 20 MHz because only management traffic
  from two 160 MHz APs was on air (beacons advertise `he6 160 ccfs0 55 ccfs1 47`). The MT7921
  returned zero transfers under the same 160 MHz configuration
  ([NEGATIVE_RESULTS.md](../NEGATIVE_RESULTS.md)); the MT7925 keeps receiving.

### 160 MHz capture with a controlled transmitter, same day

Same host, adapter, and firmware. The host's built-in Wi-Fi (Broadcom `14e4:4388`, 802.11ax)
was joined to a 6 GHz BSS on channel 53 operating at 160 MHz (its link reported
`Channel: 53 (6GHz, 160MHz)`, transmit rate 2401 Mb/s, MCS 11) and generated traffic bound to
that interface (an HTTPS download loop and a 1200-byte ping at 50 per second to the gateway)
while the A9000 captured the same channel configured for 160 MHz (control 53, center 47). The
capture host's wired link carried everything else. Counts only; the SSID and addresses stay
out of this repository.

```bash
./.venv/bin/python scripts/width_probe.py 6GHz:53:47:160 --seconds 10
./.venv/bin/python examples/sniff_to_pcap.py 53 10 out.pcap 6GHz --width 160 --center 47
tshark -r out.pcap -Y "radiotap.he.data_5.data_bw_ru_allocation == 3 && wlan.ta == <mac>" | wc -l
```

- **Criterion**: frames decoded with a PHY width of 160 MHz > 0; HE data frames at 160 MHz
  whose transmitter address is the built-in Wi-Fi's MAC > 0; tshark dissects the pcap with
  zero malformed frames.
- **Result**: width probe, 10 s: **3337 frames, 1736 decoded at 160 MHz**, 513 at 80, 1066 at
  20, 22 at 40; kinds BlockAck 894, Action 781, RTS 565, CTS 510, Beacon 196, QoS Data 147,
  VHT-NDPA 73, ActionNoAck 73, Data 65, ACK 17, Null 15; 0 USB errors. pcap, 10 s: 3764
  transfers, 3764 frames, **0 malformed**; **193 HE frames at 160 MHz (radiotap HE bandwidth
  code 3), all 193 transmitted by the built-in Wi-Fi's MAC**, all QoS Data at HE MCS 8 (76)
  and MCS 9 (117), radiotap data rates 1633 to 1922 Mb/s; 1186 frames in total from that MAC
  (RTS 458, BlockAck 449, QoS Data 193, others 86). Frames addressed to that MAC were CTS,
  BlockAck, and control only: the AP's downlink data to it was not decoded, consistent with
  beamformed downlink being outside what a third radio can receive
  ([README](../README.md#known-limits-and-non-goals)).

### Full passive sweep and retune drops, same day

```bash
./.venv/bin/python scripts/hardware_smoke.py --plan all
./.venv/bin/python scripts/retune_drops.py --retunes 20 --dwell 1
```

- **Criterion**: `hardware_smoke` exits 0 with decoded frames on every band and no
  undecoded transfers; `retune_drops` completes 20 retunes with counts only.
- **Result**: `status=pass`, exit 0, 48.2 s for 43 channels: 991 transfers, 991 decoded
  frames, 0 undecoded, 0 USB errors, 67 USB timeouts (quiet channels). 2.4 GHz 3/3 channels
  with frames (233: 129 management, 56 data, 48 control); 5 GHz 16/25 (527: 327 / 22 / 178);
  6 GHz 4/15 PSCs (231: 227 / 4 / 0). Redacted output in
  [hardware-smoke-reference-mt7925.json](hardware-smoke-reference-mt7925.json). Retune drops on
  the two busiest 2.4 GHz channels, 20 retunes: median 1 frame lost per retune, min 0, max 3,
  18 total, at 127 to 296 frames per 1 s dwell; median retune 5.7 ms (one MCU command on this
  chip); 0 USB errors.

The MT7921 reference adapter was not attached on 2026-09-03; nothing above reruns its
evidence, and the MT7921 on-wire framing is held fixed by `tests/golden_mt7921_frames.json`.

## Pure C driver on the MT7925U: 2026-09-03

Same host, adapter, and firmware as the Python MT7925U sections above. The C driver selects the
chip from the USB id, resolves the Wi-Fi interface and endpoint roles from the descriptors, and
uses the MT7925 MCU geometry, UNI commands, and connac3 decoder (`c/mt7921_chip.c`,
`c/mt7921_rxd_connac3.c`).

```bash
make -C c clean all test
./c/mt7921_smoke --plan quick --dwell 1.0 --fw firmware
./c/mt7921_smoke --plan all --dwell 0.75 --fw firmware --pcap out.pcap
tshark -r out.pcap -q -z io,phs
tshark -r out.pcap -Y "_ws.malformed || _ws.expert.severity==error" -T fields -e wlan.fc.type_subtype -e frame.len | sort | uniq -c
```

- **Criterion**: the offline suite passes including the connac3, profile, and MT7925 framing
  tests; the smoke tool opens the A9000 by its USB id, reports `chip=mt7925` and interface 0,
  boots the MT7925 firmware, and exits 0 with decoded frames on every band and no undecoded
  transfers; the pcap dissects as `radiotap/wlan_radio/wlan`.
- **Result**: 12 offline tests pass. `--plan quick`: pass, 397 transfers, 397 decoded, 0 undecoded,
  0 USB errors, `device.chip=mt7925`, `usb_id=0846:9072`, `wifi_interface=0`, `usb_speed_code=3`
  (IOKit's SuperSpeed code; the Python tool reports libusb's 4 for the same link). `--plan all`:
  **pass**, 48.8 s, 1825 transfers, 1825 decoded, 0 undecoded, 0 USB errors, 69 timeouts (quiet
  channels); 2.4 GHz 3/3 channels (519 frames), 5 GHz 17/25 (1062), 6 GHz 5/15 (244). pcap:
  1825 frames dissected; tshark 4.6.8 flags 37, none with the bad-FCS flag, and both kinds are
  frame content rather than capture defects:
  - 22 are 19-byte VHT NDP Announcements (FC `0x0054`, RA, TA, sounding token, one 2-byte STA
    Info), complete per 802.11ac. Their transmitters increment the whole token byte, so the low
    two bits, which Wireshark decodes as the 802.11ax HE / 802.11az Ranging variant, take every
    value; for variants 1 to 3 the dissector expects 4-byte STA Info and reports "Malformed".
    A Python-driver capture of 5 GHz channel 56 shows the same population: 300 NDPAs of 34 bytes
    from two transmitters, variant 0 clean (78), variants 1 to 3 flagged (172), plus 2 genuine
    36-byte HE NDPAs, clean.
  - 15 are 490/493-byte beacons from one AP on channel 112 whose Supported Rates element has
    length 0 ("Tag length 0 too short").
  Frames carry no FCS: on 418 beacon and data frames from both pcaps the trailing four bytes
  never equal the CRC-32 of the rest, so the radiotap "FCS at end" flag is correctly absent.

The MT7921 reference adapter was not attached; the C driver's MT7921 path is covered by the
unchanged offline tests (connac2 decode, TXWI, pcap writer) and by the MT7921 profile tests.

## EHT radiotap on the MT7925U: 2026-09-03

Same host, adapter, and firmware. Both pcap writers now emit the radiotap TLV section (present
bit 28) with a U-SIG item (type 33: bandwidth) and an EHT item (type 34: GI, RU/MRU size, one
user's MCS, NSS, coding) for EHT-SU/TRIG/MU frames, laid out per radiotap.org/fields/{TLV,U-SIG,EHT}.
An 802.11be client was active on the 160 MHz 6 GHz BSS during the runs.

```bash
./.venv/bin/python -m pytest -q tests/test_pcap.py      # includes a tshark round trip of a synthetic EHT pcap
./.venv/bin/python examples/sniff_to_pcap.py 53 30 out.pcap 6GHz --width 160 --center 47
./c/mt7921_smoke --channel 6GHz:53:47:160 --dwell 10 --fw firmware --pcap c.pcap
tshark -r out.pcap -Y "wlan_radio.phy == 12" -T fields -e wlan_radio.11be.mcs -e wlan_radio.11be.nsts -e wlan_radio.data_rate -e radiotap.u_sig.common.bw
```

- **Criterion**: tshark (4.6.8) dissects every EHT frame as `wlan_radio.phy == 12` (802.11be)
  with MCS, NSTS, bandwidth, and a data rate, and flags no frame malformed.
- **Result**: Python writer, 30 s: 8236 frames, **973 EHT** (7251 OFDM, 12 HE), all QoS Data or
  Action; MCS 0 to 5, NSTS 1 or 2, U-SIG bandwidth code 3 (160 MHz), data rates 68.1 to 864.8 Mb/s
  (for example MCS 4, 1 stream: 432.4; MCS 3, 2 streams: 576.4); **0 malformed of 8236**. C writer,
  10 s: 2774 frames, **336 EHT**, MCS 2 to 5, NSTS 1 or 2, bandwidth 160, **0 malformed of 2774**.
  Offline, the synthetic EHT pcap (MCS 11, 2 streams, 80 MHz, 1.6 µs GI) reads back as phy 12,
  MCS 11, NSTS 2, 1134.x Mb/s, bandwidth code 2.

The MT7921 cannot receive EHT PPDUs wider than its configuration and no MT7921 was attached; the
writers' HT/VHT/HE output is unchanged and covered by the existing offline tests.

## Previously observed, not rerun in the current validation

- control-frame receive;
- per-frame PHY width/MCS/rate/retry reporting across all modes;
- hardware good-MPDU and FCS-error counters;
- 40 and 80 MHz capture paths; and
- low-rate Probe Request injection: 60 Probe Requests at 50 ms spacing on one 2.4 GHz channel,
  the chip alive after every 20, 677 directed Probe Responses received from 6 BSSIDs. Sustained
  or high-rate transmit was not attempted, then or since.

These observations motivated code and documentation, but they should not be interpreted
as a current release qualification.

## Explicitly untested or unsupported

- Intel Macs, non-26.6 macOS hardware runs, and non-Apple operating systems;
- capture on USB ids other than `0e8d:7961` and `0846:9072` (the A8500 `0846:9050` and the
  MediaTek `0e8d:7925` ids are in the table but no such device has been attached; the MT7927
  `0e8d:6639` is not in the table at all);
- 320 MHz (no supported part), 160 MHz on the MT7921U, simultaneous channels, multiple
  adapters in one process, MT7922, PCIe, and SDIO;
- association, client mode, AP mode, routing, CoreWLAN, and a BSD network interface;
- Bluetooth firmware or coexistence;
- decryption and complete capture of beamformed downlink or A-MSDU inner frames;
- working noise-floor and CCA-busy measurements;
- suspend/resume, sleep/wake, hot-unplug recovery, and long-duration soak behavior;
- sustained or high-rate injection, injection across bands/widths, TX power, TX feedback,
  and regulatory-domain enforcement; and
- automatic recovery from a device that stops responding.

Do not turn an item in this section into a positive claim until a dated result, exact test
bed, command, acceptance criterion, and failure disclosure are added here.
