# Third-party notices and provenance

This file records incorporated code, runtime dependencies, and their licenses. For the
broader technical lineage—including peer projects whose code is **not** incorporated—see
[RELATED_WORK.md](RELATED_WORK.md).

## Derivation from openwrt/mt76

`mt7921u.py` and `rxd.py` are transcriptions of the MediaTek MT7921 receive and
control paths from the Linux **[openwrt/mt76](https://github.com/openwrt/mt76)**
driver, which is licensed **BSD-3-Clause-Clear** on those paths.

- **Transcribed from commit `c5a3bd91`** (read 2026-08-27).
- The mt76 USB path has changed repeatedly; diff forward from that commit rather than
  guessing which fixes are already inherited here.
- Specific origins are cited inline in the source: `mt792x_usb.c`, `usb.c`, `mcu.c`,
  `eeprom.c`, `mt7921/mac.c`, the `mt76_connac_*` sources, and the `mt792x_regs.h` /
  `mt76_connac2_mac.h` register and descriptor definitions.

An SPDX audit of the upstream tree at that commit found the entire MT7921 path to be
BSD-3-Clause-Clear (GPL-2.0 in that tree is confined to `mt76x0/`, `mt7615/`,
`mt7996/`, and `npu.c`, none of which are used here). This project is released under
the same license; see [LICENSE](LICENSE).

## MediaTek firmware (NOT distributed here)

This driver requires two MediaTek firmware blobs at runtime. They are **not included
in this repository** and are **never committed** (see `.gitignore`). `setup.sh` fetches
them from the `linux-firmware` project:

- `WIFI_RAM_CODE_MT7961_1.bin`
- `WIFI_MT7961_patch_mcu_1_2_hdr.bin`

For reproducibility, `setup.sh` pins linux-firmware commit
`e981caea6ed33c48d25b7dbf473327dbd01df163` and verifies these SHA-256 hashes:

- `WIFI_RAM_CODE_MT7961_1.bin`: `b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`
- `WIFI_MT7961_patch_mcu_1_2_hdr.bin`: `a276c06c2b772adb50b86639d33c82824ff4c21d617feb78caea74c040b873f6`

These binaries are MediaTek-licensed and covered by `LICENCE.mediatek` in
[linux-firmware](https://gitlab.com/kernel-firmware/linux-firmware/-/tree/main/mediatek),
which permits redistribution for use with devices containing MediaTek chipsets. Do not
fetch or load `BT_RAM_CODE_MT7961_1_2_hdr.bin`; the Bluetooth function is unused and
loading it can destabilize the composite device.

## Runtime dependencies

- **[pyusb](https://github.com/pyusb/pyusb)** (BSD) provides the Python USB API.
- **[libusb](https://libusb.info/)** (LGPL-2.1) is the native backend, loaded
  dynamically (Homebrew on macOS). It is not bundled or modified here.

## Peer projects (not code sources)

- **[wifikit](https://github.com/RLabs-Inc/wifikit)** independently implements native
  macOS userspace Wi-Fi support, including MT7921AU, within a broader Rust toolkit.
- **[wifit3](https://github.com/derv82/wifit3)** contains a separate cross-platform
  userspace mt76/mt7921u port and documents Windows, Linux, and macOS operation.

They are cited as relevant prior and comparative work. No code from either peer project is
included in this repository as of `0.1.0`. If that changes, the exact files, revisions,
license compatibility, and modifications must be recorded above before publication.
