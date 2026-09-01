# mt7921u-macos: MT7921AU Wi-Fi 6E monitor mode on macOS

[![CI](https://github.com/Network-Weather/mt7921u-macos/actions/workflows/ci.yml/badge.svg)](https://github.com/Network-Weather/mt7921u-macos/actions/workflows/ci.yml)
[![License: BSD-3-Clause-Clear](https://img.shields.io/badge/license-BSD--3--Clause--Clear-blue.svg)](LICENSE)

A small, readable Python userspace monitor-mode driver for the MediaTek MT7921AU / MT7921U
(`MT7961`, USB `0e8d:7961`) on macOS. It talks directly to an external adapter such as the
ALFA AWUS036AXML through libusb—no kernel extension, DriverKit extension, root, or virtual
machine—and writes 2.4, 5, and **6 GHz** 802.11 traffic to radiotap pcap for Wireshark.

The practical use case is giving a Mac whose built-in radio cannot receive 6 GHz a passive
Wi-Fi 6E capture instrument. The current reference host is an M1 Max; newer Macs may have
different built-in capabilities.

> **Status: research-grade passive capture, not a network driver.** The receive path is
> working on the exact hardware below. Injection is experimental and was not part of the
> current release validation. Read [Testing and evidence](docs/TESTING.md),
> [Known limits](#known-limits-and-non-goals), [engineering quality](docs/QUALITY.md), and
> [ROADMAP.md](ROADMAP.md) before relying on it.

**Lineage:** the driver logic is transcribed from the BSD-3-Clause-Clear
[`openwrt/mt76`](https://github.com/openwrt/mt76) MT7921 path, and it boots MediaTek blobs
fetched from [`linux-firmware`](https://gitlab.com/kernel-firmware/linux-firmware). The
closest peer userspace implementations are [`wifikit`](https://github.com/RLabs-Inc/wifikit)
on macOS and [`wifit3`](https://github.com/derv82/wifit3) across Windows, Linux, and macOS. See
[Lineage and related work](RELATED_WORK.md) for exact relationships, pinned revisions, and
what was—and was not—derived from each project.

Potential downstream consumers and the boundary each would need are documented in
[Integration opportunities](docs/INTEGRATIONS.md); this is a technical fit assessment, not a
claim that any named project endorses or plans to adopt this code.

## Why userspace works at all

Passive monitor mode does not need a network interface. There is no association, no
routing, no handing packets to the network stack. It needs exactly three things: upload
firmware, set a channel with an MCU command, and pull raw frames off a bulk endpoint into
radiotap. That is a plain userspace USB job, and on macOS nothing is holding the device.

This project does not try to expose a CoreWLAN or BSD network interface. For passive
capture, libusb access to the otherwise-unclaimed device is enough.

## Requirements

- An MT7921AU **USB device with the exact ID and composite layout** `0e8d:7961`, for
  example the tested ALFA AWUS036AXML. The code currently hard-codes Wi-Fi interface 3;
  rebadged IDs and single-interface MT7921AU devices are not supported yet.
- macOS on Apple Silicon. Hardware-validated on an M1 Max running macOS 26.6. Intel macOS
  and other macOS releases are plausible but **not hardware-tested by this project**.
- Homebrew `libusb`: `brew install libusb`.
- Python 3.10+.
- **No root required.** macOS leaves the adapter unclaimed, so a normal user process can
  take the interface.

## Setup

```bash
bash setup.sh                 # creates .venv (+pyusb) and fetches firmware into ./firmware
./.venv/bin/python examples/scan.py
```

`setup.sh` is idempotent, verifies pinned firmware checksums, and puts everything in
gitignored, repo-relative locations. The
MediaTek firmware blobs are **not** part of this repository (they are licensed binaries);
`setup.sh` fetches them from `linux-firmware`. See [NOTICE.md](NOTICE.md) for the license
terms and the one blob you must not fetch.

## Usage

```bash
./.venv/bin/python examples/scan.py                              # tri-band BSSID census
./.venv/bin/python examples/scan.py 6                            # 6 GHz PSCs only
./.venv/bin/python examples/sniff_to_pcap.py 53 8 out.pcap 6GHz # 6 GHz radiotap pcap
./.venv/bin/python scripts/hardware_smoke.py --plan all          # redacted passive release check
```

`scan.py` intentionally prints observed SSIDs and BSSIDs; treat its terminal output as
sensitive. `hardware_smoke.py` reports only aggregate counts, software/device capability,
and firmware hashes. It never emits captured identifiers or payloads.

The library is two flat modules:

| File | What it does |
|---|---|
| `mt7921u.py` | The driver: USB vendor transfers, register I/O, MCU command framing, firmware download, channel and sniffer setup, receive, and (see caveat) injection |
| `rxd.py` | RX descriptor decode and 802.11 frame parsing |

## What the driver source does not tell you

Porting register maps from `mt76` is mechanical. Five things are not written down anywhere
and had to be measured. If you are attempting this port on any OS, these are the walls you
will hit:

1. **MCU responses move endpoints.** They arrive on `0x85` until `USB_RXEVT_EP4_EN` is set,
   then on `0x84`. The driver sets it, so responses land on `0x84`.
2. **There is no RX header to skip.** `mt7921u` keeps zero head room; `rxd[0]`'s low half
   *is* the DMA length word. Read the descriptor straight off the transfer.
3. **The patch semaphore success value is 2, not 1.** The enum starts at
   `PATCH_NOT_DL_SEM_FAIL`, so an off-by-one here reads as a failed firmware download.
4. **Opening the MAC filter is necessary but not sufficient.** With the receive filter
   fully open (`MT_WF_RFCR = 0`, dropping nothing) you still get thousands of QoS data
   frames and *zero* beacons: the firmware consumes beacons itself until
   `MCU_UNI_CMD(SNIFFER)` puts it in sniffer mode, which needs the UNI command TXD rather
   than the ordinary one. That single command is the difference between 0 and 684 beacons.
5. **Bands above 2.4 GHz stay silent until the efuse is pushed.** A channel with a
   known-active AP returns zero transfers until `MCU_EXT_CMD(EFUSE_BUFFER_MODE)` hands the
   firmware its calibration data. That one call is what makes 5 GHz and 6 GHz work.
   `MT_SWDEF_MODE` must also be written *before* the firmware download.

## Endpoint map

`mt76u_set_endpoints` assigns endpoints positionally over the interface descriptor. On
interface 3 (the Wi-Fi function; interfaces 0 to 2 are Bluetooth):

| Driver constant | Endpoint | Use |
|---|---|---|
| `MT_EP_IN_PKT_RX` | `0x84` | Received 802.11 frames, and MCU responses once EP4 routing is on |
| `MT_EP_IN_CMD_RESP` | `0x85` | MCU responses before that |
| `MT_EP_OUT_INBAND_CMD` | `0x08` | MCU commands and firmware download |
| `MT_EP_OUT_AC_*`, `HCCA` | `0x04`-`0x07`, `0x09` | Transmit queues |

## Capability and evidence matrix

“Current pass” means rerun on the attached `0e8d:7961` device on 2026-08-31. “Previously
observed” is deliberately weaker: the code has done it on hardware, but it was not proved
again in the publication run. Exact commands and results are in [docs/TESTING.md](docs/TESTING.md).

| Capability | Evidence |
|---|---|
| Claim the device from userspace without root | Current pass |
| Upload and boot checksum-pinned firmware | Current pass |
| Retune and receive on 2.4 / 5 / 6 GHz | Current pass; 24 / 37 / 6 BSSIDs in one sweep |
| Passive management and data frame capture | Current pass |
| Radiotap pcap readable by Wireshark | Current pass; 353 6 GHz packets, 0 malformed |
| Control frame receive | Previously observed; absent from the five-second validation sample |
| Per-frame PHY rate, width, MCS, RSSI, retry bit | Previously observed; offline calculations tested |
| 802.11k/v/r, PMF, EasyMesh, and 802.11s parsing | Synthetic offline tests; opportunistic live coverage |
| Frame injection | Experimental, previously observed only at low rate; **not current-pass tested** |
| 40 / 80 MHz capture | Code paths exist; not covered by the current release validation |
| 160 / 320 MHz capture | Not supported for this part |
| Simultaneous multi-channel capture | Not possible with one radio |
| Hardware CCA busy / noise floor | Not working; reads zero on the reference device |

## Injection: read this first

The transmit path (`inject`, `_build_txwi`, `build_probe_request`, and
`examples/inject_demo.py`) is **experimental, rate-limited, and outside the current
end-to-end validation.** Sustained transmit can panic the MCU and require a physical
replug. The code does not implement regulatory-domain enforcement. Transmit only on
frequencies, power levels, and systems you are legally permitted to use. This repository
is a diagnostics and driver-research tool, not an attack toolkit. The demo refuses to run
unless `--acknowledge-experimental-transmit` is explicitly supplied.

## Known limits and non-goals

- This is **not** a macOS Wi-Fi network interface. It cannot associate, provide Internet
  access, act as an AP, route packets, or appear in CoreWLAN, Network Settings, `tcpdump`,
  or Wireshark's interface list.
- This is not a complete Wireshark extcap integration. Today an example writes pcap to a
  file; open that file in Wireshark after or during capture.
- Only USB `0e8d:7961` with Wi-Fi on interface 3 is matched. Netgear/Comfast/rebadged IDs,
  the Panda single-interface layout, MT7922, PCIe, SDIO, and Bluetooth are not supported.
- One radio means channel hopping has unavoidable blind intervals. It cannot capture more
  than one channel simultaneously, and the current examples use 20 MHz channels.
- It does not decrypt protected traffic, reconstruct TCP streams, split A-MSDU inner
  frames, or guarantee complete beamformed downlink capture.
- It is not a spectrum analyzer. Frame counts, RSSI, and FCS errors cannot identify
  non-Wi-Fi interference; hardware CCA busy and noise-floor readings are not working.
- PHY rate is metadata, not throughput. Airtime estimates are approximate and a
  channel-local partial view.
- There is no tested suspend/resume, hot-unplug recovery, long-duration soak test,
  multi-adapter support, or automatic MCU panic recovery.
- Firmware is re-uploaded for every process. The MediaTek blobs are fetched separately
  and are never distributed in this repository.

## Lineage, peers, and novelty

Not as a category. [wifikit](https://github.com/RLabs-Inc/wifikit) is a broader native
macOS userspace toolkit in Rust with an MT7921AU backend, and
[wifit3](https://github.com/derv82/wifit3) provides a broader Python userspace auditor for
Windows, Linux, and macOS with many chipset drivers, including MT7921AU.
The Linux [mt76](https://github.com/openwrt/mt76) driver is the upstream technical basis
for all of this project's register and descriptor work, while
[linux-firmware](https://gitlab.com/kernel-firmware/linux-firmware) supplies the required
MediaTek runtime binaries. [RELATED_WORK.md](RELATED_WORK.md) records the exact relationship
to both foundational projects and distinguishes them from peer work.

What is distinctive here is the narrow form: about 2,800 lines of readable Python focused
on passive capture, with the measured firmware/endpoint/efuse bring-up details exposed as
a compact reference implementation. That can be useful for driver research even when a
larger end-user tool is the better operational choice.

In short: choose this repository for a minimal readable reference and its current macOS
6 GHz evidence; choose wifikit for a broader native macOS application; choose wifit3 for
cross-platform hardware breadth and active audit workflows; choose mt76/Linux for an actual
managed Wi-Fi interface and mature kernel integration. The detailed strong/weak comparison
and its evidence caveats are in [RELATED_WORK.md](RELATED_WORK.md#capability-comparison).

## Testing

The macOS-only CI runs 44 offline tests for firmware parsing, MCU framing, RX descriptors,
802.11 management parsing, PHY/airtime calculations, aggregation, and pcap serialization.
It also enforces Ruff formatting/linting, shell syntax, and distribution builds. Hardware tests
are intentionally separate because GitHub runners have no radio. See
[docs/TESTING.md](docs/TESTING.md) for the dated attached-hardware evidence and exact untested
list, and [docs/QUALITY.md](docs/QUALITY.md) for the enforced checks and known engineering gaps.

## License and provenance

BSD-3-Clause-Clear. `mt7921u.py` and `rxd.py` are transcriptions of the BSD-3-Clause-Clear
MT7921 path in [openwrt/mt76](https://github.com/openwrt/mt76), commit `c5a3bd91`. See
[LICENSE](LICENSE), [NOTICE.md](NOTICE.md), and [RELATED_WORK.md](RELATED_WORK.md).
Release changes are recorded in [CHANGELOG.md](CHANGELOG.md).
