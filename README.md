# mt76-usb-macos: MediaTek MT7921U and MT7925U (MT7961, MT7925) Wi-Fi 6E and Wi-Fi 7 monitor mode on macOS

[![CI](https://github.com/Network-Weather/mt76-usb-macos/actions/workflows/ci.yml/badge.svg)](https://github.com/Network-Weather/mt76-usb-macos/actions/workflows/ci.yml)
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

## Supported hardware

The name is the upstream family, `mt76-usb`, the Linux USB transport this driver transcribes.
Support is per chip and evidence-gated:

| Chip (Linux module) | Adapter tested | Status |
|---|---|---|
| MT7921AU / MT7921U, `mt7921u` (`MT7961`, USB `0e8d:7961`) | ALFA AWUS036AXML | Working: 2.4 / 5 / 6 GHz passive capture at 20 and 80 MHz, dated evidence in [docs/TESTING.md](docs/TESTING.md) |
| MT7925U, `mt7925u` (Netgear Nighthawk A9000, A8500; USB `0846:9072`, `0846:9050`, `0e8d:7925`) | none yet | In progress: port plan in [docs/MT7925.md](docs/MT7925.md); adds 160 MHz |
| MT7663U, MT76x2U, MT76x0U (`mt7663u`, `mt76x2u`, `mt76x0u`) | none | Not attempted: different firmware and MCU models; nothing here has been run on them |

**Lineage:** the driver logic is transcribed from the BSD-3-Clause-Clear
[`openwrt/mt76`](https://github.com/openwrt/mt76) MT7921 path, and it boots MediaTek blobs
fetched from [`linux-firmware`](https://gitlab.com/kernel-firmware/linux-firmware). The
same mt76 lineage is integrated in the
[Linux kernel](https://github.com/torvalds/linux/tree/master/drivers/net/wireless/mediatek/mt76);
openwrt/mt76 commit `c5a3bd91` is the exact transcription baseline for this repository. The
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
- For the Python driver: Homebrew `libusb` (`brew install libusb`) and Python 3.10+.
- For the pure C driver: Apple Command Line Tools (`clang`)—**no Homebrew, libusb, or Python required**.
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
./.venv/bin/python scripts/retune_drops.py                    # frames lost per channel hop, counts only
./.venv/bin/python scripts/width_probe.py 5GHz:132:138:80 6GHz:53:47:160   # which widths decode; counts only
./.venv/bin/python scripts/roam_watch.py --find MySSID           # BSSIDs of one SSID with k/v/r flags
./.venv/bin/python scripts/roam_watch.py --lock 5GHz:44 --client aa:bb:cc:dd:ee:ff
```

`scan.py` intentionally prints observed SSIDs and BSSIDs; treat its terminal output as
sensitive. `hardware_smoke.py` reports only aggregate counts, software/device capability,
and firmware hashes. It never emits captured identifiers or payloads.

The codebase includes both a high-level Python library and a zero-dependency C driver:

| Component | What it does |
|---|---|
| `mt7921u.py` | Python driver: USB vendor transfers, register I/O, MCU command framing, firmware download, channel and sniffer setup, receive, and injection |
| `rxd.py` | Python RX descriptor decode and 802.11 frame parsing (IE analysis, AKM suites, airtime accounting) |
| [`c/`](c/README.md) | Pure C driver: native macOS IOKit USB transport (zero external dependencies), MCU framing, TXWI injection, PCAP writer, and `mt7921_smoke` CLI |

## Pure C driver (zero dependencies)

Under [`c/`](c/README.md) is a pure C (C11) monitor-mode driver and hardware validator. It uses native Apple system frameworks (`IOKit` and `CoreFoundation`) with **zero external dependencies**—no Homebrew, no `libusb`, and no Python required.

Building and running offline unit tests:
```bash
make -C c all
make -C c test
```

Capabilities and CLI options:
```bash
# Quick 3-band sweep (channels 1, 36, 53)
./c/mt7921_smoke --plan quick --dwell 0.75

# Full 43-channel sweep emitting schema-compliant JSON
./c/mt7921_smoke --plan all --dwell 0.75

# Capture live frames to standard IEEE 802.11 radiotap PCAP
./c/mt7921_smoke --plan quick --dwell 1.0 --pcap /tmp/capture.pcap
tcpdump -r /tmp/capture.pcap -c 10

# Test packet injection across channels (sends 5 probe requests per channel)
./c/mt7921_smoke --plan quick --dwell 0.5 --inject 5

# Query on-die temperature sensor
./c/mt7921_smoke --temp

# Read a raw 16-byte efuse block
./c/mt7921_smoke --read-efuse 0x000
```

> **Design Note:** The C driver focuses strictly on MediaTek chipset-specific primitives (Connac2 TXWI injection, P-RXV hardware PHY telemetry decoding, MCU commands, USB transport, efuse, and thermal sensing). Hardware PHY telemetry (mode, MCS, NSS, bandwidth, GI, and Mbps data rate) is decoded directly from the baseband descriptors and recorded into Radiotap PCAP headers. Generic 802.11 Information Element (IE) parsing is intentionally omitted from the C driver, delegating upper-layer protocol dissection to tools such as Wireshark and `tcpdump`.

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
end-to-end validation.** What has been tested here is small: 60 Probe Requests at 50 ms spacing on
one 2.4 GHz channel, with the chip alive after every 20 and 677 directed Probe Responses received
([docs/TESTING.md](docs/TESTING.md#previously-observed-not-rerun-in-the-current-validation)).
Sustained or high-rate transmit is untested, so treat it as unknown rather than safe. The widely
reported Linux symptom, "injection kills the mt7921u" and the interface vanishes until a replug, is
a host-driver NULL dereference in the `TXRX_NOTIFY` path, fixed upstream in
[`d367ee6d`](https://github.com/openwrt/mt76/commit/d367ee6d) and present in this repository's
baseline; it is not an MCU panic and does not describe this userspace path. Linux mt76 also stopped
advertising generic active-monitor support for MT792x after
[upstream issue #839](https://github.com/openwrt/mt76/issues/839); that feature and this raw
injection demo are not equivalent, and neither establishes reliable auto-ACK behavior here.
The code does not implement regulatory-domain or per-band TX-power enforcement. Transmit only on
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
  multi-adapter support, or automatic recovery from a device that stops responding.
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

The macOS-only CI runs 54 offline tests for firmware parsing, MCU framing, RX descriptors,
802.11 management parsing, PHY/airtime calculations, aggregation, and pcap serialization.
It also enforces Ruff formatting/linting, shell syntax, and distribution builds. Hardware tests
are intentionally separate because GitHub runners have no radio. See
[docs/TESTING.md](docs/TESTING.md) for the dated attached-hardware evidence and exact untested
list, and [docs/QUALITY.md](docs/QUALITY.md) for the enforced checks and known engineering gaps.

## Planning

- [ROADMAP.md](ROADMAP.md): stack-ranked work in three tracks (roaming and steering instrument,
  community capture source, researcher reference). Fresh as of 2026-09-01.
- [TODO.md](TODO.md): the current sprint, one line per task. Fresh as of 2026-09-01.
- [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md): experiments that returned nothing, so they are
  not re-run by accident. Fresh as of 2026-09-02.
- [docs/MT7925.md](docs/MT7925.md): the MT7925U (Wi-Fi 7, 160 MHz) port plan, each claim checked
  against the pinned mt76 source. Fresh as of 2026-09-02.

## License and provenance

BSD-3-Clause-Clear. `mt7921u.py` and `rxd.py` are transcriptions of the BSD-3-Clause-Clear
MT7921 path in [openwrt/mt76](https://github.com/openwrt/mt76), commit `c5a3bd91`. See
[LICENSE](LICENSE), [NOTICE.md](NOTICE.md), and [RELATED_WORK.md](RELATED_WORK.md).
Release changes are recorded in [CHANGELOG.md](CHANGELOG.md).
