# Lineage and related work

This project is not an isolated implementation. It sits in an existing MediaTek driver,
firmware, USB, and packet-analysis ecosystem. The relationships below use precise terms so
that “based on,” “depends on,” and “peer” are not conflated.

## Foundational upstream projects

### openwrt/mt76 — direct transcription source

[`openwrt/mt76`](https://github.com/openwrt/mt76) is the direct source implementation for
the register map, USB control path, firmware boot sequence, MCU framing, channel/sniffer
commands, RX descriptors, and TX descriptor work in `mt7921u.py` and `rxd.py`.

This repository transcribes the BSD-3-Clause-Clear MT7921 path from
[`c5a3bd91`](https://github.com/openwrt/mt76/commit/c5a3bd91). It does not claim those
mechanisms as independently invented. Inline comments name the relevant mt76 files and
symbols so a change can be diffed against upstream. The detailed licensing audit and file
list are in [NOTICE.md](NOTICE.md).

The principal source surfaces at that revision are
[`mt792x_usb.c`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt792x_usb.c),
[`usb.c`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/usb.c),
[`mt7921/mcu.c`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mcu.c),
[`mt7921/mac.c`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mac.c),
[`mt76_connac_mcu.c`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac_mcu.c),
[`mt76_connac_mac.c`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac_mac.c),
[`mt792x_regs.h`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt792x_regs.h), and
[`mt76_connac2_mac.h`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac2_mac.h).
These links are deliberately revision-pinned; a moving `master` link is not adequate
provenance for transcribed register values or wire formats.

### Linux kernel mt76 — canonical in-tree integration

The corresponding driver is distributed in the Linux kernel under
[`drivers/net/wireless/mediatek/mt76`](https://github.com/torvalds/linux/tree/786262be6048deab760f68c8acc2c85607165894/drivers/net/wireless/mediatek/mt76),
including the in-tree
[`mt7921u` USB module](https://github.com/torvalds/linux/blob/786262be6048deab760f68c8acc2c85607165894/drivers/net/wireless/mediatek/mt76/mt7921/usb.c).
It is the canonical Linux integration of the same mt76 lineage, not a second independent
implementation. This repository's transcription baseline remains the openwrt/mt76 commit
above; the Linux tree is cited so readers can follow kernel integration, review lifecycle and
regulatory behavior, and avoid describing mt76 as merely an OpenWrt-only driver. The in-tree
links were reviewed at Linux commit
[`786262be`](https://github.com/torvalds/linux/commit/786262be6048deab760f68c8acc2c85607165894)
on 2026-09-01.

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
The comparison below was reviewed at
[`6ab5c5b1`](https://github.com/RLabs-Inc/wifikit/commit/6ab5c5b1e88333b1acc0ada7c01d75f6d5d7ff24)
(MIT); no wifikit code is incorporated here.

### wifit3

[`derv82/wifit3`](https://github.com/derv82/wifit3) is a Python userspace wireless auditor
for Windows, Linux, and macOS containing another port of the mt76/mt7921u path. Its
[`MT7921AU.md`](https://github.com/derv82/wifit3/blob/274f4849d88a88dd59d035f06b46c552c1a695be/src/wifit3/chips/mt7921au/MT7921AU.md)
documents Windows and Linux hardware results, interface-layout differences, endpoint
routing, monitor receive, and transmit behavior. It is valuable comparative evidence for
the same silicon and for a broader cross-platform design.
The comparison below was reviewed at
[`274f4849`](https://github.com/derv82/wifit3/commit/274f4849d88a88dd59d035f06b46c552c1a695be)
(GPL-2.0). Its source may inform experiments and clean, independent implementation, but it
must not be copied into this BSD-licensed project without an explicit license decision.

## Selected downstream and backport projects

These projects redistribute, package, backport, or document Linux mt76. They are useful for
compatibility reports and operational practices, but they are downstream evidence—not
additional original sources for the protocol—and no code from them is incorporated here.

- [`morrownr/mt76`](https://github.com/morrownr/mt76/tree/6b0ef22e275c36e3a5d10dd108546192c54e9238)
  adapts openwrt/mt76 for standalone out-of-tree builds, DKMS, diagnostics, and current desktop
  kernels. It is useful for install/diagnostic design and device reports, not for establishing
  that this macOS port supports the same adapters.
- [`astsam/mt7921`](https://github.com/astsam/mt7921/tree/f281125d5a7f654b53d745d824418492bb3f9f7c)
  is a historical backport of the kernel 5.18.19 MT7921 driver to older kernels. It helps explain
  deployment history but is too old to use as the current protocol baseline.
- [`morrownr/USB-WiFi`](https://github.com/morrownr/USB-WiFi/tree/0e00f79dca363e0d3edc410b0bb3905882041d42)
  collects adapter and monitor-mode field reports. Those reports are useful leads for hardware
  selection and test planning, but remain community observations until reproduced locally.

Listing every GitHub fork would add noise rather than provenance. A downstream belongs here
when it supplied a concrete design input, compatibility report, or experiment. Cite the exact
revision, file, issue, or result used; do not imply endorsement or independent confirmation.

## What this project can learn from the ecosystem

The following are investigation leads, not inherited capabilities. Each needs an independent
implementation and local tests before it can change this project's support claims.

| Source | Useful lesson | Current local state / required evidence |
|---|---|---|
| Linux/openwrt mt76 | Treat reset, resume, USB transport recovery, firmware events, regulatory setup, and TX-power programming as explicit lifecycle operations | Cold bring-up works; recovery, resume, regulatory enforcement, and sustained TX remain unqualified |
| mt76 issue [`#839`](https://github.com/openwrt/mt76/issues/839) and commit [`9de65849`](https://github.com/openwrt/mt76/commit/9de658490af758f89c083605bd412310511fff17) | MT792x must not advertise Linux “active monitor” merely because the mt76 core supports it | This project makes no active-monitor/auto-ACK claim; its low-rate injection demo is a different, experimental path |
| wifikit | Use explicit lifecycle states, targeted hardware test programs, and controlled MIB/test-mode experiments | The roadmap has soak/recovery and CCA work; peer self-reports are not substituted for local measurements |
| wifit3 | Discover the vendor interface, reject short USB writes, match MCU replies by sequence, drain stale RX, distinguish warm attach from cold boot, and build sanitized USB record/replay tests | Sequence matching exists; descriptor discovery, short-transfer tests, warm attach, stale-buffer handling, and replay fixtures remain roadmap work |
| wifit3 TX investigations | Sequence control, endpoint selection, per-band basic rates, regulatory-domain configuration, and TX-power programming all affect credible transmit results | Do not expand TX until these are independently implemented, isolated-RF tested, and evidence-gated |
| Linux downstreams | Diagnostics should record the actual module/source revision, firmware, USB identity/layout, and recent transport errors | The hardware smoke record covers identity and firmware; reusable transport diagnostics and broader layouts remain open |

Two boundaries matter. First, another project's successful hardware result is a hypothesis here,
not a pass. Second, learning an architecture is not permission to copy its implementation:
wifit3 is GPL-2.0, while this repository and the transcribed mt76 paths are
BSD-3-Clause-Clear.

## Capability comparison

This table is a project-selection aid, not an independent benchmark. Peer capabilities are
summarized from their own documentation at the pinned revisions above as read on 2026-09-01;
“not assessed” means this
project has not verified the behavior. All projects are moving targets.

| Dimension | mt76-usb-macos (this project) | openwrt/mt76 | wifikit | wifit3 |
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
| Local evidence style | 54 offline tests plus dated, redacted tri-band macOS hardware/pcap evidence | Upstream kernel development and per-device testing | Project reports extensive unit tests and hardware testing | USB-trace replay against Linux behavior plus real-hardware tests |
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

## The kernel-extension alternative on macOS

The other way a USB MediaTek adapter has been made to work on macOS is a resurrected proprietary
kernel extension. [D-LinkUtility-Package](https://github.com/chris1111/D-LinkUtility-Package)
(read 2026-09-02; binary only, no license file) repackages the Ralink-era
`RT2870USBWirelessDriver.kext` and the D-Link client utility so they install on Catalina through
Tahoe, for the RT28xx to RT55xx, MT7601, MT7610, and MT7621U parts. It provides a managed network
interface in station mode, not capture, and requires System Integrity Protection and Gatekeeper to
be disabled or a separately notarized build. Nothing in it applies to the MT7921 or MT7925
generation, and it was not run here. It is listed because it is the clearest example of the
opposite architectural choice to this project: a kernel driver with a system-integrity cost, versus
a userspace capture tool with none.

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
