# Failed-frame PHY metadata is accessible on MT7961

**Clearing MAC RFCR's FCS-drop bit exposes CRC-failed HT frames that normal
capture hides.** Changing the sniffer `drop_err` byte alone does not do so in
this setup. This adds a useful diagnostic observation, not good-payload reception,
an authenticated transmitter identity, a calibrated loss rate or an interference
source classifier. Production Python/C capture defaults are unchanged.

## Source-defined controls and actual readback

The pinned driver's
[filter constructor](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mcu.c#L1477)
provides CE`0x0a` mode2 bitmap updates: bit-operation2 clears and1 sets.
[MT792x register definitions](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt792x_regs.h)
name RFCR's FCS-drop bit1. The already used normal monitor setup leaves
band0 RFCR`0x820e5000 = 0x00201002`; clearing only bit1 reads back
**`0x00201000`**. No direct whole-register overwrite is used for this control.

Separately, the
[sniffer configuration](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mcu.c#L1190)
has UNI`0x24` tag1/length16 with a `drop_err` byte, normally1. Tests change
that byte between0/1 at the same channel6/20MHz. Reads immediately after
the sniffer command show it does **not** toggle RFCR bit1 in these trials.
The two source controls must not be assumed to be equivalent.

## Factorial control and same-rate reversal

MT7925 sends four65-byte synthetic no-ACK Probe Requests per phase. HT8
controls bracket HT15 phases; power, width, GI and coding remain unchanged.
An initial24-frame factorial is followed by two28-frame runs that add an
HT15 restored-filter phase, so hiding the failed frames is checked again
at the same requested PHY rate. Each packet has a100ms/128-transfer observation
ceiling. The first28-frame run yields:

| Requested PHY | Sniffer drop_err | MAC FCS-drop | Exact good-FCS receipts | Anonymous bad-FCS records |
|---|---:|---:|---:|---:|
| HT8 before | 1 | 1 | 4 | 0 |
| HT15 | 1 | 1 | 0 | 0 |
| HT15 | 0 | 1 | 0 | 0 |
| HT15 | 1 | 0 | 0 | **4** |
| HT15 | 0 | 0 | 0 | **4** |
| HT15 restored | 1 | 1 | 0 | 0 |
| HT8 after | 1 | 1 | 4 | 0 |

The repeat gives the same gate pattern, with **3/4** failed-frame records in
the two open-MAC phases; HT8 controls receive4/4 before and1/4 after. The
variable link is not claimed repaired. All failed records in these two runs
report HT/MCS15/NSS2/NSTS2/20MHz/GI0/BCC,65-byte frames and calculated130Mbps
PHY rate. Raw signal readings remain near−100; no dBm accuracy is established.

The initial probe that checked failed-frame headers and the fresh private nonce
found **no authenticated own failed payloads**. These observations are therefore
anonymous PHY metadata correlated with the controlled rate/time/length, not
exact payload matches or proof of a particular peer's failed transmission.
The published probe explicitly marks `own_frame_identity_verified: false` and
exports no failed frame bytes, MAC addresses, SSIDs or nonces. No good-FCS HT15
payload has yet been verified. Likewise this does not establish HE11 reception.

## Counters reveal another important limit

The [mapped normal-mode PHY counters](PHY_RX_COUNTERS.md) are enabled by the
previously verified clear→`0xa00` sequence under mask`0xe00` at`0x83082004`.
Snapshots and the [latched CN/EVM register](PHY_SIGNAL_FIELDS.md) are read
around observation windows; neither is atomic per-frame metadata.

OFDM PD/MDRDY advance in HT15 windows even when USB delivers no frame. More
importantly, the source-named OFDM FCS field at`0x83081024[31:16]` changes0→1
at the first HT15 window and then remains1 across later failed-frame receipts.
**It is not a demonstrated count of every failed frame under this enable recipe.**
Do not compute an error percentage from it. A latch, separate enable/reset
dependency or another field interpretation remains to be resolved. CCK ambient
traffic and occasional detection errors also appear; counter deltas cannot
automatically be assigned to a particular synthetic transmission.

## Reproduce and restore

```sh
python research/error_frame_probe.py --acknowledge-experimental-transmit \
  --enable-error-capture --enable-counters
```

The probe is restricted to the tested MT7961 receiver, channel6/20MHz and28
submissions. It verifies the FCS-drop readback, restores the original FCS bit
and counter mask, returns the sniffer setting to the boot default1, then
normally reloads both radios. All readback/restoration/alive/reload checks pass
in the retained runs. Counter enabling resets statistics and needs exclusive
ownership; this is not an option to turn on alongside another counter consumer.

For Network Weather, failed-frame PHY observations could expose reception trouble
that successful-packet capture misses. They cannot identify a household device
from a corrupted address, and they do not distinguish interference from weak
signal, PHY construction problems or receiver limitations by themselves.

The pinned Linux
[configure_filter path](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/main.c#L666)
requests FCSFAIL through the firmware flag word. Our source-derived monitor
setup already sends that flag but still observes RFCR bit1 set. That is a
concrete diagnostic pointer, **not a live-Linux reproduction or an upstream bug
claim**; no maintainer message or Linux implementation was sent.

[Sanitized experiments](../research/evidence/error-frame-capture-2026-09-05.json).
