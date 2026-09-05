# Receiver evidence and controlled power, 2026-09-04

Follow-up to [radio observability](RADIO_OBSERVABILITY.md), after merging that work
locally at `3ff84d7`. These are research results, not production driver capabilities.
Aggregate [machine-readable evidence](../research/evidence/receiver-evidence-2026-09-04.json)
contains firmware hashes and no ambient identifiers or frame bytes.
The [follow-up evidence](../research/evidence/receiver-evidence-followup-2026-09-04.json)
records the channel 149 attenuation repeat, channel 132 positive delivery comparison,
and channel 149 subtype census.

## Per-packet attenuation reaches the air

Test bed: MT7961/MT7921 ALFA `0e8d:7961` transmitting, MT7925 A9000 `0846:9072`
independently receiving on the same host; unchanged physical placement. Both radios
use their pinned firmware, monitor/sniffer mode, and 20 MHz. No association or
persistent power configuration is involved.

```bash
./.venv/bin/python research/tx_power_probe.py --channel 36 \
  --acknowledge-experimental-transmit --output /tmp/power-36.json
```

The bounded experiment sends 100 directed no-ACK OFDM 6 Mbps Probe Requests, with
50 ms spacing, in five 20-frame phases: `0, -8, 0, -16, 0`. Only TXWI word 2
bits 29:24 change, the `MT_TXD2_POWER_OFFSET` field in
[mt76_connac2_mac.h at c5a3bd91](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac2_mac.h).
The signed six-bit interpretation was initially a hypothesis; these two negative
codes now have directional evidence. Positive codes and other rates are untested.

Acceptance: the second radio decodes the controlled frame sequences; attenuation
phases lower received signal relative to adjacent zero-code controls; TX status
records agree in direction; both radios remain responsive after capture.

| Channel 36 phase | 0 | -8 | 0 | -16 | 0 |
|---|---:|---:|---:|---:|---:|
| Independent frames / submitted | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 |
| TX status power byte | 44 | 36 | 44 | 28 | 44 |
| Receiver median RSSI | -40 | -46 | -42 | -50 | -41.5 |

All 100 independent decodes reported OFDM; all 100 TX statuses were received, and
both register-alive checks passed. Relative to adjacent baseline medians, measured
attenuation is about 5 and 8.25 dB. This is compatible with a roughly half-dB code
step, but is **not a calibrated transfer function or absolute transmit-power
measurement**. In particular, raw TX status 44 must not be labeled 44 dBm.

A repeat using `--channel 149` again decoded 100/100 frames and received 100 TX
statuses, with both radios alive afterward:

| Channel 149 phase | 0 | -8 | 0 | -16 | 0 |
|---|---:|---:|---:|---:|---:|
| Independent frames / submitted | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 |
| TX status power byte | 44 | 36 | 44 | 28 | 44 |
| Receiver median RSSI | -46 | -50 | -46 | -54 | -46 |

This repeat has exact 4 and 8 dB median attenuation at the receiver and matching
raw TX-status reductions of 8 and 16. It strengthens the half-dB-step interpretation
for these codes/rate/channels, without calibrating absolute dBm or other codes.

The probe also evaluates neighboring-chip standalone RX-vector hypotheses from
`mt7915/mac.c:mt7915_mac_fill_rx_vector` at the same pinned revision. Group 5 word 7
byte 1 interpreted as signed eight bits tracks receiver RSSI here (phase medians
-41, -47, -43, -50, -42). The candidate SNR barely moves (10, 10, 10, 9, 10),
and the candidate frequency-offset field has coarse steps. These fields are not
validated noise floor, SNR, or frequency offset; do not expose those labels to users.

This provides a useful future controlled perturbation: change one radio's signal
without changing its placement or persistent configuration, then check what the
other radio's telemetry actually responds to. It does not yet recommend AP power.

## BlockAck is receipt evidence, not a passive loss-rate meter

```bash
./.venv/bin/python research/delivery_evidence.py 5GHz:149:155:80 \
  --seconds 30 --output /tmp/delivery-149-80.json
```

The passive probe retains transmitter/receiver/TID/sequence histories only in RAM.
For each compressed single-TID BlockAck it compares acknowledged sequence numbers
with QoS data observed in the preceding 100 ms, accounting for direction and
modulo-4096 sequence wrap. Common beacon bytes align the two timestamp domains;
shared BlockAcks must have unique matching fingerprints and fall within 100 us
after clock alignment. No decrypted payload is needed.

Acceptance for a useful positive comparison: recent QoS data must actually be
observed, the beacon clock fit must pass, and at least one shared BlockAck must
match. The first run **does not meet the data-observation criterion**:

- MT7961: 3,175 frames, 815 BlockAck windows, no qualifying recent QoS data.
- MT7925: 2,599 frames, 283 BlockAck windows, no qualifying recent QoS data.
- 37 shared beacons give 0.641 us fit p95 and 0.614 us held-out prediction p95.
- 182 shared BlockAck events contain 8,720 acknowledged sequence-window positions
  with no corresponding recent data observation by either dongle.
- Both radios remain responsive; no USB errors are reported.

Those 8,720 positions are **not unique packets, failed deliveries, or a quantified
sniffer miss rate**. BlockAck windows can repeat earlier receipts, data can precede
the lookback, and bandwidth, beamforming, filtering, or frame-format visibility can
prevent observation. This run says that receiver receipt reports are visible where
the corresponding data histories are not. It does not establish why. Follow-up
census counters distinguish frame subtypes and timestamp exclusions.

The channel 149 repeat with those counters again saw no QoS data subtype `0x88`
on either radio, with no timestamp exclusions. It did see 406 and 227 post-warmup
BlockAck windows and some non-QoS data (17 and 31 frames). Thus the missing QoS data
is not caused by this tool's timestamp filter or QoS acknowledgment-policy filter.
Only five shared beacons were captured, below the required 20, so the tool correctly
refused cross-radio event comparison for this repeat. Both radios remained alive.
The underlying receive/bandwidth/air-traffic explanation is still unresolved.

### Positive matched-data result on channel 132 / 80 MHz

Repeat the command with target `5GHz:132:138:80`, otherwise unchanged. This second
30 s dwell meets the positive acceptance criterion:

| Observation | MT7961 | MT7925 |
|---|---:|---:|
| Frames | 2,410 | 2,778 |
| Qualifying QoS data | 135 | 88 |
| QoS data with retry flag | 10 | 0 |
| BlockAck windows | 110 | 101 |
| HE-SU frames | 109 | 66 |

There are 884 shared beacons: clock fit p95 0.799 us, held-out p95 0.933 us.
All 101 shared BlockAck events pass the timestamp gate. Their acknowledged
sequence-window opportunities divide into:

- 70 with recent data observed by both radios;
- 31 with recent data observed only by MT7961;
- one with recent data observed only by MT7925;
- five with no recent data observed by either.

No timestamp exclusions, backward timestamp skips, or USB errors were reported;
both radios were alive afterward. The subtype census agrees with the qualifying
QoS counts, so this result is not an artifact of excluding timestamp-less QoS frames.
No observed recent sequence had a zero bit in its corresponding BA window.

This establishes complementary observer visibility and receiver-reported receipt
in one dwell, **not superiority of one chipset, unique packet counts, a mesh link,
or packet-loss percentages**. In particular, the retry flag totals do not mean that
the MT7925 observed a healthier link; it observed fewer QoS frames overall.
The asymmetry could reflect RF placement, directional reception, filtering, or
decode differences; this experiment does not distinguish those causes.

Offline tests cover direction/TID, sequence wrap, retry-history expiry, warm-up,
four-address QoS offsets, timestamp pairing gates, all visibility categories,
and exclusions for null/multicast/fragmented data; power tests isolate the modified
TXWI field and signed-byte interpretation. Raw network identifiers never leave RAM.

Validation: the complete `scripts/check.sh` gate passed at both checkpoints
(405 then 407 Python tests, documentation, Ruff, distributions, dependency check,
and C offline tests). The follow-up adds paired-comparison and four-address QoS
tests; no production driver code changes in this exploration.
