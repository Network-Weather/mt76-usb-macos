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

## Reproduce the offline check

```sh
python research/cross_radio_clock_analysis.py /path/to/retained-trial.json
```

The analyzer validates complete unique TX statuses, one receiver, unique own
RX sequences, bounded integer clocks and unambiguous forward32-bit unwraps.
It permits missed RX frames and reports their count explicitly. It uses the
observed TX rate for each airtime estimate, and leaves latch/propagation
validation false. [Sanitized trials and analysis](../research/evidence/cross-radio-clock-2026-09-05.json).
