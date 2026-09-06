# Cross-radio timestamps have a packet-duration-dependent separation

**`MT7961 RXD timestamp − MT7925 TXS timestamp − modeled PPDU airtime`
stays within1–2µs per boot**, across five rates and two packet lengths in
the2026-09-05 controls. This is a relative timing measurement, not absolute
clock synchronization, a propagation delay, or a proved timestamp latch point.

## Source fields and bounded experiment

The MT7961 decoder already extracts Group2's first32-bit word. Pinned
[mt7921/mac.c](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mac.c)
uses that word as the receive timestamp and sets `RX_FLAG_MACTIME_START`.
The [Connac3 TXS header](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac3_mac.h)
defines TXS word4 as timestamp. Earlier [TX timing controls](TX_STATUS_TIMING.md)
support a1µs TXS clock. A related MT7928 event's latch-point comment is **not**
assumed to establish this MT7925 clock's latch.

`phy_tx_probe.py --suite cck --transmitter mt7925 --channel 6 --per-phase 4
--tx-timing --acknowledge-experimental-transmit` now records RXD timestamps
**only after exact own-frame and good-FCS validation**. A fresh nonce prevents
old probes matching. No ambient frame, identifier or timestamp is serialized.
Missing timestamps stay unknown; duplicates are not silently collapsed by the
offline analyzer. Default capture output is unchanged without the timing opt-in.

Two fresh runs send24 no-ACK probes each,50ms apart: OFDM6, CCK1/2/5.5/11,
OFDM6. The second adds128 private-IE bytes, increasing MAC length65→193;
hardware adds the4-byte FCS. Channel6/20MHz, power and preamble selections
are unchanged. Both radios remain alive and both transmitter reloads pass.
The receiver remains in normal monitor mode; no report-register change is used.

| Run | Exact receipts by phase | Matched clock pairs | Corrected offset range | Spread |
|---|---|---|---|---|
| 65 MAC bytes | 0/4/4/4/4/1 | 17 | 2568972..2568974 | **2µs** |
| 193 MAC bytes | 1/4/4/4/4/2 | 19 | 2530349..2530350 | **1µs** |

All24 TX statuses per run are matched format0/single-attempt/error-free.
All16 CCK probes arrive in both runs; OFDM reception remains weak. The
different per-boot constants cannot be compared as distance or time-of-flight.

## Why the packet-duration term matters

The model includes the long CCK or OFDM preamble, MAC bytes plus FCS, and
OFDM service/tail/symbol rounding. It excludes SIFS and the optional ERP6µs
extension, exactly as in the earlier TX timing analysis. Raw median clock
differences change with PHY airtime, not just elapsed host time:

| Rate | Modeled duration65/193 bytes | Raw RX−TX median,65 bytes | Raw RX−TX median,193 bytes |
|---|---|---|---|
| CCK1 | 744/1768µs | 2569718 | 2532118 |
| CCK2 | 468/980µs | 2569441 | 2531330 |
| CCK5.5 | 293/479µs | 2569266 | 2530828 |
| CCK11 | 243/336µs | 2569215 | 2530685 |
| OFDM6 | 116/288µs | 2569088 | 2530637 |

Subtracting each modeled duration removes these differences to1–2 ticks over
all36 matched frames. The airtime-corrected RX/TX slope fits are0.999998698 and
0.999999214, consistent with nearly equal-rate clocks over these short windows;
these fits are **not a calibrated oscillator-drift specification**. A longer
window and interleaved packet lengths would better separate drift/order effects.

The evidence rejects treating the two raw timestamps as the same packet
boundary plus one constant offset. It is consistent with a transmit-start /
receive-end-like separation, but either field could have an internal or
duration-adjusted latch. **No independent absolute timing reference identifies
which endpoint or exact bit is sampled.** Consequently this is not, by itself,
a definitive Linux `MACTIME_START` bug report or a claim of end-of-FCS precision.
Prior USB observations of per-MPDU timestamps inside A-MPDUs are a separate
reason to audit assumptions about receive timestamp semantics.

For Network Weather, the useful lead is packet-duration-aware cross-radio
alignment and more trustworthy activity windows. An unknown offset still
absorbs startup skew, fixed processing latency and propagation. It must never
be converted to meters or interpreted as an RTT measurement.

## Independent clock-reference frontier

The pinned driver's
[`mt792x_get_tsf`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt792x_core.c#L243)
provides a source-defined OMAC0/band0 TSF snapshot: OR3 into LPON_TCR0
`0x820eb0a8`, then read UTTR0/1 at`0x820eb080/84`. This is the software-read
mode, **not** SW_WRITE mode1; neither timestamp data register is written.
The corresponding register fields are in
[`mt792x_regs.h`](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt792x_regs.h#L70).

An initial test incorrectly required the low mode bits to self-clear. The
diagnostic repeat shows control`0x01640003` and both timestamp words zero.
Upstream repeatedly ORs3 and does not specify self-clearing behavior; retained
mode3 is therefore accepted, not called a busy/error state. With that check
corrected, six snapshots50ms apart on **each** radio all return64-bit zero.
The control remains in read mode3. Both alive checks and normal reloads pass.

This OMAC0 snapshot is **not an advancing reference clock in the current
unassociated monitor setup**. It does not establish that the packet clocks
are zero, that every TSF instance is unavailable, or that a TSF setter/active
BSS is needed. No BSS activation, TSF setter or clock-enable sweep was attempted.
`research.tsf_snapshot.snapshot` preserves the small source-defined read recipe
and host-call brackets, with invalid-bus/mode checks. A retained read selector
is not claimed to have been cleared by reload; no timestamp value was set.
[Sanitized snapshot/diagnostic evidence](../research/evidence/tsf-snapshot-2026-09-05.json).

### An advancing LPON counter exists, but has a different apparent epoch

Two explicitly source-derived, read-only candidates were checked: LPON
offset`0x314` from MT7915 and`0x37c` from MT7916/MT7996, at the known MT792x
band0 base`0x820eb000`. See the pinned
[MT7915/7916 offset table](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7915/mmio.c)
and [MT7996 FRCR definition](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7996/regs.h).
These are related-chip register names, not an independently recovered MT792x
register specification. No adjacent-address sweep or counter writes were used.

On **both** tested dongles, six samples50ms apart return zero at`0x820eb314`
but an advancing counter at **`0x820eb37c`**. First-to-last host-call brackets
are consistent with1MHz on both chips; this short USB-bracketed check is not
a calibrated frequency or drift measurement. Both normal reloads pass.
The small `research.lpon_clock.read_counter` helper reads only37c, rejects
invalid bus words/unknown chips, and preserves host-call brackets. It neither
resets a clock nor treats this counter as TSF.

Two fresh24-frame CCK-suite controls then read37c immediately before and
after each blocking USB receive call. Only exact own good-FCS RX frames and
the bounded own PID/sequence TX statuses are serialized. Each run receives
19 exact frames and all24 valid TX statuses; both alive checks and transmitter
reloads pass. The observed differences are:

| MAC bytes | MT7961 counter-after minus RXD timestamp | MT7925 counter-after minus TXS timestamp |
|---|---|---|
| 65 | 124691..126028 ticks | 133234..134880 ticks |
| 193 | 120064..121718 ticks | 134448..137837 ticks |

These offsets are much larger than the per-record read-call windows and
change between boots. **The counter cannot simply replace the RXD/TXS clock.**
The differences combine any clock-origin offset, timestamp semantics and
delivery delay; they are not measurements of USB latency. In particular,
they do not independently locate the packet timestamp latch. The counter
is a useful local elapsed-time candidate, not yet a precision cross-radio
alignment or ranging primitive. Packet-counter reads also perturb USB polling;
this wrapper is an opt-in experiment, not a default acquisition change.

```sh
python research/lpon_packet_clock_probe.py --suite cck --transmitter mt7925 \
  --channel 6 --per-phase 4 --tx-timing --acknowledge-experimental-transmit
# Repeat with --timing-padding 128 for the longer-packet control.
```

[Sanitized counter and packet controls](../research/evidence/lpon-clock-2026-09-05.json).

## Reproduce the offline check

### Preamble-only control strengthens the relative-latch result

Two subsequent `--suite preamble --tx-timing` runs retain four probes per
phase and alternate OFDM6, CCK2-long, CCK2-short, CCK11-long, CCK11-short,
OFDM6. Within each long/short pair the PHY rate and MAC length are unchanged.
The [pinned Linux frame-duration implementation](https://github.com/torvalds/linux/blob/8ab1afb2eb246ab15b301cd255b5943d208a93c1/net/mac80211/util.c#L119)
uses144+48µs versus72+24µs for the CCK preamble plus PLCP header: a96µs
difference. The research model now accepts only the already exercised short
codes5/7; it still rejects short1Mbps and untested code6.

| Fresh run | Exact receipts | CCK2 long−short RX−TX median | CCK11 long−short | Corrected offset spread |
|---|---|---|---|---|
| 65 MAC bytes | 0/3/4/4/4/4 | **96µs** | **96µs** | 2µs,19 pairs |
| 193 MAC bytes | 2/3/4/4/4/4 | **97µs** | **97µs** | 2µs,21 pairs |

The extra tick in the longer run fits its1–2-tick within-boot variation; it is
not evidence for a97µs physical preamble difference. All24 TX statuses per
run and all alive/transmitter-reload checks pass. This isolates a preamble
contribution at unchanged payload rate, supporting whole-PPDU-duration rather
than payload-only separation. Absolute latch points remain unproved. Across
the original and preamble runs there are76 matched clock pairs, not a distance
calibration. [Sanitized preamble controls](../research/evidence/cross-radio-preamble-clock-2026-09-05.json).

### Offline invocation

```sh
python research/cross_radio_clock_analysis.py /path/to/retained-trial.json
```

The analyzer validates complete unique TX statuses, one receiver, unique own
RX sequences, bounded integer clocks and unambiguous forward32-bit unwraps.
It permits missed RX frames and reports their count explicitly. It uses the
observed TX rate for each airtime estimate, and leaves latch/propagation
validation false. [Sanitized trials and analysis](../research/evidence/cross-radio-clock-2026-09-05.json).
