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

## A distinct MAC FCS counter does accumulate and read-clear

The source-defined **`0x820ed698[31:16]`** is a different field from the PHY
register above. Pinned
[`mt792x_mac_update_mib_stats`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt792x_mac.c#L77)
adds it to the software FCS count; `mt792x_regs.h` defines band0 MIB base,
SDR3 offset`0x698` and the high16 mask. The research helper is MT7961-only:
the MT7925 vendor register map differs and is not assumed interchangeable.

Two further28-frame filter cycles add paired reads immediately around each
window. In the first run, all20 HT15 windows return **[1,0]** after the window;
all eight successful HT8 controls return[0,0]. In the repeat,19 HT15 windows
return[1,0], while the remaining open-filter window returns[0,0] and also has
no failed-frame delivery. All eight HT8 controls again return[0,0]. These
results cover closed and open MAC filters: the MAC counts failed receptions
even when their USB delivery is suppressed. The initial pre-trial reads contain
3/4 errors respectively and are explicitly discarded, not assigned to probes.

To distinguish accumulation from a one-bit read-clear event latch, two separate
18-frame tests sample **only before/after batches**, with normal error-drop
filters and **no PHY counter-enable writes**. Both begin/end with RFCR
`0x00201002` and PHY control`0x83082004 = 0` unchanged:

| Batch | First run MAC FCS pair | Repeat MAC FCS pair | Good payload receipts, each run |
|---|---|---|---|
| 4 × HT8 | [0,0] | [0,0] | 4 |
| 2 × HT15 | [3,0] | [2,0] | 0 |
| 4 × HT8 | [0,0] | [0,0] | 4 |
| 4 × HT15 | [4,0] | [4,0] | 0 |
| 4 × HT8 | [0,0] | [0,0] | 4 |

The extra count in the first two-frame batch is **not** forced into a one-error-
per-probe explanation: this is a channel-wide counter and includes background
activity. Multi-count reads followed by zero, together with the single-packet
controls and the Linux read-and-accumulate use, support a **read-clear MAC FCS
counter available without the PHY enable recipe**. All alive/reload checks pass.

This gives Network Weather an error-count surface that need not export failed
packets. It still needs exclusive ownership, a defined sample interval and a
qualified denominator before becoming an error percentage. Full-word reads also
consume the opaque low16 field; it is not independently named or calibrated here.
Do not subtract two readings as if cumulative, assume wrap/saturation behavior,
or mix this register with the legacy MCU offset0 previously found inconsistent
with its FCS-error label. No production survey API changed.

```sh
# Paired samples with the factorial error-delivery experiment:
python research/error_frame_probe.py --acknowledge-experimental-transmit \
  --enable-error-capture --enable-counters --mac-fcs
# Independent18-frame batch control, no PHY counter/filter changes:
python research/mac_fcs_batch_probe.py --acknowledge-experimental-transmit
```

[Sanitized MAC counter controls](../research/evidence/mac-fcs-counter-2026-09-05.json).

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
