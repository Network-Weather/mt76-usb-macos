# Short RTS, CTS and ACK transmission

**MT7925 transmits independently received16-byte RTS and10-byte CTS/ACK frames
at1Mbps CCK.** Two fresh runs each receive4/4 of every control class, with exact
synthetic destination/header matching and good FCS. Probe controls are3/4 before
and4/4 after both runs. Durations remain zero. This adds short control-frame
generation to the earlier probe/Data/QoS capabilities, not an automatic handshake,
ACK-timing engine, association or ranging measurement.

## Source-shaped frames and descriptors

Linux's pinned [control-frame structures](https://github.com/torvalds/linux/blob/8ab1afb2eb246ab15b301cd255b5943d208a93c1/include/linux/ieee80211.h#L1287)
define the RTS and CTS layouts. The local parser also recognizes the ACK header.
All lengths below exclude hardware-generated FCS:

| Class | Frame Control | Header bytes | Address fields |
| --- | --- | --- | --- |
| RTS | `0x00b4` | 16 | receiver + transmitter |
| CTS | `0x00c4` | 10 | receiver |
| ACK | `0x00d4` | 10 | receiver |

Each control frame has a fresh per-run, per-packet locally administered unicast
receiver address derived only from random bytes and its experiment index. No
captured station/AP address is used. RTS transmitter address is the existing
synthetic lab address. Duration is always0; no peer is asked to reserve airtime.
No fabricated BA, deauthentication, association, IP or authentication traffic.

The descriptor uses the existing source-derived fixed-rate TX path, with:

- Correct byte count and header-length/2:8 for RTS,5 for CTS/ACK.
- Frame type1 and subtype11/12/13, from [Connac3 fields](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac3_mac.h).
- TXD2 bit12 set to preserve software Duration, as the [vendor SW_DURATION macro](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic/nic_connac3x_tx.h#L465) specifies.
- No manual Sequence Control insertion for short control headers; TXD3 SN_VALID
  and sequence bits cleared, multicast bit cleared, NO_ACK and BA_DISABLE retained.
- TX status requested with unique PIDs16..35; control TXS sequence reads0, so
  matching by the nonexistent MAC sequence would be wrong.
- Existing20MHz fixed rate, disabled MAT, no power offset or timestamp insertion.

The [source-named receiver filters](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt792x_regs.h#L237)
are RFCR `820e5000` bits14/15 (CTS/RTS) and RFCR1 `820e5004` bit4 (ACK).
The probe requires explicit permission to clear just these masks and restores
them afterward. **All three bits were already clear in these runs**; this was
not a newly required filter-unlock discovery. FCS-error capture remains disabled.

## Bounded hardware results

[`control_frame_probe.py`](../research/control_frame_probe.py) sends20 frames:
Probe/RTS/CTS/ACK/Probe, four per class, with100ms/256-transfer receipt windows
and50ms gaps. Both radios use channel6/20MHz and reload normally on exit.
The successful invocation uses `--rate cck1 --acknowledge-experimental-transmit
--open-control-filters`. The committed default is the demonstrated CCK1 case;
only OFDM6 and CCK1 are exposed, with no nonstandard HT control-frame experiment.

| Run start, UTC2026-09-05 | PHY | Probe before | RTS | CTS | ACK | Probe after |
| --- | --- | --- | --- | --- | --- | --- |
| 19:43:27 | OFDM6 | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| 19:44:02 | CCK1 | 3/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| 19:45:04 | CCK1 repeat | 3/4 | 4/4 | 4/4 | 4/4 | 4/4 |

All60 submissions have one matched TX status with count1/error0/power-code36;
rate codes are75 for OFDM6 and0 for CCK1. Successful RX metadata reports
CCK/MCS0/NSS1/20MHz. Exact whole-frame equality independently confirms the
zero Duration and short sizes, not just the existence of a control-frame RXD.
All filters restore and both radios pass alive/reload checks in all three runs.

The OFDM run fails its probe controls too: it is **not evidence that control
frame generation fails at OFDM**, nor proof no RF was emitted. The current
weak/selective reciprocal link remains unresolved. CCK success establishes the
short-frame capability without claiming improved power calibration or general
link recovery. The frames are unsolicited lab stimuli, not responses to observed
production exchanges; no automatic CTS/ACK turnaround or SIFS timing was tested.

[Sanitized evidence](../research/evidence/control-frame-transmit-2026-09-05.json)
contains aggregate own-frame receipts, PHY metadata and matched TX statuses.
No ambient identities/frames or random destination bytes are exported. Production
Python/C APIs and passive defaults remain unchanged.

## Reverse short frames do not restore the older transmitter's control

`--transmitter mt7961` uses the pinned [Connac2 descriptor fields](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac2_mac.h):
header length in DW1 bits15:11, multicast in DW2 bit10, and duplicate type/subtype
in DW8. Software Duration and manual-SN control bits are shared with Connac3;
the fixed-rate HTC bit is retained as [the Linux path requires for management/
control frames](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac_mac.c#L604).
TXS uses the old32-byte format and the same unique per-packet PIDs.

At19:48:28 UTC, CCK1 reverse Probe/RTS/CTS/ACK/Probe gives **0/4 in all five
phases**, with20 matched transmitter statuses. MT7925's three selected receive
drop bits are already clear; mask restoration and both normal reloads pass.
Shorter frames therefore do not establish a usable reverse stimulus for CSI or
timing experiments. The failed probe controls prevent a control-frame-specific
negative, and TX statuses alone do not prove RF emission or reception.
[Reverse evidence](../research/evidence/control-frame-reverse-2026-09-05.json).
