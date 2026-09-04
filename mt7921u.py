# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
# Portions transcribed from openwrt/mt76 (BSD-3-Clause-Clear).
# See NOTICE.md and RELATED_WORK.md for source lineage, firmware, and peer implementations.
"""Userspace driver for the MediaTek MT7921AU over libusb.

Transcribed from the mt76 driver (BSD-3-Clause-Clear), specifically
mt792x_usb.c (mt792xu_rr / mt792xu_wr / mt792xu_copy / mt792xu_mcu_power_on)
and usb.c (__mt76u_vendor_request). Register addresses from mt792x_regs.h.

Register I/O, firmware download, MCU command framing, channel and sniffer setup,
and passive receive. Frame injection (the inject/_build_txwi/build_probe_request
helpers at the tail of this module) is research-grade and rate-limited: it is
confirmed only at scan rates (60 frames at 50 ms, chip alive after); sustained or
high-rate transmit is untested.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import os
import struct
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import usb.core
import usb.util

__version__ = "0.3.0"

# ---------------------------------------------------------------------------
# Supported USB devices and firmware
#
# mt7921/usb.c mt7921u_device_table and mt7925/usb.c mt7925u_device_table at c5a3bd91.
# Each entry matches interface class/subclass/protocol ff/ff/ff, never an interface
# number; see select_wifi_interface below.
# ---------------------------------------------------------------------------

CHIP_MT7921 = "mt7921"
CHIP_MT7925 = "mt7925"

VID, PID = 0x0E8D, 0x7961  # the MT7921 reference adapter (ALFA AWUS036AXML)

# The MT7927 USB id 0e8d:6639 (mt7925/usb.c:13 at c5a3bd91) is deliberately absent: it needs
# the mt7927/ blobs, which are neither fetched nor validated here (NOTICE.md).
SUPPORTED_DEVICES: dict[tuple[int, int], str] = {
    (0x0E8D, 0x7961): CHIP_MT7921,
    (0x0E8D, 0x7925): CHIP_MT7925,
    (0x0846, 0x9050): CHIP_MT7925,  # Netgear Nighthawk A8500
    (0x0846, 0x9072): CHIP_MT7925,  # Netgear Nighthawk A9000
}

# Firmware blobs per chip, relative to the firmware directory, with the SHA-256 of the
# copy at the linux-firmware commit pinned in setup.sh. mt792x.h MT7921_FIRMWARE_WM,
# MT7921_ROM_PATCH, MT7925_FIRMWARE_WM, MT7925_ROM_PATCH at c5a3bd91.
LINUX_FIRMWARE_COMMIT = "e981caea6ed33c48d25b7dbf473327dbd01df163"
FIRMWARE_FILES: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    # chip: ((patch relative path, sha256), (ram relative path, sha256))
    CHIP_MT7921: (
        (
            "WIFI_MT7961_patch_mcu_1_2_hdr.bin",
            "a276c06c2b772adb50b86639d33c82824ff4c21d617feb78caea74c040b873f6",
        ),
        (
            "WIFI_RAM_CODE_MT7961_1.bin",
            "b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9",
        ),
    ),
    CHIP_MT7925: (
        (
            "mt7925/WIFI_MT7925_PATCH_MCU_1_1_hdr.bin",
            "8eb46014d2a6b4124472eee7476d995008a6f40b1daffef87eb42f30d98699e1",
        ),
        (
            "mt7925/WIFI_RAM_CODE_MT7925_1_1.bin",
            "23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120",
        ),
    ),
}

REPO_ROOT = Path(__file__).resolve().parent


def firmware_dir(fw_dir: str | os.PathLike | None = None) -> Path:
    """Where setup.sh put the blobs: an explicit argument, $MT76_FW_DIR, the older
    $MT7921_FW_DIR, then <repo>/firmware."""
    if fw_dir is not None:
        return Path(fw_dir)
    for var in ("MT76_FW_DIR", "MT7921_FW_DIR"):
        value = os.environ.get(var)
        if value:
            return Path(value)
    return REPO_ROOT / "firmware"


def firmware_paths(chip: str, fw_dir: str | os.PathLike | None = None) -> tuple[Path, Path]:
    """(patch path, RAM path) for one chip."""
    (patch, _), (ram, _) = FIRMWARE_FILES[chip]
    base = firmware_dir(fw_dir)
    return base / patch, base / ram


def load_firmware(
    chip: str, fw_dir: str | os.PathLike | None = None, verify: bool = True
) -> tuple[bytes, bytes]:
    """Read the patch and RAM blobs for one chip, checking the pinned SHA-256s.

    verify=False skips the hash check for deliberately different firmware; the
    examples and scripts keep it on.
    """
    patch_path, ram_path = firmware_paths(chip, fw_dir)
    for path in (patch_path, ram_path):
        if not path.is_file():
            raise FileNotFoundError(f"firmware missing: {path}; run bash setup.sh")
    blobs = []
    for path, (_, expected) in zip((patch_path, ram_path), FIRMWARE_FILES[chip], strict=True):
        data = path.read_bytes()
        if verify:
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise RuntimeError(
                    f"firmware checksum mismatch for {path.name}: {actual}; run bash setup.sh"
                )
        blobs.append(data)
    return blobs[0], blobs[1]


# ---------------------------------------------------------------------------
# Descriptor discovery (usb.c mt76u_set_endpoints at c5a3bd91)
#
# mt76 binds by interface class ff/ff/ff and assigns endpoints positionally: the
# first two bulk IN endpoints in descriptor order are PKT_RX and CMD_RESP; the first
# six bulk OUT endpoints are INBAND_CMD, AC_BE, AC_BK, AC_VI, AC_VO, HCCA. Other
# endpoint types are skipped; usb.c:326 fails unless exactly 2 IN and 6 OUT were found.
# ---------------------------------------------------------------------------

N_BULK_IN = 2  # __MT_EP_IN_MAX
N_BULK_OUT = 6  # __MT_EP_OUT_MAX
USB_ENDPOINT_XFER_BULK = 2  # bmAttributes & 0x3
USB_ENDPOINT_DIR_IN = 0x80
WIFI_INTERFACE_CLASS = (0xFF, 0xFF, 0xFF)


@dataclass(frozen=True)
class EndpointDesc:
    address: int  # bEndpointAddress, direction bit included
    attributes: int  # bmAttributes

    @property
    def is_bulk(self) -> bool:
        return (self.attributes & 0x3) == USB_ENDPOINT_XFER_BULK

    @property
    def is_in(self) -> bool:
        return bool(self.address & USB_ENDPOINT_DIR_IN)


@dataclass(frozen=True)
class InterfaceDesc:
    number: int
    interface_class: int
    subclass: int
    protocol: int
    endpoints: tuple[EndpointDesc, ...]

    @property
    def class_triple(self) -> tuple[int, int, int]:
        return (self.interface_class, self.subclass, self.protocol)


@dataclass(frozen=True)
class UsbLayout:
    """What open() resolved from the descriptors: which interface holds the Wi-Fi
    function and which endpoint addresses play which mt76 role."""

    vid: int
    pid: int
    chip: str
    interface: int
    in_eps: tuple[int, ...]  # N_BULK_IN addresses, direction bit included
    out_eps: tuple[int, ...]  # N_BULK_OUT addresses

    @property
    def usb_id(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"

    @property
    def ep_in_pkt_rx(self) -> int:
        return self.in_eps[0]

    @property
    def ep_in_cmd_resp(self) -> int:
        return self.in_eps[1]

    @property
    def ep_out_inband_cmd(self) -> int:
        return self.out_eps[0]

    @property
    def ep_out_ac_be(self) -> int:
        return self.out_eps[1]


class UnsupportedDevice(RuntimeError):
    """No usable device, or the descriptors do not match what mt76 requires."""


def _describe_interfaces(interfaces: list[InterfaceDesc]) -> str:
    parts = []
    for intf in interfaces:
        bulk_in = sum(1 for ep in intf.endpoints if ep.is_bulk and ep.is_in)
        bulk_out = sum(1 for ep in intf.endpoints if ep.is_bulk and not ep.is_in)
        cls = "/".join(f"{v:02x}" for v in intf.class_triple)
        parts.append(f"intf {intf.number} class {cls} bulk in/out {bulk_in}/{bulk_out}")
    return "; ".join(parts) or "no interfaces"


def select_wifi_interface(interfaces: list[InterfaceDesc]) -> tuple[int, tuple, tuple]:
    """Pick the interface mt76 would bind and assign its endpoints positionally.

    Returns (interface number, in endpoint addresses, out endpoint addresses).
    Raises UnsupportedDevice when no interface qualifies or more than one does, so a
    layout this code has never seen fails closed with the descriptors it saw.
    """
    candidates = []
    for intf in interfaces:
        if intf.class_triple != WIFI_INTERFACE_CLASS:
            continue
        in_eps: list[int] = []
        out_eps: list[int] = []
        for ep in intf.endpoints:
            if not ep.is_bulk:
                continue
            if ep.is_in and len(in_eps) < N_BULK_IN:
                in_eps.append(ep.address)
            elif not ep.is_in and len(out_eps) < N_BULK_OUT:
                out_eps.append(ep.address)
        if len(in_eps) == N_BULK_IN and len(out_eps) == N_BULK_OUT:
            candidates.append((intf.number, tuple(in_eps), tuple(out_eps)))
    if not candidates:
        raise UnsupportedDevice(
            "no interface with class ff/ff/ff and at least "
            f"{N_BULK_IN} bulk IN + {N_BULK_OUT} bulk OUT endpoints "
            f"({_describe_interfaces(interfaces)})"
        )
    if len(candidates) > 1:
        numbers = ", ".join(str(c[0]) for c in candidates)
        raise UnsupportedDevice(
            f"ambiguous layout: interfaces {numbers} all qualify "
            f"({_describe_interfaces(interfaces)})"
        )
    return candidates[0]


def interfaces_from_pyusb(dev) -> list[InterfaceDesc]:
    """Flatten the active configuration's interfaces (alternate setting 0 only)."""
    cfg = dev.get_active_configuration()
    out = []
    for intf in cfg:
        if intf.bAlternateSetting != 0:
            continue
        eps = tuple(EndpointDesc(ep.bEndpointAddress, ep.bmAttributes) for ep in intf)
        out.append(
            InterfaceDesc(
                intf.bInterfaceNumber,
                intf.bInterfaceClass,
                intf.bInterfaceSubClass,
                intf.bInterfaceProtocol,
                eps,
            )
        )
    return out


def layout_from_pyusb(dev) -> UsbLayout:
    key = (dev.idVendor, dev.idProduct)
    chip = SUPPORTED_DEVICES.get(key)
    if chip is None:
        raise UnsupportedDevice(f"device {key[0]:04x}:{key[1]:04x} is not in SUPPORTED_DEVICES")
    number, in_eps, out_eps = select_wifi_interface(interfaces_from_pyusb(dev))
    return UsbLayout(key[0], key[1], chip, number, in_eps, out_eps)


def parse_usb_id(text: str) -> tuple[int, int]:
    """'0846:9072' -> (0x0846, 0x9072)."""
    try:
        vid, pid = text.lower().split(":")
        return int(vid, 16), int(pid, 16)
    except ValueError as exc:
        raise ValueError(f"usb id must look like 0e8d:7961, got {text!r}") from exc


def find_supported_devices(usb_id: str | None = None) -> list:
    """Attached pyusb devices whose VID:PID is supported, optionally one exact ID.

    usb_id defaults to $MT76_USB_ID so a host with two adapters can pick one without
    changing code. Returns pyusb device objects; nothing is opened or claimed.
    """
    wanted = usb_id or os.environ.get("MT76_USB_ID") or None
    keys = {parse_usb_id(wanted)} if wanted else set(SUPPORTED_DEVICES)
    found = []
    for dev in usb.core.find(find_all=True):
        if (dev.idVendor, dev.idProduct) in keys:
            found.append(dev)
    return found


# usb.h: USB_TYPE_VENDOR = 0x40, USB_DIR_IN = 0x80
USB_TYPE_VENDOR = 0x40
USB_DIR_IN = 0x80
USB_DIR_OUT = 0x00

# mt792x.h
MT_USB_TYPE_VENDOR = USB_TYPE_VENDOR | 0x1F  # 0x5f
MT_USB_TYPE_UHW_VENDOR = USB_TYPE_VENDOR | 0x1E  # 0x5e

# mt76.h, enum mt_vendor_req
MT_VEND_DEV_MODE = 0x01
MT_VEND_WRITE = 0x02
MT_VEND_POWER_ON = 0x04
MT_VEND_MULTI_WRITE = 0x06
MT_VEND_MULTI_READ = 0x07
MT_VEND_READ_EXT = 0x63
MT_VEND_WRITE_EXT = 0x66
MT_VEND_FEATURE_SET = 0x91

# mt76.h endpoint roles, as resolved on the MT7921 reference adapter (interface 3;
# interfaces 0-2 are its Bluetooth function). These are the defaults an unopened device
# object carries; open() replaces them with what the attached device's descriptors say
# (see select_wifi_interface). The A9000 exposes the same addresses on interface 0.
EP_OUT_INBAND_CMD = 0x08
EP_OUT_AC_BE = 0x04
EP_IN_PKT_RX = 0x84
EP_IN_CMD_RESP = 0x85

WIFI_INTERFACE = 3  # MT7921 reference adapter; informational, open() does not use it

# mt792x_regs.h
MT_HW_CHIPID = 0x70010200
MT_HW_REV = 0x70010204
MT_CONN_ON_MISC = 0x7C0600F0
MT_TOP_MISC2_FW_PWR_ON = 1 << 0
MT_TOP_MISC2_FW_N9_ON = 1 << 1
MT_TOP_MISC2_FW_N9_RDY = 0x3
MT_CONN_ON_LPCTL = 0x7C060010
PCIE_LPCR_HOST_SET_OWN = 1 << 0
PCIE_LPCR_HOST_CLR_OWN = 1 << 1
PCIE_LPCR_HOST_OWN_SYNC = 1 << 2
MT_CONN_STATUS = 0x7C053C10
MT_WIFI_PATCH_DL_STATE = 1 << 0


def MT_UMAC(ofs: int) -> int:
    return 0x74000000 + ofs


MT_UDMA_TX_QSEL = MT_UMAC(0x008)
MT_FW_DL_EN = 1 << 3
MT_UDMA_WLCFG_0 = MT_UMAC(0x018)
MT_WL_RX_EN = 1 << 22
MT_WL_TX_EN = 1 << 23
MT_WL_RX_FLUSH = 1 << 19
MT_UDMA_CONN_INFRA_STATUS = MT_UMAC(0xA20)
MT_UDMA_CONN_WFSYS_INIT_DONE = 1 << 22

MT_SSUSB_EPCTL_CSR_EP_RST_OPT = 0x74011800 + 0x090


def MT_UWFDMA0(ofs: int) -> int:
    return 0x7C024000 + ofs


MT_UWFDMA0_GLO_CFG = MT_UWFDMA0(0x208)
MT_WFDMA0_GLO_CFG_TX_DMA_EN = 1 << 0
MT_WFDMA0_GLO_CFG_RX_DMA_EN = 1 << 2

MT_WFSYS_SW_RST_B = 0x18000140  # mt792x_regs.h WFSYS reset register
WFSYS_SW_RST_B = 1 << 0
WFSYS_SW_INIT_DONE = 1 << 4

VEND_TIMEOUT_MS = 1000
VEND_RETRIES = 10


class Mt7921u:
    """Register-level access to an mt792x USB chip. Context manager.

    CHIP names which SUPPORTED_DEVICES entries this class drives; open() refuses a
    device whose descriptors resolve to another chip so an MT7925 is never driven
    with MT7921 command encodings by accident.
    """

    CHIP = CHIP_MT7921
    # mt76_chip(): rr(MT_HW_CHIPID) is the chip number itself (mt7925/usb.c:215-217,
    # mt7921/usb.c:206-208 at c5a3bd91). Values this class accepts from chip_id().
    CHIP_IDS: tuple[int, ...] = (0x7961,)
    # Module whose decode() understands this chip's RX descriptor (see decoder_for()).
    DECODER_MODULE = "rxd"
    # Widest capture this chip has been shown to produce frames at. The MT7921U returns
    # zero transfers when configured for 160 MHz, recorded in NEGATIVE_RESULTS.md, so a
    # caller that asks for it would get a silent radio rather than an error. Raising this
    # requires dated hardware evidence, as ROADMAP.md's decision rules require for any
    # new width.
    MAX_WIDTH_MHZ = 80

    def __init__(self, verbose: bool = False, usb_id: str | None = None):
        self.dev = None
        self.verbose = verbose
        self.usb_id = usb_id  # "vvvv:pppp" to pick one adapter; None = any supported
        self._claimed = []
        self.layout: UsbLayout | None = None
        # Endpoint roles. Defaults are the reference adapter's so an object built
        # without USB (tests) still frames commands; open() sets the real ones.
        self.ep_in_pkt_rx = EP_IN_PKT_RX
        self.ep_in_cmd_resp = EP_IN_CMD_RESP
        self.ep_out_inband_cmd = EP_OUT_INBAND_CMD
        self.ep_out_ac_be = EP_OUT_AC_BE

    def __enter__(self) -> Mt7921u:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        """Find one supported device, resolve its layout, claim the Wi-Fi interface."""
        candidates = find_supported_devices(self.usb_id)
        if not candidates:
            wanted = self.usb_id or os.environ.get("MT76_USB_ID") or "any supported"
            raise UnsupportedDevice(f"device not found (looked for {wanted})")
        if len(candidates) > 1:
            ids = ", ".join(f"{d.idVendor:04x}:{d.idProduct:04x}" for d in candidates)
            raise UnsupportedDevice(
                f"{len(candidates)} supported devices attached ({ids}); "
                "pass usb_id or set MT76_USB_ID to pick one"
            )
        dev = candidates[0]
        layout = layout_from_pyusb(dev)
        if layout.chip != self.CHIP:
            raise UnsupportedDevice(
                f"device {layout.usb_id} is an {layout.chip}; {type(self).__name__} "
                f"drives {self.CHIP} (use open_device() to pick the class by USB id)"
            )
        try:
            usb.util.claim_interface(dev, layout.interface)
        except usb.core.USBError as exc:
            raise RuntimeError(f"cannot claim interface {layout.interface}: {exc}") from exc
        self.dev = dev
        self._claimed.append(layout.interface)
        self.layout = layout
        self.ep_in_pkt_rx = layout.ep_in_pkt_rx
        self.ep_in_cmd_resp = layout.ep_in_cmd_resp
        self.ep_out_inband_cmd = layout.ep_out_inband_cmd
        self.ep_out_ac_be = layout.ep_out_ac_be
        # The USB id says which family; the silicon says which blobs. Refuse before any
        # firmware is offered to a chip this class does not know (0x6639 is the MT7927,
        # which mt7925/usb.c:219 forces to 0x7927 and feeds different files).
        chip_id = self.chip_id()
        if chip_id not in self.CHIP_IDS:
            self.close()
            raise UnsupportedDevice(
                f"device {layout.usb_id} reports chip id {chip_id:#06x}; "
                f"{type(self).__name__} knows {[f'{c:#06x}' for c in self.CHIP_IDS]}"
            )
        if self.verbose:
            print(
                f"  opened {layout.usb_id} ({layout.chip}) interface {layout.interface} "
                f"in={[f'{e:#04x}' for e in layout.in_eps]} "
                f"out={[f'{e:#04x}' for e in layout.out_eps]}"
            )

    def close(self) -> None:
        if self.dev is None:
            return
        for intf in self._claimed:
            with suppress(Exception):
                usb.util.release_interface(self.dev, intf)
        self._claimed.clear()
        usb.util.dispose_resources(self.dev)
        self.dev = None

    # ---- vendor control transfers -------------------------------------

    def _vendor(
        self,
        req: int,
        req_type: int,
        value: int,
        index: int,
        data_or_len,
        timeout: int = VEND_TIMEOUT_MS,
    ):
        """__mt76u_vendor_request, including its retry loop."""
        last = None
        for _ in range(VEND_RETRIES):
            try:
                return self.dev.ctrl_transfer(req_type, req, value, index, data_or_len, timeout)
            except usb.core.USBError as exc:
                last = exc
                time.sleep(0.005)
        raise RuntimeError(f"vendor request req:{req:02x} off:{index:04x} failed: {last}")

    def rr(self, addr: int) -> int:
        """mt792xu_rr: 32-bit register read via MT_VEND_READ_EXT."""
        buf = self._vendor(
            MT_VEND_READ_EXT,
            USB_DIR_IN | MT_USB_TYPE_VENDOR,
            (addr >> 16) & 0xFFFF,
            addr & 0xFFFF,
            4,
        )
        val = struct.unpack("<I", bytes(buf))[0]
        if self.verbose:
            print(f"    rr  0x{addr:08x} -> 0x{val:08x}")
        return val

    def wr(self, addr: int, val: int) -> None:
        """mt792xu_wr: 32-bit register write via MT_VEND_WRITE_EXT."""
        if self.verbose:
            print(f"    wr  0x{addr:08x} <- 0x{val:08x}")
        self._vendor(
            MT_VEND_WRITE_EXT,
            USB_DIR_OUT | MT_USB_TYPE_VENDOR,
            (addr >> 16) & 0xFFFF,
            addr & 0xFFFF,
            struct.pack("<I", val & 0xFFFFFFFF),
        )

    def rmw(self, addr: int, mask: int, val: int) -> int:
        new = val | (self.rr(addr) & ~mask & 0xFFFFFFFF)
        self.wr(addr, new)
        return new

    def set_bits(self, addr: int, bits: int) -> int:
        return self.rmw(addr, bits, bits)

    def clear_bits(self, addr: int, bits: int) -> int:
        return self.rmw(addr, bits, 0)

    def uhw_rr(self, addr: int) -> int:
        """mt792xu_uhw_rr: USB host-wrapper register read."""
        buf = self._vendor(
            MT_VEND_DEV_MODE,
            USB_DIR_IN | MT_USB_TYPE_UHW_VENDOR,
            (addr >> 16) & 0xFFFF,
            addr & 0xFFFF,
            4,
        )
        return struct.unpack("<I", bytes(buf))[0]

    def uhw_wr(self, addr: int, val: int) -> None:
        """mt792xu_uhw_wr: USB host-wrapper register write."""
        self._vendor(
            MT_VEND_WRITE,
            USB_DIR_OUT | MT_USB_TYPE_UHW_VENDOR,
            (addr >> 16) & 0xFFFF,
            addr & 0xFFFF,
            struct.pack("<I", val & 0xFFFFFFFF),
        )

    def copy(self, offset: int, data: bytes, chunk: int = 512) -> None:
        """mt792xu_copy: bulk register-space write, 4-byte aligned."""
        if len(data) % 4:
            data = data + b"\x00" * (4 - len(data) % 4)
        i = 0
        while i < len(data):
            n = min(chunk, len(data) - i)
            self._vendor(
                MT_VEND_WRITE_EXT,
                USB_DIR_OUT | MT_USB_TYPE_VENDOR,
                ((offset + i) >> 16) & 0xFFFF,
                (offset + i) & 0xFFFF,
                data[i : i + n],
            )
            i += n

    def power_on(self) -> None:
        """mt792xu_mcu_power_on."""
        self._vendor(MT_VEND_POWER_ON, USB_DIR_OUT | MT_USB_TYPE_VENDOR, 0x0, 0x1, None)
        if not self.poll(MT_CONN_ON_MISC, MT_TOP_MISC2_FW_PWR_ON, MT_TOP_MISC2_FW_PWR_ON, 500):
            raise RuntimeError("timeout waiting for FW_PWR_ON")

    # ---- helpers -------------------------------------------------------

    def poll(self, addr: int, mask: int, expect: int, timeout_ms: int) -> bool:
        """mt76_poll_msec: read until (val & mask) == expect."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            if (self.rr(addr) & mask) == expect:
                return True
            if time.monotonic() > deadline:
                return False
            time.sleep(0.010)

    def bulk_out(self, ep: int, data: bytes, timeout: int = 1000) -> int:
        return self.dev.write(ep, data, timeout)

    def bulk_in(self, ep: int, length: int, timeout: int = 1000) -> bytes:
        return bytes(self.dev.read(ep, length, timeout))

    # ---- identity ------------------------------------------------------

    def chip_id(self) -> int:
        """mt76_chip(): the low half of MT_HW_CHIPID (0x7961, 0x7925, 0x6639, ...).

        mt7925/usb.c:215-217 at c5a3bd91 builds rev = (rr(CHIPID) << 16) | (rr(REV) & 0xff)
        and mt76_chip() returns rev >> 16.
        """
        return self.rr(MT_HW_CHIPID) & 0xFFFF

    def hw_rev(self) -> int:
        return self.rr(MT_HW_REV)


# ---------------------------------------------------------------------------
# MCU command layer
#
# From mt7921u_mcu_send_message (mt7921/usb.c) and
# mt76_connac2_mcu_fill_message (mt76_connac_mcu.c).
# ---------------------------------------------------------------------------

# mt76_connac2_mac.h
MT_HDR_FORMAT_CMD = 1
MT_TX_TYPE_CMD = 2
MT_TX_MCU_PORT_RX_Q0 = 0x20
MT_TX_PORT_IDX_MCU = 1
MT_TXD1_LONG_FORMAT = 1 << 31  # connac2 only; mt76_connac3_mac.h has no such bit
MT_TXD1_HDR_FORMAT_SHIFT = 16  # MT_TXD1_HDR_FORMAT GENMASK(17, 16) on connac2
# MCU TXD word 1 as mt76_connac2_mcu_fill_message writes it (mt7921).
MCU_TXD1_CONNAC2 = MT_TXD1_LONG_FORMAT | (MT_HDR_FORMAT_CMD << MT_TXD1_HDR_FORMAT_SHIFT)

# mt76_connac_mcu.h
MCU_PKT_ID = 0xA0
MCU_Q_QUERY, MCU_Q_SET, MCU_Q_RESERVED, MCU_Q_NA = 0, 1, 2, 3
# enum mcu_s2d_type in mt76_connac_mcu.h: H2N, C2N, H2C, H2CN
MCU_S2D_H2N, MCU_S2D_C2N, MCU_S2D_H2C, MCU_S2D_H2CN = 0, 1, 2, 3

MCU_CMD_TARGET_ADDRESS_LEN_REQ = 0x01
MCU_CMD_FW_START_REQ = 0x02
MCU_CMD_NIC_POWER_CTRL = 0x04
MCU_CMD_PATCH_START_REQ = 0x05
MCU_CMD_PATCH_FINISH_REQ = 0x07
MCU_CMD_PATCH_SEM_CONTROL = 0x10
MCU_CMD_FW_SCATTER = 0xEE

PATCH_SEM_RELEASE, PATCH_SEM_GET = 0, 1
(PATCH_NOT_DL_SEM_FAIL, PATCH_IS_DL, PATCH_NOT_DL_SEM_SUCCESS, PATCH_REL_SEM_SUCCESS) = 0, 1, 2, 3

DL_MODE_ENCRYPT = 1 << 0
DL_MODE_KEY_IDX_SHIFT = 1
DL_MODE_RESET_SEC_IV = 1 << 3
DL_MODE_WORKING_PDA_CR4 = 1 << 4
DL_CONFIG_ENCRY_MODE_SEL = 1 << 6
DL_MODE_NEED_RSP = 1 << 31

FW_START_OVERRIDE = 1 << 0
FW_START_WORKING_PDA_CR4 = 1 << 2

FW_FEATURE_SET_ENCRYPT = 1 << 0
FW_FEATURE_SET_KEY_IDX = 0x6  # GENMASK(2,1)
FW_FEATURE_ENCRY_MODE = 1 << 4
FW_FEATURE_OVERRIDE_ADDR = 1 << 5
FW_FEATURE_NON_DL = 1 << 6

PATCH_SEC_TYPE_MASK = 0xFFFF
PATCH_SEC_TYPE_INFO = 0x2
PATCH_SEC_NOT_SUPPORT = 0xFFFFFFFF
PATCH_SEC_ENC_TYPE_PLAIN = 0x00
PATCH_SEC_ENC_TYPE_AES = 0x01
PATCH_SEC_ENC_TYPE_SCRAMBLE = 0x02

MCU_TXD_LEN = 64  # sizeof(struct mt76_connac2_mcu_txd)
MCU_RXD_LEN = 36  # sizeof(struct mt76_connac2_mcu_rxd) header
SDIO_HDR_LEN = 4  # MT_SDIO_HDR_SIZE, on the TX side only

# On RX there is no separate header to skip: mt7921u sets MT_DRV_RX_DMA_HDR, so
# mt76 keeps zero head room and mt7921_queue_rx_skb reads rxd[0] directly off
# the bulk transfer. The DMA length word is rxd[0]'s low half.
RXD_SEQ_OFFSET = 29  # rxd[6] (24) + len,pkt_type_id (4) + eid (1)
PKT_TYPE_RX_EVENT = 7  # MT_RXD0_PKT_TYPE value carrying an MCU reply
# rx_pkt_type values (mt76_connac2_mac.h). A received 802.11 frame is PKT_TYPE_NORMAL, or
# PKT_TYPE_RX_EVENT with MT_RXD0_PKT_FLAG == 1 (the "NORMAL_MCU" case that rxd.decode also
# remaps). Anything else on the RX endpoint is a status or notification packet (TXS,
# TXRXV, TXRX_NOTIFY, ...).
PKT_TYPE_NORMAL = 2
RXD0_PKT_FLAG_SHIFT, RXD0_PKT_FLAG_MASK = 16, 0xF  # MT_RXD0_PKT_FLAG GENMASK(19, 16)
PKT_FLAG_NORMAL_MCU = 1
RXD_STATUS_OFFSET = 32  # skb_pull(sizeof(*rxd) - 4) in mt7921_mcu_parse_response
FW_SCATTER_MAX = 4096  # max_len for non-SDIO


class McuError(RuntimeError):
    pass


class Mt7921uMcu(Mt7921u):
    """Adds the MCU command/response layer on top of register access.

    The class attributes are the chip's MCU framing geometry. The defaults are the
    connac2 (MT7921) values; mt7925u overrides them for connac3.
    """

    # struct mt76_connac2_mcu_txd word 1, written by mt76_connac2_mcu_fill_message.
    TXD1 = MCU_TXD1_CONNAC2
    # Reply header: sizeof(struct mt76_connac2_mcu_rxd), and where seq and the
    # patch-semaphore status byte sit in the raw transfer (mt7921_mcu_parse_response).
    MCU_RXD_LEN = MCU_RXD_LEN
    RXD_SEQ_OFFSET = RXD_SEQ_OFFSET
    RXD_STATUS_OFFSET = RXD_STATUS_OFFSET

    def __init__(self, verbose: bool = False, usb_id: str | None = None):
        super().__init__(verbose=verbose, usb_id=usb_id)
        self.msg_seq = 0
        self.evt_ep4 = False  # set once dma_rx_evt_ep4 has run
        # Counters for what mcu_wait throws away while hunting for a reply on the
        # shared RX endpoint. Cumulative over the object lifetime; callers snapshot
        # before and after a command to attribute drops to it.
        self.mcu_wait_dropped_frames = 0  # received 802.11 frames (NORMAL or NORMAL_MCU)
        self.mcu_wait_stale_events = 0  # MCU events whose sequence did not match
        self.mcu_wait_other_packets = 0  # status/notification packets (TXS, TXRXV, ...)

    def _next_seq(self) -> int:
        self.msg_seq = (self.msg_seq + 1) & 0xF
        if self.msg_seq == 0:
            self.msg_seq = (self.msg_seq + 1) & 0xF
        return self.msg_seq

    def _build_mcu_txd(
        self,
        total_len: int,
        cid: int,
        seq: int,
        ext_cid: int = 0,
        set_query: int = MCU_Q_NA,
        s2d: int = MCU_S2D_H2N,
    ) -> bytes:
        """mt76_connac2_mcu_fill_message, non-UNI path."""
        txd = [0] * 8
        # MT_TXD0: TX_BYTES GENMASK(15,0), PKT_FMT GENMASK(24,23), Q_IDX GENMASK(31,25)
        txd[0] = (
            (total_len & 0xFFFF)
            | ((MT_TX_TYPE_CMD & 0x3) << 23)
            | ((MT_TX_MCU_PORT_RX_Q0 & 0x7F) << 25)
        )
        txd[1] = self.TXD1

        out = b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in txd)
        # len is total minus the 32-byte txd[8] array
        pq_id = (MT_TX_PORT_IDX_MCU << 15) | (MT_TX_MCU_PORT_RX_Q0 << 10)
        out += struct.pack("<HH", (total_len - 32) & 0xFFFF, pq_id & 0xFFFF)
        out += struct.pack("<BBBB", cid & 0xFF, MCU_PKT_ID, set_query & 0xFF, seq & 0xFF)
        out += struct.pack("<BBBB", 0, ext_cid & 0xFF, s2d & 0xFF, 1 if ext_cid else 0)
        out += b"\x00" * 20  # rsv[5]
        if len(out) != MCU_TXD_LEN:
            raise RuntimeError(f"internal MCU TXD length {len(out)}, expected {MCU_TXD_LEN}")
        return out

    def mcu_send(self, cid: int, payload: bytes = b"", wait: bool = True, timeout: int = 3000):
        """One MCU command. Returns the response body, or None if wait=False."""
        seq = self._next_seq()

        if cid == MCU_CMD_FW_SCATTER:
            body = payload  # no mcu_txd for scatter
            ep = self.ep_out_ac_be
        else:
            total = MCU_TXD_LEN + len(payload)
            body = self._build_mcu_txd(total, cid, seq) + payload
            ep = self.ep_out_inband_cmd

        # mt792x_skb_add_usb_sdio_hdr: len in [15:0], pkt type in [17:16]
        hdr = struct.pack("<I", len(body) & 0xFFFF)
        frame = hdr + body

        # pad = round_up(len, 4) + 4 - len
        pad = ((len(frame) + 3) & ~3) + 4 - len(frame)
        frame += b"\x00" * pad

        if self.verbose:
            print(
                f"    mcu -> cid=0x{cid:02x} seq={seq} "
                f"payload={len(payload)}B frame={len(frame)}B ep=0x{ep:02x}"
            )

        self.bulk_out(ep, frame, timeout)
        if not wait:
            return None
        return self.mcu_wait(seq, cid, timeout)

    def mcu_wait(self, seq: int, cid: int, timeout: int = 3000) -> bytes:
        """Read one MCU response and check its sequence.

        Which endpoint answers depends on MT_WFDMA_HOST_CONFIG_USB_RXEVT_EP4_EN:
        with it set (what mt792xu_dma_init does) responses arrive on
        MT_EP_IN_PKT_RX, otherwise on MT_EP_IN_CMD_RESP. Measured both ways.
        """
        ep = self.ep_in_pkt_rx if self.evt_ep4 else self.ep_in_cmd_resp
        # Once RX events are routed to EP4, MCU responses and 802.11 frames
        # share one endpoint. Under load the response is buried in the frame
        # stream, so demultiplex on the descriptor's packet type rather than
        # reading once and hoping. Measured: on a busy channel a reply can sit
        # behind hundreds of frames.
        deadline = time.monotonic() + (timeout / 1000.0) * 4
        discarded = 0
        while time.monotonic() < deadline:
            try:
                raw = self.bulk_in(ep, 4096, timeout)
            except usb.core.USBError as exc:
                raise McuError(
                    f"cid 0x{cid:02x} seq {seq}: no response on ep "
                    f"0x{ep:02x} after {discarded} frames ({exc})"
                ) from exc
            if len(raw) < self.MCU_RXD_LEN:
                continue
            rxd0 = struct.unpack_from("<I", raw, 0)[0]
            pkt_type = (rxd0 >> 27) & 0x1F
            pkt_flag = (rxd0 >> RXD0_PKT_FLAG_SHIFT) & RXD0_PKT_FLAG_MASK
            is_frame = pkt_type == PKT_TYPE_NORMAL or (
                pkt_type == PKT_TYPE_RX_EVENT and pkt_flag == PKT_FLAG_NORMAL_MCU
            )
            if is_frame or pkt_type != PKT_TYPE_RX_EVENT:
                discarded += 1
                if is_frame:
                    self.mcu_wait_dropped_frames += 1
                else:
                    self.mcu_wait_other_packets += 1
                continue
            rseq = raw[self.RXD_SEQ_OFFSET]
            if self.verbose:
                print(f"    mcu <- {len(raw)}B seq={rseq} (want {seq}, {discarded} frames skipped)")
            if rseq == seq:
                return raw
            discarded += 1
            self.mcu_wait_stale_events += 1
        raise McuError(
            f"cid 0x{cid:02x}: no response matching seq {seq} ({discarded} frames skipped)"
        )

    def _status_byte(self, rxd: bytes) -> int:
        """PATCH_SEM_CONTROL / PATCH_FINISH_REQ return a status byte."""
        return rxd[self.RXD_STATUS_OFFSET]

    def reply_body(self, rxd: bytes) -> bytes:
        """The payload after the chip's MCU reply header (skb_pull(sizeof(*rxd)))."""
        return rxd[self.MCU_RXD_LEN :]

    # ---- firmware download commands ------------------------------------

    def patch_sem_ctrl(self, get: bool) -> int:
        op = PATCH_SEM_GET if get else PATCH_SEM_RELEASE
        rxd = self.mcu_send(MCU_CMD_PATCH_SEM_CONTROL, struct.pack("<I", op))
        return self._status_byte(rxd)

    def init_download(self, addr: int, length: int, mode: int) -> None:
        # is_connac2 is true for 0x7961, so addr 0x900000 uses PATCH_START_REQ
        cid = MCU_CMD_PATCH_START_REQ if addr == 0x900000 else MCU_CMD_TARGET_ADDRESS_LEN_REQ
        self.mcu_send(cid, struct.pack("<III", addr, length, mode))

    def send_firmware(self, data: bytes, max_len: int = FW_SCATTER_MAX) -> None:
        off = 0
        while off < len(data):
            n = min(max_len, len(data) - off)
            self.mcu_send(MCU_CMD_FW_SCATTER, data[off : off + n], wait=False)
            off += n

    def start_patch(self) -> int:
        rxd = self.mcu_send(MCU_CMD_PATCH_FINISH_REQ, struct.pack("<BBBB", 0, 0, 0, 0))
        return self._status_byte(rxd)

    def start_firmware(self, override: int, option: int) -> None:
        self.mcu_send(MCU_CMD_FW_START_REQ, struct.pack("<II", option, override))

    def nic_power_ctrl(self, power_mode: int = 1) -> None:
        """mt76_connac_mcu_restart. No response expected."""
        self.mcu_send(MCU_CMD_NIC_POWER_CTRL, struct.pack("<BBBB", power_mode, 0, 0, 0), wait=False)


# ---------------------------------------------------------------------------
# Firmware image parsing
# ---------------------------------------------------------------------------

PATCH_HDR_LEN = 96  # sizeof(struct mt76_connac2_patch_hdr)
PATCH_SEC_LEN = 64  # sizeof(struct mt76_connac2_patch_sec)
FW_TRAILER_LEN = 36  # sizeof(struct mt76_connac2_fw_trailer)
FW_REGION_LEN = 40  # sizeof(struct mt76_connac2_fw_region)


def parse_patch(blob: bytes) -> dict:
    """struct mt76_connac2_patch_hdr, big-endian fields."""
    if len(blob) < PATCH_HDR_LEN:
        raise ValueError(
            f"patch image is shorter than its {PATCH_HDR_LEN}-byte header ({len(blob)} bytes)"
        )
    build_date = blob[0:16].split(b"\x00")[0].decode("ascii", "replace")
    platform = blob[16:20].decode("ascii", "replace")
    hw_sw_ver, patch_ver = struct.unpack_from(">II", blob, 20)
    (checksum,) = struct.unpack_from(">H", blob, 28)
    _d_patch_ver, subsys, feature, n_region, crc = struct.unpack_from(">IIIII", blob, 32)
    table_end = PATCH_HDR_LEN + n_region * PATCH_SEC_LEN
    if table_end > len(blob):
        raise ValueError(f"patch section table needs {table_end} bytes, image has {len(blob)}")

    sections = []
    for i in range(n_region):
        base = PATCH_HDR_LEN + i * PATCH_SEC_LEN
        sec_type, offs, size = struct.unpack_from(">III", blob, base)
        addr, length, sec_key_idx, align_len = struct.unpack_from(">IIII", blob, base + 12)
        if offs > len(blob) or length > len(blob) - offs:
            raise ValueError(
                f"patch section {i} payload [{offs}, {offs + length}) exceeds "
                f"{len(blob)}-byte image"
            )
        sections.append(
            {
                "type": sec_type,
                "offs": offs,
                "size": size,
                "addr": addr,
                "len": length,
                "sec_key_idx": sec_key_idx,
                "align_len": align_len,
            }
        )
    return {
        "build_date": build_date,
        "platform": platform,
        "hw_sw_ver": hw_sw_ver,
        "patch_ver": patch_ver,
        "checksum": checksum,
        "subsys": subsys,
        "feature": feature,
        "n_region": n_region,
        "crc": crc,
        "sections": sections,
    }


def parse_ram(blob: bytes) -> dict:
    """struct mt76_connac2_fw_trailer at the tail, regions immediately before."""
    if len(blob) < FW_TRAILER_LEN:
        raise ValueError(
            f"RAM image is shorter than its {FW_TRAILER_LEN}-byte trailer ({len(blob)} bytes)"
        )
    t = len(blob) - FW_TRAILER_LEN
    chip_id, eco_code, n_region, format_ver, format_flag = struct.unpack_from("<BBBBB", blob, t)
    metadata_len = FW_TRAILER_LEN + n_region * FW_REGION_LEN
    if metadata_len > len(blob):
        raise ValueError(f"RAM region metadata needs {metadata_len} bytes, image has {len(blob)}")
    fw_ver = blob[t + 7 : t + 17].split(b"\x00")[0].decode("ascii", "replace")
    build_date = blob[t + 17 : t + 32].split(b"\x00")[0].decode("ascii", "replace")
    (crc,) = struct.unpack_from("<I", blob, t + 32)

    regions = []
    for i in range(n_region):
        base = t - (n_region - i) * FW_REGION_LEN
        decomp_crc, decomp_len, _decomp_blk_sz = struct.unpack_from("<III", blob, base)
        addr, length = struct.unpack_from("<II", blob, base + 16)
        feature_set, rtype = struct.unpack_from("<BB", blob, base + 24)
        regions.append(
            {
                "addr": addr,
                "len": length,
                "feature_set": feature_set,
                "type": rtype,
                "decomp_crc": decomp_crc,
                "decomp_len": decomp_len,
            }
        )
    payload_len = len(blob) - metadata_len
    declared_len = sum(region["len"] for region in regions)
    if declared_len > payload_len:
        raise ValueError(
            f"RAM regions declare {declared_len} payload bytes, image contains {payload_len}"
        )
    return {
        "chip_id": chip_id,
        "eco_code": eco_code,
        "n_region": n_region,
        "format_ver": format_ver,
        "format_flag": format_flag,
        "fw_ver": fw_ver,
        "build_date": build_date,
        "crc": crc,
        "regions": regions,
    }


def get_data_mode(sec_info: int) -> int:
    """mt76_connac2_get_data_mode, connac2 path."""
    mode = DL_MODE_NEED_RSP
    if sec_info == PATCH_SEC_NOT_SUPPORT:
        return mode
    enc = (sec_info >> 24) & 0xFF
    if enc == PATCH_SEC_ENC_TYPE_PLAIN:
        pass
    elif enc == PATCH_SEC_ENC_TYPE_AES:
        mode |= DL_MODE_ENCRYPT
        mode |= ((sec_info & 0x0F) << DL_MODE_KEY_IDX_SHIFT) & 0x6
        mode |= DL_MODE_RESET_SEC_IV
    elif enc == PATCH_SEC_ENC_TYPE_SCRAMBLE:
        mode |= DL_MODE_ENCRYPT | DL_CONFIG_ENCRY_MODE_SEL | DL_MODE_RESET_SEC_IV
    else:
        raise McuError(f"unsupported patch encryption type 0x{enc:02x}")
    return mode


def gen_dl_mode(feature_set: int, is_wa: bool = False) -> int:
    """mt76_connac_mcu_gen_dl_mode."""
    ret = 0
    if feature_set & FW_FEATURE_SET_ENCRYPT:
        ret |= DL_MODE_ENCRYPT | DL_MODE_RESET_SEC_IV
    if feature_set & FW_FEATURE_ENCRY_MODE:
        ret |= DL_CONFIG_ENCRY_MODE_SEL
    ret |= ((feature_set & FW_FEATURE_SET_KEY_IDX) >> 1) << DL_MODE_KEY_IDX_SHIFT
    ret |= DL_MODE_NEED_RSP
    if is_wa:
        ret |= DL_MODE_WORKING_PDA_CR4
    return ret


# ---------------------------------------------------------------------------
# Bring-up: reset, power on, DMA init, firmware download
#
# Follows mt7921u_probe (mt7921/usb.c) -> mt792xu_dma_init (mt792x_usb.c)
# -> mt7921u_mcu_init -> mt7921_run_firmware -> mt792x_load_firmware.
# ---------------------------------------------------------------------------

MT_TOP_MISC_FW_STATE = 0x7  # GENMASK(2,0)

MT_UDMA_WLCFG_1 = MT_UMAC(0x00C)
MT_WL_RX_AGG_PKT_LMT = 0xFF  # GENMASK(7,0)
MT_WL_TX_TMOUT_LMT = 0x0FFFFF00  # GENMASK(27,8)
MT_WL_RX_AGG_TO = 0xFF  # GENMASK(7,0)
MT_WL_RX_AGG_LMT = 0xFF00  # GENMASK(15,8)
MT_WL_TX_TMOUT_FUNC_EN = 1 << 16
MT_WL_RX_MPSZ_PAD0 = 1 << 18
MT_TICK_1US_EN = 1 << 20
MT792X_USB_TX_TIMEOUT_LIMIT = 50000

MT_WFDMA0_GLO_CFG_RX_DMA_BUSY = 1 << 3
MT_WFDMA0_GLO_CFG_FW_DWLD_BYPASS_DMASHDL = 1 << 9
MT_WFDMA0_GLO_CFG_OMIT_RX_INFO_PFET2 = 1 << 21
MT_WFDMA0_GLO_CFG_OMIT_RX_INFO = 1 << 27
MT_WFDMA0_GLO_CFG_OMIT_TX_INFO = 1 << 28

MT_WPDMA0_MAX_CNT_MASK = 0xFF
MT_WPDMA0_BASE_PTR_MASK = 0xFFFF0000
MT_WFDMA_DUMMY_CR = 0x54000000 + 0x120
MT_WFDMA_NEED_REINIT = 1 << 1
MT_WFDMA_HOST_CONFIG = 0x7C027030
MT_WFDMA_HOST_CONFIG_USB_RXEVT_EP4_EN = 1 << 6


def MT_DMA_SHDL(ofs: int) -> int:
    return 0x7C026000 + ofs


MT_DMASHDL_PAGE = MT_DMA_SHDL(0x00C)
MT_DMASHDL_GROUP_SEQ_ORDER = 1 << 16
MT_DMASHDL_REFILL = MT_DMA_SHDL(0x010)
MT_DMASHDL_REFILL_MASK = 0xFFFF0000
MT_DMASHDL_PKT_MAX_SIZE = MT_DMA_SHDL(0x01C)
MT_DMASHDL_PKT_MAX_SIZE_PLE = 0x00000FFF
MT_DMASHDL_PKT_MAX_SIZE_PSE = 0x0FFF0000


def MT_DMASHDL_GROUP_QUOTA(n: int) -> int:
    return MT_DMA_SHDL(0x020 + (n << 2))


def MT_DMASHDL_Q_MAP(n: int) -> int:
    return MT_DMA_SHDL(0x060 + (n << 2))


def MT_DMASHDL_SCHED_SET(n: int) -> int:
    return MT_DMA_SHDL(0x070 + (n << 2))


def MT_UWFDMA0_TX_RING_EXT_CTRL(n: int) -> int:
    return MT_UWFDMA0(0x600 + (n << 2))


class Mt7921uDevice(Mt7921uMcu):
    """Full bring-up through firmware download."""

    # ---- DMA -----------------------------------------------------------

    def dma_prefetch(self) -> None:
        for idx, cnt, base in (
            (0, 4, 0x080),
            (1, 4, 0x0C0),
            (2, 4, 0x100),
            (3, 4, 0x140),
            (4, 4, 0x180),
            (16, 4, 0x280),
            (17, 4, 0x2C0),
        ):
            self.rmw(
                MT_UWFDMA0_TX_RING_EXT_CTRL(idx),
                MT_WPDMA0_MAX_CNT_MASK | MT_WPDMA0_BASE_PTR_MASK,
                (cnt & 0xFF) | ((base << 16) & MT_WPDMA0_BASE_PTR_MASK),
            )

    def wfdma_init(self) -> None:
        """mt792xu_wfdma_init."""
        self.dma_prefetch()
        self.clear_bits(MT_UWFDMA0_GLO_CFG, MT_WFDMA0_GLO_CFG_OMIT_RX_INFO)
        self.set_bits(
            MT_UWFDMA0_GLO_CFG,
            MT_WFDMA0_GLO_CFG_OMIT_TX_INFO
            | MT_WFDMA0_GLO_CFG_OMIT_RX_INFO_PFET2
            | MT_WFDMA0_GLO_CFG_FW_DWLD_BYPASS_DMASHDL
            | MT_WFDMA0_GLO_CFG_TX_DMA_EN
            | MT_WFDMA0_GLO_CFG_RX_DMA_EN,
        )

        self.rmw(MT_DMASHDL_REFILL, MT_DMASHDL_REFILL_MASK, 0xFFE00000)
        self.clear_bits(MT_DMASHDL_PAGE, MT_DMASHDL_GROUP_SEQ_ORDER)
        self.rmw(
            MT_DMASHDL_PKT_MAX_SIZE, MT_DMASHDL_PKT_MAX_SIZE_PLE | MT_DMASHDL_PKT_MAX_SIZE_PSE, 1
        )  # PLE=1, PSE=0
        for i in range(5):
            self.wr(MT_DMASHDL_GROUP_QUOTA(i), 0x3 | (0xFFF << 16))
        for i in range(5, 16):
            self.wr(MT_DMASHDL_GROUP_QUOTA(i), 0)
        self.wr(MT_DMASHDL_Q_MAP(0), 0x32013201)
        self.wr(MT_DMASHDL_Q_MAP(1), 0x32013201)
        self.wr(MT_DMASHDL_Q_MAP(2), 0x55555444)
        self.wr(MT_DMASHDL_Q_MAP(3), 0x55555444)
        self.wr(MT_DMASHDL_SCHED_SET(0), 0x76540132)
        self.wr(MT_DMASHDL_SCHED_SET(1), 0xFEDCBA98)
        self.set_bits(MT_WFDMA_DUMMY_CR, MT_WFDMA_NEED_REINIT)

    def dma_rx_evt_ep4(self) -> None:
        """mt792xu_dma_rx_evt_ep4: route RX events to endpoint 4."""
        if not self.poll(MT_UWFDMA0_GLO_CFG, MT_WFDMA0_GLO_CFG_RX_DMA_BUSY, 0, 1000):
            raise RuntimeError("timeout waiting for RX DMA idle")
        self.clear_bits(MT_UWFDMA0_GLO_CFG, MT_WFDMA0_GLO_CFG_RX_DMA_EN)
        self.set_bits(MT_WFDMA_HOST_CONFIG, MT_WFDMA_HOST_CONFIG_USB_RXEVT_EP4_EN)
        self.set_bits(MT_UWFDMA0_GLO_CFG, MT_WFDMA0_GLO_CFG_RX_DMA_EN)
        self.evt_ep4 = True

    def epctl_rst_opt(self, reset: bool) -> None:
        """mt792xu_epctl_rst_opt."""
        mask = 0x3F0 | 0x700000  # GENMASK(9,4) | GENMASK(22,20)
        val = self.uhw_rr(MT_SSUSB_EPCTL_CSR_EP_RST_OPT)
        val = (val | mask) if reset else (val & ~mask & 0xFFFFFFFF)
        self.uhw_wr(MT_SSUSB_EPCTL_CSR_EP_RST_OPT, val)

    def dma_init(self, resume: bool = False) -> None:
        """mt792xu_dma_init."""
        self.wfdma_init()
        self.clear_bits(MT_UDMA_WLCFG_0, MT_WL_RX_FLUSH)
        self.set_bits(
            MT_UDMA_WLCFG_0, MT_WL_RX_EN | MT_WL_TX_EN | MT_WL_RX_MPSZ_PAD0 | MT_TICK_1US_EN
        )
        self.rmw(
            MT_UDMA_WLCFG_1,
            MT_WL_TX_TMOUT_LMT,
            (MT792X_USB_TX_TIMEOUT_LIMIT << 8) & MT_WL_TX_TMOUT_LMT,
        )
        self.set_bits(MT_UDMA_WLCFG_0, MT_WL_TX_TMOUT_FUNC_EN)
        self.clear_bits(MT_UDMA_WLCFG_0, MT_WL_RX_AGG_TO | MT_WL_RX_AGG_LMT)
        self.clear_bits(MT_UDMA_WLCFG_1, MT_WL_RX_AGG_PKT_LMT)
        if resume:
            return
        self.dma_rx_evt_ep4()
        self.epctl_rst_opt(False)

    # ---- firmware ------------------------------------------------------

    def load_patch(self, blob: bytes, log=print) -> None:
        """mt76_connac2_load_patch."""
        sem = self.patch_sem_ctrl(True)
        if sem == PATCH_IS_DL:
            log("  patch already downloaded")
            return
        if sem != PATCH_NOT_DL_SEM_SUCCESS:
            raise McuError(
                f"failed to get patch semaphore (status {sem}; "
                f"0=SEM_FAIL 1=IS_DL 2=SEM_SUCCESS 3=REL_SUCCESS)"
            )

        try:
            p = parse_patch(blob)
            log(
                f"  patch {p['build_date']} hw/sw 0x{p['hw_sw_ver']:08x}, {p['n_region']} region(s)"
            )
            for i, sec in enumerate(p["sections"]):
                if (sec["type"] & PATCH_SEC_TYPE_MASK) != PATCH_SEC_TYPE_INFO:
                    raise McuError(f"section {i} is not PATCH_SEC_TYPE_INFO")
                mode = get_data_mode(sec["sec_key_idx"])
                log(f"  section {i}: addr=0x{sec['addr']:08x} len={sec['len']:,} mode=0x{mode:08x}")
                self.init_download(sec["addr"], sec["len"], mode)
                self.send_firmware(blob[sec["offs"] : sec["offs"] + sec["len"]])
            st = self.start_patch()
            if st:
                raise McuError(f"PATCH_FINISH_REQ returned {st}")
            log("  patch started")
        finally:
            rel = self.patch_sem_ctrl(False)
            if rel != PATCH_REL_SEM_SUCCESS:
                log(f"  warning: patch semaphore release returned {rel}")

    def load_ram(self, blob: bytes, log=print) -> None:
        """mt76_connac2_load_ram + mt76_connac_mcu_send_ram_firmware."""
        r = parse_ram(blob)
        log(f"  ram fw {r['fw_ver']} built {r['build_date']}, {r['n_region']} regions")
        override = 0
        option = 0
        offset = 0
        for i, rg in enumerate(r["regions"]):
            mode = gen_dl_mode(rg["feature_set"])
            if rg["feature_set"] & FW_FEATURE_OVERRIDE_ADDR:
                override = rg["addr"]
            if rg["feature_set"] & FW_FEATURE_NON_DL:
                log(f"  region {i}: NON_DL, skipped ({rg['len']:,} bytes)")
                offset += rg["len"]
                continue
            log(f"  region {i}: addr=0x{rg['addr']:08x} len={rg['len']:,} mode=0x{mode:08x}")
            self.init_download(rg["addr"], rg["len"], mode)
            self.send_firmware(blob[offset : offset + rg["len"]])
            offset += rg["len"]

        if override:
            option |= FW_START_OVERRIDE
        log(f"  starting firmware: override=0x{override:08x} option=0x{option:x}")
        self.start_firmware(override, option)

    def bringup(self, patch_blob: bytes, ram_blob: bytes, log=print) -> None:
        """mt7921u_probe through mt7921u_mcu_init."""
        log("resetting USB device")
        try:
            self.dev.reset()
        except usb.core.USBError as exc:
            log(f"  usb reset returned {exc}; continuing")
        time.sleep(0.5)

        misc = self.rr(MT_CONN_ON_MISC)
        log(f"MT_CONN_ON_MISC = 0x{misc:08x}")
        if misc & MT_TOP_MISC2_FW_N9_RDY:
            # mt7921u_probe does the same truthiness test on the masked field,
            # so any retained FW_STATE bit means a WFSYS reset first.
            log("  retained FW_STATE bits; running WFSYS reset")
            self.wfsys_reset()
            log(f"  MT_CONN_ON_MISC = 0x{self.rr(MT_CONN_ON_MISC):08x}")

        log("powering on MCU")
        self.power_on()
        log(f"  MT_CONN_ON_MISC = 0x{self.rr(MT_CONN_ON_MISC):08x}")

        log("initialising DMA")
        self.dma_init(resume=False)

        # "force firmware operation mode into normal state, which should be
        # set before firmware download stage" (__mt7921_init_hardware)
        self.wr(MT_SWDEF_MODE, MT_SWDEF_NORMAL_MODE)

        log("enabling firmware download path")
        self.set_bits(MT_UDMA_TX_QSEL, MT_FW_DL_EN)

        log("restarting MCU before download")
        self.nic_power_ctrl(1)
        if not self.poll(MT_CONN_ON_MISC, MT_TOP_MISC_FW_STATE, MT_TOP_MISC2_FW_PWR_ON, 1000):
            log("  warning: MCU not reporting ready for download")

        log("loading ROM patch")
        self.load_patch(patch_blob, log=log)

        log("loading RAM firmware")
        self.load_ram(ram_blob, log=log)

        log("waiting for N9 ready")
        if not self.poll(MT_CONN_ON_MISC, MT_TOP_MISC2_FW_N9_RDY, MT_TOP_MISC2_FW_N9_RDY, 1500):
            raise RuntimeError(
                f"timeout waiting for N9_RDY (MT_CONN_ON_MISC = 0x{self.rr(MT_CONN_ON_MISC):08x})"
            )

        self.clear_bits(MT_UDMA_TX_QSEL, MT_FW_DL_EN)
        log("firmware is running")
        self.post_firmware_init(log)

    def post_firmware_init(self, log=print) -> None:
        """What __mt7921_init_hardware does once the firmware answers.

        Bands other than 2.4 GHz stay silent until the firmware has the calibration
        data. Measured: without this, channel 153 yields zero transfers while channel 6
        yields thousands.
        """
        self.get_nic_capability()
        self.set_eeprom()
        log("efuse pushed")


# ---------------------------------------------------------------------------
# WFSYS reset (mt792xu_wfsys_reset). The driver runs this whenever the chip
# comes up with any FW_STATE bits already set, which is the normal case on a
# re-run without a physical replug.
# ---------------------------------------------------------------------------

MT_CBTOP_RGU_WF_SUBSYS_RST = 0x70002000 + 0x600
MT_CBTOP_RGU_WF_SUBSYS_RST_WF_WHOLE_PATH = 1 << 0
MT_UDMA_CONN_INFRA_STATUS_SEL = MT_UMAC(0xA24)
MT_WL_RX_BUSY = 1 << 30
MT_WL_TX_BUSY = 1 << 31
MT792x_WFSYS_INIT_RETRY_COUNT = 2
MT792X_USB_UDMA_IDLE_TIMEOUT = 1000


def _wait_udma_idle(self) -> None:
    """mt792xu_wait_udma_idle."""
    self.set_bits(MT_UDMA_WLCFG_0, MT_WL_RX_FLUSH)
    if not self.poll(
        MT_UDMA_WLCFG_0, MT_WL_RX_BUSY | MT_WL_TX_BUSY, 0, MT792X_USB_UDMA_IDLE_TIMEOUT
    ):
        val = self.rr(MT_UDMA_WLCFG_0)
        print(f"  warning: UDMA busy before WFSYS reset, WLCFG0=0x{val:08x}")


def _wfsys_reset(self) -> None:
    """mt792xu_wfsys_reset, driven by the class's WFSYS_* descriptor
    (struct mt792xu_wfsys_desc; mt7921_wfsys_desc is the default below).

    Note the reset register is reached through the UHW (USB host wrapper)
    vendor request pair, not the normal one.
    """
    self.wait_udma_idle()
    self.epctl_rst_opt(False)

    val = self.uhw_rr(self.WFSYS_RST_REG)
    self.uhw_wr(self.WFSYS_RST_REG, val | MT_CBTOP_RGU_WF_SUBSYS_RST_WF_WHOLE_PATH)
    time.sleep(self.WFSYS_RST_DELAY_S)
    val = self.uhw_rr(self.WFSYS_RST_REG)
    self.uhw_wr(self.WFSYS_RST_REG, val & ~MT_CBTOP_RGU_WF_SUBSYS_RST_WF_WHOLE_PATH & 0xFFFFFFFF)

    if self.WFSYS_NEED_STATUS_SEL:
        self.uhw_wr(MT_UDMA_CONN_INFRA_STATUS_SEL, 0)

    for _ in range(MT792x_WFSYS_INIT_RETRY_COUNT):
        val = self.uhw_rr(self.WFSYS_DONE_REG)
        if (val & self.WFSYS_DONE_MASK) == self.WFSYS_DONE_VAL:
            return
        time.sleep(0.1)
    raise RuntimeError("timeout waiting for WFSYS init done")


# mt7921_wfsys_desc (mt792x_usb.c:375-382 at c5a3bd91): done when BIT(22) of the
# UDMA status register is set, after selecting status page 0; usleep_range(10, 20)
# between asserting and releasing the reset.
Mt7921uDevice.WFSYS_RST_REG = MT_CBTOP_RGU_WF_SUBSYS_RST
Mt7921uDevice.WFSYS_DONE_REG = MT_UDMA_CONN_INFRA_STATUS
Mt7921uDevice.WFSYS_DONE_MASK = MT_UDMA_CONN_WFSYS_INIT_DONE
Mt7921uDevice.WFSYS_DONE_VAL = MT_UDMA_CONN_WFSYS_INIT_DONE
Mt7921uDevice.WFSYS_RST_DELAY_S = 0.001
Mt7921uDevice.WFSYS_NEED_STATUS_SEL = True


Mt7921uDevice.wait_udma_idle = _wait_udma_idle
Mt7921uDevice.wfsys_reset = _wfsys_reset


# ---------------------------------------------------------------------------
# Full command-word encoding (MCU_CMD / MCU_EXT_CMD / MCU_CE_CMD) and the
# post-firmware commands: capability query and channel set.
# ---------------------------------------------------------------------------

MCU_CMD_FIELD_ID = 0x000000FF
MCU_CMD_FIELD_EXT_ID = 0x0000FF00
MCU_CMD_FIELD_QUERY = 1 << 16
MCU_CMD_FIELD_UNI = 1 << 17
MCU_CMD_FIELD_CE = 1 << 18
MCU_CMD_FIELD_WA = 1 << 19
MCU_CMD_FIELD_WM = 1 << 20

MCU_CMD_EXT_CID = 0xED
MCU_EXT_CMD_CHANNEL_SWITCH = 0x08
MCU_EXT_CMD_SET_RX_PATH = 0x4E
MCU_CE_CMD_GET_NIC_CAPAB = 0x8A


def MCU_EXT_CMD(ext_id: int) -> int:
    return MCU_CMD_EXT_CID | ((ext_id << 8) & MCU_CMD_FIELD_EXT_ID)


def MCU_CE_CMD(ce_id: int) -> int:
    return MCU_CMD_FIELD_CE | (ce_id & MCU_CMD_FIELD_ID)


CMD_CBW_20MHZ, CMD_CBW_40MHZ, CMD_CBW_80MHZ, CMD_CBW_160MHZ = 0, 1, 2, 3
CMD_CBW_10MHZ, CMD_CBW_5MHZ, CMD_CBW_8080MHZ, CMD_CBW_320MHZ = 4, 5, 6, 7

CH_SWITCH_NORMAL = 0

NIC_CAP_NAMES = {
    0x00: "TX_RESOURCE",
    0x01: "TX_EFUSE_ADDR",
    0x02: "COEX",
    0x03: "SINGLE_SKU",
    0x04: "CSUM_OFFLOAD",
    0x05: "HW_VER",
    0x06: "SW_VER",
    0x07: "MAC_ADDR",
    0x08: "PHY",
    0x09: "MAC",
    0x0A: "FRAME_BUF",
    0x0B: "BEAM_FORM",
    0x0C: "LOCATION",
    0x0D: "MUMIMO",
    0x0E: "BUFFER_MODE_INFO",
    0x14: "HW_ADIE_VERSION",
    0x16: "ANTSWP",
    0x17: "WFDMA_REALLOC",
    0x18: "6G",
    0x20: "CHIP_CAP",
    0x22: "EML_CAP",
}


def _mcu_cmd_word(self, cmd: int, payload: bytes = b"", wait: bool = True, timeout: int = 3000):
    """mcu_send for a full command word, decoding it as fill_message does."""
    cid = cmd & MCU_CMD_FIELD_ID
    ext_cid = (cmd & MCU_CMD_FIELD_EXT_ID) >> 8

    if ext_cid or (cmd & MCU_CMD_FIELD_CE):
        set_query = MCU_Q_QUERY if (cmd & MCU_CMD_FIELD_QUERY) else MCU_Q_SET
    else:
        set_query = MCU_Q_NA
    s2d = MCU_S2D_H2C if (cmd & MCU_CMD_FIELD_WA) else MCU_S2D_H2N

    seq = self._next_seq()
    total = MCU_TXD_LEN + len(payload)
    body = (
        self._build_mcu_txd(total, cid, seq, ext_cid=ext_cid, set_query=set_query, s2d=s2d)
        + payload
    )
    frame = struct.pack("<I", len(body) & 0xFFFF) + body
    frame += b"\x00" * (((len(frame) + 3) & ~3) + 4 - len(frame))

    if self.verbose:
        print(
            f"    mcu -> cmd=0x{cmd:06x} cid=0x{cid:02x} ext=0x{ext_cid:02x} "
            f"sq={set_query} seq={seq} {len(frame)}B"
        )
    self.bulk_out(self.ep_out_inband_cmd, frame, timeout)
    if not wait:
        return None
    return self.mcu_wait(seq, cid, timeout)


def _get_nic_capability(self) -> dict:
    """mt7921_mcu_get_nic_capability. Returns the decoded TLVs."""
    rxd = self.mcu_cmd_word(MCU_CE_CMD(MCU_CE_CMD_GET_NIC_CAPAB))
    body = self.reply_body(rxd)
    if len(body) < 4:
        raise McuError(f"capability response too short ({len(body)} bytes)")
    (n_element,) = struct.unpack_from("<H", body, 0)
    off = 4
    caps = {}
    for _ in range(n_element):
        if off + 8 > len(body):
            break
        ttype, tlen = struct.unpack_from("<II", body, off)
        off += 8
        if off + tlen > len(body):
            break
        caps[ttype] = body[off : off + tlen]
        off += tlen
    return caps


def _set_chan_info(
    self,
    control_ch: int,
    center_ch: int,
    bw: int,
    band: int,
    antenna_mask: int = 0x3,
    cmd_ext: int = MCU_EXT_CMD_CHANNEL_SWITCH,
    band_idx: int = 0,
) -> None:
    """mt7921_mcu_set_chan_info.

    band: 0 = 2.4 GHz, 1 = 5 GHz, 2 = 6 GHz (channel_band encoding).
    Monitor mode always uses CH_SWITCH_NORMAL.
    """
    rx_streams = antenna_mask.bit_count() if cmd_ext == MCU_EXT_CMD_CHANNEL_SWITCH else antenna_mask
    req = struct.pack(
        "<BBBBBBBB",
        control_ch & 0xFF,
        center_ch & 0xFF,
        bw & 0xFF,
        antenna_mask.bit_count() & 0xFF,  # tx_streams_num
        rx_streams & 0xFF,
        CH_SWITCH_NORMAL,
        band_idx & 0xFF,
        0,  # center_ch2
    )
    req += struct.pack("<HBB", 0, band & 0xFF, 0)  # cac_case, channel_band, rsv0
    req += struct.pack("<I", 0)  # outband_freq
    req += struct.pack("<BBB", 0, 0, 0)  # txpower_drop, ap_bw, ap_center_ch
    req += b"\x00" * 57  # rsv1
    if len(req) != 76:  # 19 bytes of fields + rsv1[57]
        raise RuntimeError(f"internal channel request length {len(req)}, expected 76")
    self.mcu_cmd_word(MCU_EXT_CMD(cmd_ext), req)


Mt7921uDevice.mcu_cmd_word = _mcu_cmd_word
Mt7921uDevice.get_nic_capability = _get_nic_capability
Mt7921uDevice.set_chan_info = _set_chan_info


# ---------------------------------------------------------------------------
# RX filter and monitor mode
# ---------------------------------------------------------------------------

MCU_CE_CMD_SET_RX_FILTER = 0x0A

# mt7921_configure_filter's local defines
MT7921_FILTER_FCSFAIL = 1 << 2
MT7921_FILTER_CONTROL = 1 << 5
MT7921_FILTER_OTHER_BSS = 1 << 6
MT7921_FILTER_ENABLE = 1 << 31

# What mac80211 asks for on a monitor interface: FIF_OTHER_BSS | FIF_FCSFAIL |
# FIF_CONTROL, which mt7921_configure_filter turns into these bits.
MONITOR_FILTER = (
    MT7921_FILTER_ENABLE | MT7921_FILTER_FCSFAIL | MT7921_FILTER_CONTROL | MT7921_FILTER_OTHER_BSS
)


def _set_rxfilter(self, fif: int, bit_op: int = 0, bit_map: int = 0) -> None:
    """mt7921_mcu_set_rxfilter. Sent without waiting, as the driver does."""
    data = b"\x00" * 4  # rsv[4]
    data += struct.pack("<B", 1 if fif else 2)  # mode
    data += b"\x00" * 3  # rsv2[3]
    data += struct.pack("<II", fif & 0xFFFFFFFF, bit_map & 0xFFFFFFFF)
    data += struct.pack("<B", bit_op & 0xFF)
    data += b"\x00" * 51  # pad
    if len(data) != 68:  # 17 bytes of fields + pad[51]
        raise RuntimeError(f"internal RX filter length {len(data)}, expected 68")
    self.mcu_cmd_word(MCU_CE_CMD(MCU_CE_CMD_SET_RX_FILTER), data, wait=False)


def _rx_read(self, timeout: int = 1000, size: int = 8192) -> bytes:
    """One bulk read off the 802.11 receive endpoint."""
    return self.bulk_in(self.ep_in_pkt_rx, size, timeout)


Mt7921uDevice.set_rxfilter = _set_rxfilter
Mt7921uDevice.rx_read = _rx_read


# ---------------------------------------------------------------------------
# Hardware RX drop bits (MT_WF_RFCR). The FIF flags above are not enough on
# their own: the RFCR bitmap independently drops beacons from other BSSes,
# which is exactly what a survey wants to keep.
# ---------------------------------------------------------------------------

MT7921_FIF_BIT_SET = 1 << 0
MT7921_FIF_BIT_CLR = 1 << 1

MT_WF_RFCR_DROP_STBC_MULTI = 1 << 0
MT_WF_RFCR_DROP_FCSFAIL = 1 << 1
MT_WF_RFCR_DROP_VERSION = 1 << 3
MT_WF_RFCR_DROP_PROBEREQ = 1 << 4
MT_WF_RFCR_DROP_MCAST = 1 << 5
MT_WF_RFCR_DROP_BCAST = 1 << 6
MT_WF_RFCR_DROP_MCAST_FILTERED = 1 << 7
MT_WF_RFCR_DROP_A3_MAC = 1 << 8
MT_WF_RFCR_DROP_A3_BSSID = 1 << 9
MT_WF_RFCR_DROP_A2_BSSID = 1 << 10
MT_WF_RFCR_DROP_OTHER_BEACON = 1 << 11
MT_WF_RFCR_DROP_FRAME_REPORT = 1 << 12
MT_WF_RFCR_DROP_CTL_RSV = 1 << 13
MT_WF_RFCR_DROP_CTS = 1 << 14
MT_WF_RFCR_DROP_RTS = 1 << 15
MT_WF_RFCR_DROP_DUPLICATE = 1 << 16
MT_WF_RFCR_DROP_OTHER_BSS = 1 << 17
MT_WF_RFCR_DROP_OTHER_UC = 1 << 18
MT_WF_RFCR_DROP_OTHER_TIM = 1 << 19
MT_WF_RFCR_DROP_NDPA = 1 << 20
MT_WF_RFCR_DROP_UNWANTED_CTL = 1 << 21

# Everything a passive survey wants to stop the MAC discarding.
MONITOR_DROP_CLEAR = (
    MT_WF_RFCR_DROP_STBC_MULTI
    | MT_WF_RFCR_DROP_VERSION
    | MT_WF_RFCR_DROP_PROBEREQ
    | MT_WF_RFCR_DROP_MCAST
    | MT_WF_RFCR_DROP_BCAST
    | MT_WF_RFCR_DROP_MCAST_FILTERED
    | MT_WF_RFCR_DROP_A3_MAC
    | MT_WF_RFCR_DROP_A3_BSSID
    | MT_WF_RFCR_DROP_A2_BSSID
    | MT_WF_RFCR_DROP_OTHER_BEACON
    | MT_WF_RFCR_DROP_CTL_RSV
    | MT_WF_RFCR_DROP_DUPLICATE
    | MT_WF_RFCR_DROP_OTHER_BSS
    | MT_WF_RFCR_DROP_OTHER_UC
    | MT_WF_RFCR_DROP_OTHER_TIM
    | MT_WF_RFCR_DROP_UNWANTED_CTL
)


def _set_monitor_mode(self) -> None:
    """Open the receiver as wide as the MAC allows.

    Two commands, because they use different modes of SET_RX_FILTER: mode 1
    sets the FIF flag word, mode 2 edits the RFCR drop bitmap.
    """
    self.set_rxfilter(MONITOR_FILTER)
    self.set_rxfilter(0, MT7921_FIF_BIT_CLR, MONITOR_DROP_CLEAR)


Mt7921uDevice.set_monitor_mode = _set_monitor_mode


# ---------------------------------------------------------------------------
# UNI commands and sniffer mode
#
# Opening the MAC's RFCR filter is not enough on its own: the firmware still
# consumes beacons until it is put into sniffer mode explicitly, via
# MCU_UNI_CMD(SNIFFER). mt7921_mcu_set_sniffer enables it and
# mt7921_mcu_config_sniffer tells it which channel to sniff.
# ---------------------------------------------------------------------------

MCU_CMD_ACK = 1 << 0
MCU_CMD_UNI = 1 << 1
MCU_CMD_SET = 1 << 2
MCU_CMD_UNI_EXT_ACK = MCU_CMD_ACK | MCU_CMD_UNI | MCU_CMD_SET

MCU_UNI_CMD_SNIFFER = 0x24
MCU_UNI_TXD_LEN = 48  # sizeof(struct mt76_connac2_mcu_uni_txd)

# mt7921_mcu_config_sniffer uses its own band and width encodings, which are
# NOT the ones mt7921_mcu_set_chan_info uses.
SNIFFER_BAND = {"2.4GHz": 1, "5GHz": 2, "6GHz": 3}
SNIFFER_BW_20 = 0
SNIFFER_BW_80 = 1
SNIFFER_BW_160 = 2


def _uni_option(self, cid: int, query: bool = False) -> int:
    """The uni_txd option byte. mt7921 always asks for an extended ack."""
    return MCU_CMD_UNI_EXT_ACK


def _build_uni_txd(self, total_len: int, cid: int, seq: int, query: bool = False) -> bytes:
    """mt76_connac2_mcu_fill_message, UNI path (struct mt76_connac2_mcu_uni_txd)."""
    txd = [0] * 8
    txd[0] = (
        (total_len & 0xFFFF)
        | ((MT_TX_TYPE_CMD & 0x3) << 23)
        | ((MT_TX_MCU_PORT_RX_Q0 & 0x7F) << 25)
    )
    txd[1] = self.TXD1
    out = b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in txd)
    out += struct.pack("<HH", (total_len - 32) & 0xFFFF, cid & 0xFFFF)
    out += struct.pack("<BBBB", 0, MCU_PKT_ID, 0, seq & 0xFF)
    out += struct.pack("<HBB", 0, MCU_S2D_H2N, self.uni_option(cid, query))
    out += b"\x00" * 4
    if len(out) != MCU_UNI_TXD_LEN:
        raise RuntimeError(f"internal UNI TXD length {len(out)}, expected {MCU_UNI_TXD_LEN}")
    return out


def _mcu_uni(
    self, cid: int, payload: bytes, wait: bool = True, timeout: int = 3000, query: bool = False
):
    """One UNI command. query=True marks a __MCU_CMD_FIELD_QUERY command word."""
    seq = self._next_seq()
    total = MCU_UNI_TXD_LEN + len(payload)
    body = self._build_uni_txd(total, cid, seq, query=query) + payload
    frame = struct.pack("<I", len(body) & 0xFFFF) + body
    frame += b"\x00" * (((len(frame) + 3) & ~3) + 4 - len(frame))
    if self.verbose:
        print(f"    uni -> cid=0x{cid:02x} seq={seq} {len(frame)}B")
    self.bulk_out(self.ep_out_inband_cmd, frame, timeout)
    if not wait:
        return None
    return self.mcu_wait(seq, cid, timeout)


def _set_sniffer(self, enable: bool, band_idx: int = 0) -> None:
    """mt7921_mcu_set_sniffer."""
    hdr = struct.pack("<B3x", band_idx)
    tlv = struct.pack("<HHB3x", 0, 8, 1 if enable else 0)
    self.mcu_uni(MCU_UNI_CMD_SNIFFER, hdr + tlv)


def _config_sniffer(
    self,
    control_ch: int,
    center_ch: int,
    band_name: str,
    bw: int = SNIFFER_BW_20,
    center_ch2: int = 0,
    drop_err: int = 1,
    band_idx: int = 0,
) -> None:
    """mt7921_mcu_config_sniffer."""
    sco = 0
    if control_ch < center_ch:
        sco = 1  # SCA
    elif control_ch > center_ch:
        sco = 3  # SCB
    hdr = struct.pack("<B3x", band_idx)
    tlv = struct.pack(
        "<HHHBBBBBBB3x",
        1,  # tag
        16,  # len: sizeof(config_tlv)
        0,  # aid
        SNIFFER_BAND[band_name],
        bw,
        control_ch,
        sco,
        center_ch,
        center_ch2,
        drop_err,
    )
    if len(tlv) != 16:
        raise RuntimeError(f"internal sniffer TLV length {len(tlv)}, expected 16")
    self.mcu_uni(MCU_UNI_CMD_SNIFFER, hdr + tlv)


# Channel tuning shared by both chips. Width in MHz maps to two different enums:
# CMD_CBW_* for mt7921_mcu_set_chan_info and the sniffer TLV's own table, in which 40 MHz
# is encoded as 20 with the offset carried by sco (mt7921/mt7925 mcu_config_sniffer ch_width[]).
CHAN_BAND = {"2.4GHz": 0, "5GHz": 1, "6GHz": 2}  # channel_band field of set_chan_info

# Valid center channels per band and width. A wide PPDU is described by its control
# channel plus the center of the block it sits in; the driver needs the center, and an
# operator watching a roam knows only the control channel the AP advertises.
#
# 5 GHz centers are the operating-class definitions quoted in hostapd
# src/common/ieee802_11_common.c: class 126/127 (40 MHz), class 128 (80 MHz, centers
# 42, 58, 106, 122, 138, 155, 171), class 129 (160 MHz, centers 50, 114, 163).
# 6 GHz centers follow center_idx_to_bw_6ghz() in the same file: a center index is
# 40 MHz when (idx & 0x7) == 0x3, 80 MHz when (idx & 0xf) == 0x7, and 160 MHz when
# (idx & 0x1f) == 0xf. Both fetched 2026-09-03.
# A block of width W spans W/5 channel numbers, so a control channel belongs to the
# block whose center it is within (W/5 - 2) / 2 channel numbers of.
CENTER_CHANNELS = {
    ("5GHz", 40): (38, 46, 54, 62, 102, 110, 118, 126, 134, 142, 151, 159, 167),
    ("5GHz", 80): (42, 58, 106, 122, 138, 155, 171),
    ("5GHz", 160): (50, 114, 163),
    # 6 GHz 20 MHz control channels run 1 to 233 in steps of 4 (plus the standalone
    # channel 2), so a block is only real when its outermost control channel is still
    # within the band: centers stop at 227 for 40 MHz, 215 for 80 MHz, and 207 for
    # 160 MHz. That gives the 29, 14, and 7 channels the band is defined to have.
    ("6GHz", 40): tuple(range(3, 228, 8)),
    ("6GHz", 80): tuple(range(7, 216, 16)),
    ("6GHz", 160): tuple(range(15, 208, 32)),
}
SIX_GHZ_MAX_CHANNEL = 233


def center_channel(band_name: str, control_ch: int, width_mhz: int) -> int | None:
    """The center channel of the `width_mhz` block containing `control_ch`.

    Returns None when no block of that width contains the control channel, which
    includes every 2.4 GHz width above 20 MHz: a 2.4 GHz 40 MHz channel may extend
    either upward or downward from its control channel, and the control channel alone
    does not say which. Callers must fail rather than pick one.
    """
    if width_mhz == 20:
        return control_ch
    centers = CENTER_CHANNELS.get((band_name, width_mhz))
    if centers is None:
        return None
    reach = (width_mhz // 5 - 2) // 2  # channel numbers from the center to the outermost 20 MHz
    for center in centers:
        offset = control_ch - center
        # The 20 MHz control channels of a wide block sit at odd multiples of 2 channel
        # numbers from its center, so a valid offset is even with an odd half. Testing
        # only the distance would accept a channel that is not a control channel of any
        # block: 6 GHz channel 2 is five channel numbers from center 7 and is defined as
        # 20 MHz only (center_idx_to_bw_6ghz() returns 20 MHz for idx == 2).
        if abs(offset) <= reach and offset % 4 == 2:
            return center
    return None


WIDTH_TO_CMD_CBW = {20: CMD_CBW_20MHZ, 40: CMD_CBW_40MHZ, 80: CMD_CBW_80MHZ, 160: CMD_CBW_160MHZ}
WIDTH_TO_SNIFFER_BW = {20: SNIFFER_BW_20, 40: SNIFFER_BW_20, 80: SNIFFER_BW_80, 160: SNIFFER_BW_160}


def _tune(self, band_name: str, control_ch: int, center_ch: int | None = None, width_mhz: int = 20):
    """Put the sniffer on one channel: mt7921 needs CHANNEL_SWITCH then the sniffer CONFIG
    TLV; mt7925 overrides this with the TLV alone. center_ch defaults to control_ch."""
    if band_name not in CHAN_BAND:
        raise ValueError(f"band must be one of {sorted(CHAN_BAND)}, got {band_name!r}")
    if width_mhz not in WIDTH_TO_SNIFFER_BW:
        raise ValueError(f"width must be one of {sorted(WIDTH_TO_SNIFFER_BW)} MHz, got {width_mhz}")
    if center_ch is None:
        center_ch = control_ch
    self.set_chan_info(
        control_ch=control_ch,
        center_ch=center_ch,
        bw=WIDTH_TO_CMD_CBW[width_mhz],
        band=CHAN_BAND[band_name],
    )
    self.config_sniffer(
        control_ch=control_ch,
        center_ch=center_ch,
        band_name=band_name,
        bw=WIDTH_TO_SNIFFER_BW[width_mhz],
    )


Mt7921uDevice.uni_option = _uni_option
Mt7921uDevice._build_uni_txd = _build_uni_txd
Mt7921uDevice.mcu_uni = _mcu_uni
Mt7921uDevice.set_sniffer = _set_sniffer
Mt7921uDevice.config_sniffer = _config_sniffer
Mt7921uDevice.tune = _tune


# ---------------------------------------------------------------------------
# Post-firmware hardware init (__mt7921_init_hardware).
#
# MT_SWDEF_MODE must be written BEFORE the firmware download, per the comment
# in the driver. EFUSE_BUFFER_MODE pushes the calibration data the radio needs
# for bands other than 2.4 GHz.
# ---------------------------------------------------------------------------

MT_SWDEF_MODE = 0x41F200 + 0x3C
MT_SWDEF_NORMAL_MODE = 0

MCU_EXT_CMD_EFUSE_BUFFER_MODE = 0x21
EE_MODE_EFUSE = 0
EE_MODE_BUFFER = 1
EE_FORMAT_BIN = 0
EE_FORMAT_WHOLE = 1
EE_FORMAT_MULTIPLE = 2


def _set_eeprom(self) -> None:
    """mt7921_mcu_set_eeprom: hand the firmware the whole efuse."""
    req = struct.pack("<BBH", EE_MODE_EFUSE, EE_FORMAT_WHOLE, 0)
    self.mcu_cmd_word(MCU_EXT_CMD(MCU_EXT_CMD_EFUSE_BUFFER_MODE), req)


Mt7921uDevice.set_eeprom = _set_eeprom


# ---------------------------------------------------------------------------
# Transmit path (mt7921_usb_sdio_tx_prepare_skb -> mt76_connac2_mac_write_txwi).
#
# Present to characterise the radio, not to build tooling with. The only frame
# this module knows how to construct is a Probe Request, which is what every
# station on earth emits continuously and which asks an AP a question it is
# designed to answer. That makes it the cleanest possible proof that a frame
# reached the air: the AP replies to us by name.
#
# Linux active-monitor failure is tracked separately in openwrt/mt76 issue #839;
# upstream commit 9de65849 stopped advertising that generic feature on MT792x.
# The Linux "injection kills the chip" reports are a host-driver NULL dereference in the
# TXRX_NOTIFY path (upstream d367ee6d, in this repo's baseline), not an MCU fault, and do
# not apply to this userspace path. Here only 60 frames at 50 ms spacing have been sent,
# with the chip alive after; anything sustained or faster is untested. See RELATED_WORK.md
# and ROADMAP.md.
# ---------------------------------------------------------------------------

MT_TXD_SIZE = 32
MT_SDIO_TXD_SIZE = MT_TXD_SIZE + 8 * 4  # 64

MT_TXD0_TX_BYTES_M = 0xFFFF
MT_TX_TYPE_SF = 1
MT_LMAC_ALTX0 = 0x10

MT_TXD1_OWN_MAC_SHIFT = 24
MT_TXD1_TID_SHIFT = 20
MT_TXD1_HDR_INFO_SHIFT = 11
MT_HDR_FORMAT_802_11 = 2

MT_TXD2_FIX_RATE = 1 << 31
MT_TXD2_HTC_VLD = 1 << 13
MT_TXD2_MULTICAST = 1 << 10
MT_TXD2_FRAME_TYPE_SHIFT = 4
MT_TXD2_SUB_TYPE_SHIFT = 0

MT_TXD3_SN_VALID = 1 << 31
MT_TXD3_SEQ_SHIFT = 16
MT_TXD3_BA_DISABLE = 1 << 28
MT_TXD3_REM_TX_COUNT_SHIFT = 11
MT_TXD3_NO_ACK = 1 << 0

MT_TXD5_TX_STATUS_HOST = 1 << 10
MT_PACKET_ID_FIRST = 3
MT_TXD6_FIXED_BW = 1 << 2
MT_TXD6_TX_RATE_SHIFT = 16

MT_TXD8_L_TYPE_SHIFT = 4
MT_TXD8_L_SUB_TYPE_SHIFT = 0

GLOBAL_WCID = 0  # "Beacon and mgmt frames should occupy wcid 0"
TX_RATE_1M_CCK = 0  # mt76_rates[0], CCK_RATE(0, 10): nss 0, mode 0, idx 0

# Candidate TX endpoints. mt76u_ac_to_hwq maps a queue to an index into
# out_ep[]; rather than reproduce that indirection, the test sweeps them.
TX_ENDPOINTS = [EP_OUT_AC_BE, 0x05, 0x06, 0x07, 0x09]


def build_probe_request(src_mac: bytes, ssid: bytes = b"", seq: int = 0) -> bytes:
    """A wildcard Probe Request: the least disruptive frame in 802.11."""
    if len(src_mac) != 6:
        raise ValueError("source MAC must be exactly 6 bytes")
    if len(ssid) > 32:
        raise ValueError("SSID must be at most 32 bytes")
    fc = 0x0040  # type 0 (mgmt), subtype 4 (probe req)
    hdr = struct.pack("<HH", fc, 0)
    hdr += b"\xff" * 6  # addr1 broadcast
    hdr += src_mac  # addr2
    hdr += b"\xff" * 6  # addr3 broadcast
    hdr += struct.pack("<H", (seq & 0xFFF) << 4)
    body = bytes([0, len(ssid)]) + ssid  # SSID element
    body += bytes([1, 4, 0x82, 0x84, 0x8B, 0x96])  # Supported Rates
    return hdr + body


def _build_txwi(self, frame: bytes, seq: int = 0, pid: int = 0) -> bytes:
    """mt76_connac2_mac_write_txwi for an injected management frame."""
    if len(frame) < 24:
        raise ValueError("injected 802.11 frame must include a 24-byte header")
    fc = struct.unpack_from("<H", frame, 0)[0]
    fc_type = (fc >> 2) & 0x3
    fc_stype = (fc >> 4) & 0xF
    hdrlen = 24
    multicast = frame[4] & 0x01

    txwi = [0] * 16  # 64 bytes

    txwi[0] = (
        ((len(frame) + MT_SDIO_TXD_SIZE) & MT_TXD0_TX_BYTES_M)
        | ((MT_TX_TYPE_SF & 0x3) << 23)
        | ((MT_LMAC_ALTX0 & 0x7F) << 25)
    )
    txwi[1] = (
        MT_TXD1_LONG_FORMAT
        | (GLOBAL_WCID & 0x3FF)
        | (0 << MT_TXD1_OWN_MAC_SHIFT)
        | (MT_HDR_FORMAT_802_11 << MT_TXD1_HDR_FORMAT_SHIFT)
        | ((hdrlen // 2) << MT_TXD1_HDR_INFO_SHIFT)
    )
    txwi[2] = (
        (fc_type << MT_TXD2_FRAME_TYPE_SHIFT)
        | (fc_stype << MT_TXD2_SUB_TYPE_SHIFT)
        | (MT_TXD2_MULTICAST if multicast else 0)
        | MT_TXD2_FIX_RATE  # set for anything that is not data
        | MT_TXD2_HTC_VLD
    )
    txwi[3] = (
        (15 << MT_TXD3_REM_TX_COUNT_SHIFT)
        | MT_TXD3_NO_ACK  # broadcast: nobody will ACK it
        | MT_TXD3_BA_DISABLE
        | MT_TXD3_SN_VALID
        | ((seq & 0xFFF) << MT_TXD3_SEQ_SHIFT)
    )
    # Requesting per-packet TX status is what makes the chip emit
    # PKT_TYPE_TXRX_NOTIFY. Off by default: we have no use for it, and on a
    # Linux host without d367ee6d that event is what oopses the RX worker.
    txwi[5] = pid & 0xFF
    if pid >= MT_PACKET_ID_FIRST:
        txwi[5] |= MT_TXD5_TX_STATUS_HOST
    txwi[6] = MT_TXD6_FIXED_BW | (TX_RATE_1M_CCK << MT_TXD6_TX_RATE_SHIFT)
    txwi[8] = (fc_type << MT_TXD8_L_TYPE_SHIFT) | (fc_stype << MT_TXD8_L_SUB_TYPE_SHIFT)

    return b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in txwi)


def _inject(self, frame: bytes, ep: int, seq: int = 0, pid: int = 0) -> None:
    """Frame it the way mt7921_usb_sdio_tx_prepare_skb does and send it."""
    body = self._build_txwi(frame, seq, pid) + frame
    hdr = struct.pack("<I", len(body) & 0xFFFF)
    out = hdr + body
    out += b"\x00" * ((((len(out) + 3) & ~3) - len(out)) + 4)
    self.bulk_out(ep, out, 1000)


def _alive(self) -> bool:
    """Is the chip still answering after a transmit attempt?"""
    try:
        return self.chip_id() in self.CHIP_IDS
    except Exception:
        return False


Mt7921uDevice._build_txwi = _build_txwi
Mt7921uDevice.inject = _inject
Mt7921uDevice.alive = _alive


# ---------------------------------------------------------------------------
# Housekeeping queries: die temperature and raw efuse
# ---------------------------------------------------------------------------

MCU_EXT_CMD_EFUSE_ACCESS = 0x01
MCU_EXT_CMD_THERMAL_CTRL = 0x2C
THERMAL_SENSOR_TEMP_QUERY = 0
MT7921_EEPROM_BLOCK_SIZE = 16
MT_EE_MAC_ADDR = 0x004
MT_EE_HW_TYPE = 0x55B


def _get_temperature(self):
    """mt7921_mcu_get_temperature. Degrees C, from the on-die sensor."""
    req = struct.pack("<BBB5x", THERMAL_SENSOR_TEMP_QUERY, 0, 0)
    rxd = self.mcu_cmd_word(MCU_EXT_CMD(MCU_EXT_CMD_THERMAL_CTRL), req)
    body = self.reply_body(rxd)
    # mt7921_mcu_parse_response pulls sizeof(rxd)+4 for THERMAL_CTRL
    if len(body) < 8:
        return None
    return struct.unpack_from("<i", body, 4)[0]


def _read_efuse(self, offset: int):
    """mt7921_mcu_read_eeprom: one 16-byte efuse block."""
    base = offset & ~(MT7921_EEPROM_BLOCK_SIZE - 1)
    req = struct.pack("<II", base, 0) + b"\x00" * MT7921_EEPROM_BLOCK_SIZE
    rxd = self.mcu_cmd_word(MCU_EXT_CMD(MCU_EXT_CMD_EFUSE_ACCESS) | MCU_CMD_FIELD_QUERY, req)
    body = self.reply_body(rxd)
    if len(body) < 8 + MT7921_EEPROM_BLOCK_SIZE:
        return None, None
    _addr, valid = struct.unpack_from("<II", body, 0)
    data = body[8 : 8 + MT7921_EEPROM_BLOCK_SIZE]
    return valid, data


Mt7921uDevice.get_temperature = _get_temperature
Mt7921uDevice.read_efuse = _read_efuse


# ---------------------------------------------------------------------------
# Device factory: pick the driver class from the attached device's USB id
# ---------------------------------------------------------------------------


@functools.cache
def _decoder(module_name: str):
    return importlib.import_module(module_name).decode


def decoder_for(dev) -> callable:
    """The RX descriptor decode() for a device object: rxd.decode for connac2 (MT7921),
    rxd_connac3.decode for connac3 (MT7925). Both return the same dict shape."""
    return _decoder(dev.DECODER_MODULE)


def device_class_for(chip: str):
    """The device class that drives one SUPPORTED_DEVICES chip name."""
    if chip == CHIP_MT7921:
        return Mt7921uDevice
    if chip == CHIP_MT7925:
        import mt7925u

        return mt7925u.Mt7925uDevice
    raise UnsupportedDevice(f"no driver class for chip {chip!r}")


def open_device(usb_id: str | None = None, verbose: bool = False):
    """Return an unopened device object of the right class for the attached adapter.

    Use it as a context manager exactly like Mt7921uDevice(). With several supported
    adapters attached, usb_id (or $MT76_USB_ID) picks one.
    """
    candidates = find_supported_devices(usb_id)
    if not candidates:
        wanted = usb_id or os.environ.get("MT76_USB_ID") or "any supported"
        raise UnsupportedDevice(f"device not found (looked for {wanted})")
    if len(candidates) > 1:
        ids = ", ".join(f"{d.idVendor:04x}:{d.idProduct:04x}" for d in candidates)
        raise UnsupportedDevice(
            f"{len(candidates)} supported devices attached ({ids}); "
            "pass usb_id or set MT76_USB_ID to pick one"
        )
    dev = candidates[0]
    chip = SUPPORTED_DEVICES[(dev.idVendor, dev.idProduct)]
    cls = device_class_for(chip)
    return cls(verbose=verbose, usb_id=f"{dev.idVendor:04x}:{dev.idProduct:04x}")
