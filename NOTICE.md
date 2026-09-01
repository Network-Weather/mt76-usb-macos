# Third-party notices and provenance

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

These binaries are MediaTek-licensed and covered by `LICENCE.mediatek` in
[linux-firmware](https://gitlab.com/kernel-firmware/linux-firmware/-/tree/main/mediatek),
which permits redistribution for use with devices containing MediaTek chipsets. Do not
fetch or load `BT_RAM_CODE_MT7961_1_2_hdr.bin`; the Bluetooth function is unused and
loading it can destabilize the composite device.

## Runtime dependencies

- **[pyusb](https://github.com/pyusb/pyusb)** (BSD) provides the Python USB API.
- **[libusb](https://libusb.info/)** (LGPL-2.1) is the native backend, loaded
  dynamically (Homebrew on macOS). It is not bundled or modified here.
