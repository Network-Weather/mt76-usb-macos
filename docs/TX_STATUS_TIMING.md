# MT7925 transmit-status timing: a live measurement lead

The existing hardware TX status carries **live delay, timestamp and front-time
fields**. Two bounded, independently received packet-size/rate controls support
a1µs timestamp clock and32µs front-time/delay ticks. This is more than a command
ACK, but it is not calibrated airtime, a pure contention timer, or ranging.

## Exact readout, no new hardware controls

At mt76 pin`c5a3bd91aa735b669618610d5f0ebfa5786845a6`, the
[Connac3 header](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac3_mac.h)
defines a16-byte TXS header and48-byte records:

| Field | Record location | Interpretation here |
|---|---|---|
| TX_DELAY | DW2 bits15:0 | Raw16-bit delay, not just channel access |
| TIMESTAMP | DW4 | Raw32-bit timestamp |
| FRONT_TIME | DW5 bits24:0, **format0 only** | Raw25-bit clock value, not a duration |
| RATE_STBC | DW3 bit7 | Separate from DW0 raw rate bits13:0 |

`mt7925_tx_probe.tx_status(..., include_timing=True)` exposes those fields.
`phy_tx_probe.py --tx-timing` also records host monotonic receipt times. The
default status output is unchanged. No register writes beyond the existing
fixed-rate programming, TX power changes, ACK requests or new firmware command
are added. Noise/RCPI fields are deliberately not called measurements from these
no-ACK transmissions.

## Rate and128-byte length controls

Both fresh channel6/20MHz runs send24 no-ACK Probe Requests at50ms spacing:
four OFDM6, then four each CCK1/2/5.5/11 long-preamble, then four OFDM6.
A private per-run nonce and exact complete frame/FCS match identify receipts.
The second run adds a128-byte well-formed private vendor IE, growing the
host-supplied MAC frame from65 to193 bytes; hardware adds four FCS bytes.

| Run | Exact RX receipts, six phases | Statuses | Timestamp clock fit |
|---|---|---|---|
| 65 bytes | 2,4,4,4,3,4 | 24/24 | 999987 ticks/host-second |
| 193 bytes | 3,4,4,4,4,2 | 24/24 | 1000183 ticks/host-second |

Every status is format0, PID3, a unique expected sequence, one transmission,
and zero error bits. Both radios remain alive; normal transmitter reload passes.
The receiver is not reloaded by this existing probe. USB receipt timing is not
calibration; its jitter limits the clock fits.

Front time advances at31245/31270 ticks per host-second, consistent with a
32µs clock. Unlike a delay, its raw value grows throughout each run. Raw delay
does vary with rate, packet length and occasional large waits.

## A joint relation holds across all48 packets

The offline `tx_timing_analysis.py` tests the explicit hypothesis:

`K = 32 × (front_time + tx_delay) − timestamp − modeled_airtime`

It unwraps25/32-bit clocks and rejects missing/duplicate statuses, nonforward
clocks, other PHY rates, retries and error statuses. The airtime model uses
long CCK preamble192µs plus ceiling(payload bits/rate), or OFDM6 preamble20µs
plus4µs OFDM symbols including16 service bits, six tail bits and FCS. It excludes
SIFS and the optional6µs ERP signal extension;32µs-scale evidence cannot locate
all PHY/MAC timing boundaries. Compare the formula components in Linux
[ieee80211_frame_duration](https://github.com/torvalds/linux/blob/8ab1afb2eb246ab15b301cd255b5943d208a93c1/net/mac80211/util.c),
whose exported duration additionally includes SIFS/signal extension.

Across every rate in each run, K stays within **one32µs quantum**:

- 65-byte run:129780..129812µs, spread32µs.
- 193-byte run:131327..131356µs, spread29µs.

The per-boot constant differs, so directly subtracting the two clocks without
alignment is invalid. This relation is consistent with front+delay describing
completion on one clock and timestamp tracking an earlier transmit boundary
on another. It is a tested model, **not proof of the exact timestamp latch point**.
The same header describes a32µs delay in a separate MT7928 event structure;
that related-chip comment alone is not our evidence for MT7925 units.

The minimum raw delays also grow with the packet-length model:

| PHY | Modeled time65→193 bytes, µs | Minimum delay ticks65→193 |
|---|---|---|
| OFDM6 | 116→288 | 4→9 |
| CCK1 | 744→1768 | 24→55 |
| CCK2 | 468→980 | 15→31 |
| CCK5.5 | 293→479 | 10→15 |
| CCK11 | 243→336 | 8→11 |

Multiplying these minima by32 tracks airtime within quantization and small
overhead; delay is therefore **not pure backoff or contention**. One short CCK2
packet reports delay249, roughly8ms under this model, while its airtime is468µs.
Such excess could be useful as a service/access-delay observation, but does not
identify Wi-Fi contention, non-Wi-Fi interference, host scheduling, or an AP.
Further controlled perturbation and CCA correlation are needed.

## Burst control: front time follows serial service, not host enqueue

A follow-up changes only pacing: eight CCK1 packets50ms apart, **eight unpaced
packets**, then eight at50ms again. All frames are193 bytes, no-ACK, channel6/20,
with no aggregation, rate change, EDCA/CCA modification or power increase.
`--suite timing-burst --per-phase 8 --tx-timing --timing-padding 128` is bounded
to at most ten unpaced frames per invocation. Host bulk-call timings are retained
only with the timing opt-in.

Both fresh runs receive **8/8 in each of all three phases**, and each produces
24 unique single-attempt error-free statuses. Both alive checks and transmitter
reload pass. The joint clock/airtime relation still has31/28µs offset spread.

| Burst observation | First | Fresh repeat |
|---|---|---|
| Host submission window, eight frames | 1.624ms | 1.254ms |
| Front through last delay span | 703 ticks ≈22.496ms | 533 ticks ≈17.056ms |
| Sum of modeled packet airtimes | 14.144ms | 14.144ms |
| `next_front − front − delay` | **0 for all7 links** | **0 for all7 links** |

For the first burst, delays are55,57,301,60,58,57,59,56 ticks. For the repeat,
they are127,64,57,57,57,57,56,58. They do **not** grow cumulatively for frames
already submitted by the host. Instead each next front-time equals the previous
front-time plus its delay exactly, in both runs. Host submission finishes before
most of these successive front-times are reached.

This strongly supports a **head-of-line/service-boundary interpretation**:
the delay includes each frame's own service/access/on-air interval, not all
earlier FIFO waiting since USB submission. It does not identify the exact
internal queue, prove an interrupt/completion boundary, or separate contention
from other hardware delays. In particular, do not subtract airtime and label the
remainder total end-to-end queue delay. No external interference source was
introduced or inferred.

[Sanitized burst controls and analysis](../research/evidence/tx-status-burst-timing-2026-09-05.json).

## Reproduce

```sh
python research/phy_tx_probe.py --transmitter mt7925 --channel 6 --suite cck --per-phase 4 --tx-timing --acknowledge-experimental-transmit
python research/phy_tx_probe.py --transmitter mt7925 --channel 6 --suite cck --per-phase 4 --tx-timing --timing-padding 128 --acknowledge-experimental-transmit
python research/tx_timing_analysis.py /path/to/retained-trial.json
```

The first historical trial predates the explicit frame-length output; analyze it
with `--frame-bytes 65`. New outputs record the length and reject contradictory
overrides. [Sanitized trials and analysis](../research/evidence/tx-status-timing-2026-09-05.json)
retain own-device status fields and receipt aggregates only.
