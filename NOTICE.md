# Third-party notices and provenance

This file records incorporated code, runtime dependencies, and their licenses. For the
broader technical lineage—including peer projects whose code is **not** incorporated—see
[RELATED_WORK.md](RELATED_WORK.md).

## Derivation from openwrt/mt76

`mt7921u.py` and `rxd.py` are transcriptions of the MediaTek MT7921 receive and
control paths from the Linux **[openwrt/mt76](https://github.com/openwrt/mt76)**
driver, which is licensed **BSD-3-Clause-Clear** on those paths.

- **Transcribed from commit `c5a3bd91`** (read 2026-08-27).
- The same driver lineage is integrated in the Linux kernel under
  [`drivers/net/wireless/mediatek/mt76`](https://github.com/torvalds/linux/tree/786262be6048deab760f68c8acc2c85607165894/drivers/net/wireless/mediatek/mt76).
  Linux is cited as the canonical in-tree integration; the exact transcription source for this
  repository remains the pinned openwrt/mt76 revision.
- The mt76 USB path has changed repeatedly; diff forward from that commit rather than
  guessing which fixes are already inherited here.
- Specific origins are cited inline in the source: `mt792x_usb.c`, `usb.c`, `mcu.c`,
  `eeprom.c`, `mt7921/mac.c`, the `mt76_connac_*` sources, and the `mt792x_regs.h` /
  `mt76_connac2_mac.h` register and descriptor definitions.

An SPDX audit of the upstream tree at that commit found the entire MT7921 path to be
BSD-3-Clause-Clear (GPL-2.0 in that tree is confined to `mt76x0/`, `mt7615/`,
`mt7996/`, and `npu.c`, none of which are used here). This project is released under
the same license; see [LICENSE](LICENSE).

The upstream notices retained for the transcribed source surfaces are:

- Copyright (C) 2023 MediaTek Inc. (`mt792x_usb.c`, `mt792x_regs.h`)
- Copyright (C) 2022 MediaTek Inc. (`mt76_connac2_mac.h`, `mt7921/usb.c`)
- Copyright (C) 2020 MediaTek Inc. (`mt76_connac_mcu.c`, `mt76_connac_mac.c`,
  `mt7921/mcu.c`, `mt7921/mac.c`)
- Copyright (C) 2018 Lorenzo Bianconi <lorenzo.bianconi83@gmail.com> (`usb.c`)
- Copyright (C) 2016 Felix Fietkau <nbd@nbd.name> (`eeprom.c`)

Those names and dates come from the headers at the pinned revision. “Portions copyright the
mt76 authors” is not used as a substitute for retaining the concrete upstream notices.

`rxd.py` also checks 802.11 numeric assignments and layouts against Linux
`include/linux/ieee80211.h` and Wireshark's `packet-ieee80211` dissector. These are protocol
references and independent-decoder checks; no Linux-header or Wireshark implementation is
incorporated into this repository. If future work translates executable logic from either,
its license must be reviewed and recorded before merging.

## MediaTek firmware (NOT distributed here)

This driver requires two MediaTek firmware blobs per chip at runtime. They are **not
included in this repository** and are **never committed** (see `.gitignore`). `setup.sh`
fetches them from the `linux-firmware` project's `mediatek/` directory:

- MT7921U: `WIFI_RAM_CODE_MT7961_1.bin`, `WIFI_MT7961_patch_mcu_1_2_hdr.bin`
- MT7925U: `mt7925/WIFI_RAM_CODE_MT7925_1_1.bin`, `mt7925/WIFI_MT7925_PATCH_MCU_1_1_hdr.bin`

For reproducibility, `setup.sh` and `mt7921u.FIRMWARE_FILES` pin linux-firmware commit
`e981caea6ed33c48d25b7dbf473327dbd01df163` and verify these SHA-256 hashes:

- `WIFI_RAM_CODE_MT7961_1.bin`: `b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`
- `WIFI_MT7961_patch_mcu_1_2_hdr.bin`: `a276c06c2b772adb50b86639d33c82824ff4c21d617feb78caea74c040b873f6`
- `mt7925/WIFI_RAM_CODE_MT7925_1_1.bin`: `23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`
- `mt7925/WIFI_MT7925_PATCH_MCU_1_1_hdr.bin`: `8eb46014d2a6b4124472eee7476d995008a6f40b1daffef87eb42f30d98699e1`

The MT7927 (USB `0e8d:6639`, chip id `0x6639`) needs `mt7927/WIFI_RAM_CODE_MT6639_2_1.bin` and
`mt7927/WIFI_MT6639_PATCH_MCU_2_1_hdr.bin` instead (`mt792x.h` at `c5a3bd91`); no such device
has been attached here, so they are not fetched and the id is not in `SUPPORTED_DEVICES`.

These binaries are MediaTek-licensed and covered by `LICENCE.mediatek` in
[linux-firmware](https://gitlab.com/kernel-firmware/linux-firmware/-/tree/main/mediatek),
which permits redistribution for use with devices containing MediaTek chipsets. Do not
fetch or load `BT_RAM_CODE_MT7961_1_2_hdr.bin` or `mt7925/BT_RAM_CODE_MT7925_1_1_hdr.bin`; the
Bluetooth function is unused and loading it can destabilize a composite device.

## Runtime dependencies

- **[pyusb](https://github.com/pyusb/pyusb)** (BSD) provides the Python USB API.
- **[libusb](https://libusb.info/)** (LGPL-2.1) is the native backend, loaded
  dynamically (Homebrew on macOS). It is not bundled or modified here.

## Peer projects (not code sources)

- **[wifikit at `6ab5c5b1`](https://github.com/RLabs-Inc/wifikit/tree/6ab5c5b1e88333b1acc0ada7c01d75f6d5d7ff24)**
  (MIT) independently implements native macOS userspace Wi-Fi support, including MT7921AU,
  within a broader Rust toolkit.
- **[wifit3 at `274f4849`](https://github.com/derv82/wifit3/tree/274f4849d88a88dd59d035f06b46c552c1a695be)**
  (GPL-2.0) contains a separate cross-platform userspace mt76/mt7921u port and documents
  Windows, Linux, and macOS operation.

They are cited as relevant prior and comparative work. No code from either peer project is
included in this repository as of `0.1.0`. If that changes, the exact files, revisions,
license compatibility, and modifications must be recorded above before publication.

Selected Linux downstream/backport projects are catalogued in
[RELATED_WORK.md](RELATED_WORK.md#selected-downstream-and-backport-projects). They are not
incorporated dependencies and therefore are not added to this license notice merely because
they share mt76 ancestry.
