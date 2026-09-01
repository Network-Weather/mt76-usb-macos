# Lineage and related work

This project is not an isolated implementation. It sits in an existing MediaTek driver,
firmware, USB, and packet-analysis ecosystem. The relationships below use precise terms so
that “based on,” “depends on,” and “peer” are not conflated.

## Foundational upstream projects

### openwrt/mt76 — source implementation

[`openwrt/mt76`](https://github.com/openwrt/mt76) is the direct source implementation for
the register map, USB control path, firmware boot sequence, MCU framing, channel/sniffer
commands, RX descriptors, and TX descriptor work in `mt7921u.py` and `rxd.py`.

This repository transcribes the BSD-3-Clause-Clear MT7921 path from
[`c5a3bd91`](https://github.com/openwrt/mt76/commit/c5a3bd91). It does not claim those
mechanisms as independently invented. Inline comments name the relevant mt76 files and
symbols so a change can be diffed against upstream. The detailed licensing audit and file
list are in [NOTICE.md](NOTICE.md).

### linux-firmware — required firmware source

[`linux-firmware`](https://gitlab.com/kernel-firmware/linux-firmware) is the source of the
two MediaTek firmware binaries required at runtime. The binaries are not source code for
this repository and are not redistributed here, but the driver cannot boot the radio
without them. `setup.sh` fetches a pinned revision and verifies both SHA-256 hashes.

The tested revision is
[`e981caea6ed33c48d25b7dbf473327dbd01df163`](https://gitlab.com/kernel-firmware/linux-firmware/-/commit/e981caea6ed33c48d25b7dbf473327dbd01df163).
MediaTek's firmware license and the exact blob names are recorded in [NOTICE.md](NOTICE.md).

## Peer userspace driver projects

These projects overlap technically or functionally and should be consulted before claiming
a new technique. They are peers, not code sources for the current repository: no code from
either project is included here.

### wifikit

[`RLabs-Inc/wifikit`](https://github.com/RLabs-Inc/wifikit) is a native macOS userspace
Wi-Fi toolkit written in Rust. It supports multiple USB chipsets, including MT7921AU, and
has a much broader end-user and security-testing scope than this passive reference driver.
It is the closest peer for the “MT7921AU directly from macOS userspace” category.

### wifit3

[`derv82/wifit3`](https://github.com/derv82/wifit3) is a Python userspace wireless auditor
for Windows, Linux, and macOS containing another port of the mt76/mt7921u path. Its
[`MT7921AU.md`](https://github.com/derv82/wifit3/blob/master/src/wifit3/chips/mt7921au/MT7921AU.md)
documents Windows and Linux hardware results, interface-layout differences, endpoint
routing, monitor receive, and transmit behavior. It is valuable comparative evidence for
the same silicon and for a broader cross-platform design.

## Capability comparison

This table is a project-selection aid, not an independent benchmark. Peer capabilities are
summarized from their own documentation as read on 2026-08-31; “not assessed” means this
project has not verified the behavior. All projects are moving targets.

| Dimension | mt7921u-macos (this project) | openwrt/mt76 | wifikit | wifit3 |
|---|---|---|---|---|
| Primary goal | Compact driver reference and passive pcap | Linux kernel Wi-Fi driver | Native macOS security-testing toolkit | Cross-platform USB wireless auditor |
| Host integration | macOS userspace, PyUSB/libusb | Linux mac80211/cfg80211 kernel integration | Direct userspace USB; interactive Rust application | Direct userspace USB; Python application and packaged binaries |
| Hardware breadth | One ID/layout: `0e8d:7961`, interface 3 | Broad MediaTek mt76 family | Multiple MediaTek/Realtek chipsets and adapter IDs | Many listed Atheros/MediaTek/Ralink/Realtek adapters |
| MT7921AU bands documented | 2.4/5/6 GHz current hardware pass | Hardware, firmware, kernel, and regulatory-domain dependent | 2.4/5/6 GHz scanning advertised; its README calls 6 GHz reception weak | Current support table lists MT7921AU at 2.4/5 GHz |
| Passive capture | Radiotap pcap; scripts, no live UI | Standard Linux monitor interfaces and capture tools | Live scanner plus pcap/handshake export | Live scan/dashboard plus compact pcap/handshake export |
| Managed network interface | **No** association, AP, or OS interface | **Yes**; this is the right choice for normal Linux Wi-Fi integration | Not an OS network-interface replacement | Explicitly monitor RX/TX only; no AP/STA modes |
| Transmit/security work | Experimental low-rate Probe Request only; not release-qualified | Normal kernel TX facilities, not an attack application | Broad active security-testing/attack engines | PMKID, handshake, WPS, WEP, deauth, and related workflows |
| Multiple adapters | No | Multiple kernel devices | Yes | Yes |
| User experience | Source-level library and three examples | Linux networking/capture ecosystem | Interactive terminal UI and single compiled application | Interactive terminal UI and prebuilt binaries |
| Local evidence style | 44 offline tests plus dated, redacted tri-band macOS hardware/pcap evidence | Upstream kernel development and per-device testing | Project reports extensive unit tests and hardware testing | USB-trace replay against Linux behavior plus real-hardware tests |
| Regulatory enforcement | **None in transmit path** | Linux regulatory stack | Not assessed here | Not assessed here |
| Best reason to choose it | Smallest surface to read, modify, and compare with mt76; attached-device 6 GHz evidence | Mature Linux network integration and much broader driver lifecycle | Broader polished macOS workflow, chipset coverage, and active tooling | Broadest cross-platform/adapter workflow and replay-based porting harness |
| Main reason not to choose it | Narrow hardware, no UI/network interface, weak TX/recovery/soak coverage | Not native macOS userspace | Much larger scope when only a minimal reference is wanted | Much larger active-auditing scope; its MT7921 table does not currently claim 6 GHz |

### Where this project is comparatively strong

- It is deliberately small: two flat driver/decoder modules make mt76-to-Python comparison
  and experimentation substantially easier than navigating a complete application suite.
- Its exact macOS 6 GHz receive path is backed by a dated attached-device sweep and pcap
  independently parsed by Wireshark, with privacy-safe hashes instead of published ambient
  captures.
- It documents the specific endpoint-routing, RX-headroom, patch-semaphore, sniffer-mode,
  and efuse findings needed to understand why the port works.
- It remains passive by default and avoids kernel extensions, root, and a VM on the tested
  Mac/device combination.

### Where this project is comparatively weak

- Use mt76 on Linux when you need a normal managed Wi-Fi interface, established kernel
  lifecycle/recovery behavior, regulatory integration, or broad MediaTek device support.
- Use wifikit when you want a broader native macOS end-user application, more adapters,
  interactive scanning, capture/export workflows, or active security tooling.
- Use wifit3 when you want Windows/Linux/macOS packaging, a much broader adapter table,
  multiple cards, a TUI, active audit workflows, or its USB-recording replay harness.
- This project has only one hardware ID/layout, no extcap/live UI, no multi-adapter mode,
  no association/AP mode, no current 40/80 MHz qualification, no soak/suspend/recovery
  qualification, and an injection path that is explicitly unsafe for sustained use.
- A smaller codebase is easier to audit, but it is not evidence of greater completeness or
  reliability. Peer claims are not local test results, and local results do not establish
  superiority outside the tested host, firmware, radio, channels, and duration.

## Supporting projects and validation tools

- [`PyUSB`](https://github.com/pyusb/pyusb) supplies the Python USB API.
- [`libusb`](https://github.com/libusb/libusb) supplies native userspace USB transport on
  macOS.
- [`Wireshark`](https://gitlab.com/wireshark/wireshark) independently parses the emitted
  radiotap pcap during end-to-end validation.

These dependencies and tools retain their own licenses. See [NOTICE.md](NOTICE.md) for the
runtime dependency summary.

## Contribution rule

When a change is informed by upstream or peer work, cite the repository, revision, file,
symbol, issue, or experiment that informed it. Update [NOTICE.md](NOTICE.md) if code or data
is incorporated; update this document when the relationship is comparative only. A result
from another project is context, not evidence that this repository passed the same test.
