# mt7921u-macos

A userspace 802.11 monitor-mode driver for MediaTek MT7921 USB adapters (such as the
ALFA AWUS036AXML) on macOS. **No kernel extension, no DriverKit, no virtual machine.**
It captures on 2.4, 5, and **6 GHz**, decodes management, data, and control frames, and
writes radiotap pcap that Wireshark reads.

The 6 GHz part is the reason this exists. Apple Silicon Macs ship a Wi-Fi 6 (not 6E)
radio that cannot receive the 6 GHz band at all, and every macOS survey tool reads that
built-in radio through CoreWLAN, so they are all structurally blind to 6 GHz. Kismet,
WiFi Explorer, and NetSpot included. This driver talks to an external MT7921 adapter
directly over libusb and sees the band.

> **Status: research-grade.** This is a working instrument, not a polished product. It is
> maintained best-effort. Expect to read code. See [ROADMAP.md](ROADMAP.md) for known gaps
> and [NOTICE.md](NOTICE.md) for the upstream derivation.

## Why userspace works at all

Passive monitor mode does not need a network interface. There is no association, no
routing, no handing packets to the network stack. It needs exactly three things: upload
firmware, set a channel with an MCU command, and pull raw frames off a bulk endpoint into
radiotap. That is a plain userspace USB job, and on macOS nothing is holding the device.

DriverKit is not an option and is not needed. Its families cover HID, serial, PCI, audio,
SCSI, and Ethernet-style networking; there is no 802.11 family for third parties, and
Apple's own Wi-Fi driver is a private DEXT. libusb is the opening, and it is enough.

## Requirements

- An MT7921 **USB** adapter (`0x0E8D:0x7961`), for example the ALFA AWUS036AXML.
- macOS on Apple Silicon or Intel. Developed on an M1 Max, macOS 26.6.
- Homebrew `libusb`: `brew install libusb`.
- Python 3.10+.
- **No root required.** macOS leaves the adapter unclaimed, so a normal user process can
  take the interface.

## Setup

```bash
bash setup.sh                 # creates .venv (+pyusb) and fetches firmware into ./firmware
./.venv/bin/python examples/scan.py
```

`setup.sh` is idempotent and puts everything in gitignored, repo-relative locations. The
MediaTek firmware blobs are **not** part of this repository (they are licensed binaries);
`setup.sh` fetches them from `linux-firmware`. See [NOTICE.md](NOTICE.md) for the license
terms and the one blob you must not fetch.

## Usage

```bash
./.venv/bin/python examples/scan.py                 # tri-band BSSID census
./.venv/bin/python examples/sniff_to_pcap.py 6 8    # 8 s on channel 6 -> radiotap pcap
```

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

## Capability matrix

Everything here is something the code actually did on real hardware, not a datasheet claim.

| Capability | Status |
|---|---|
| Claim device from userspace, no root | Yes |
| Upload and boot firmware | Yes |
| Set channel on 2.4 / 5 / 6 GHz | Yes |
| Passive capture: management, data, **and control** frames | Yes |
| 6 GHz receive | Yes |
| Radiotap / pcap output | Yes (0 malformed in Wireshark) |
| Per-frame PHY rate, width, MCS, RSSI, retry bit | Yes |
| Hardware good-MPDU and FCS-error counters | Yes |
| 802.11k/v/r, PMF policy, EasyMesh, 802.11s decode | Yes / opportunistic |
| Frame injection | Yes, at scan rates only (see caveat) |
| 160 / 320 MHz capture | No (gated in firmware for this part) |
| Simultaneous multi-channel | No (one radio) |
| Hardware CCA busy / noise floor | Not yet (registers read zero here) |

Against the built-in radio in the same room and minute: the built-in macOS scan saw 6 / 5 /
0 networks on 2.4 / 5 / 6 GHz; this driver saw 37 / 48 / 4 BSSIDs. The 6 GHz row (0 versus
4) is the one that is exactly comparable, and it is a hardware limit on Apple's side, not a
software one. (The other rows are not like-for-like: macOS lists deduplicated networks,
this lists physical BSSIDs.)

## Injection: read this first

The transmit path (`inject`, `_build_txwi`, `build_probe_request`, and
`examples/inject_demo.py`) is **research-grade and rate-limited.** It is confirmed working
only at scan rates; sustained transmit can panic the MCU. The adapter is also a weak
transmitter, roughly 8 dB below a comparable 802.11ac adapter, so it is a strong receiver
and only incidentally a transmitter. **Transmit only on frequencies and in modes you are
legally permitted to use.** This is a diagnostics and research tool, not an attack tool.

## Limitations worth stating up front

- One radio at up to 80 MHz means channel-hopped, duty-cycled coverage. Any airtime figure
  from a wide or unvisited channel is a partial view and should be labeled as one.
- FCS-error fraction is a channel-local comparison instrument, not an interference
  classifier. It cannot name a microwave or a neighbor from the counter alone.
- Beamformed downlink capture is incomplete; PHY rate is not throughput.

## License and provenance

BSD-3-Clause-Clear. `mt7921u.py` and `rxd.py` are transcriptions of the BSD-3-Clause-Clear
MT7921 path in [openwrt/mt76](https://github.com/openwrt/mt76), commit `c5a3bd91`. See
[LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
