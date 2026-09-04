# Receiver evidence and controlled power, 2026-09-04

Follow-up to [radio observability](RADIO_OBSERVABILITY.md), after merging that work
locally at `3ff84d7`. These are research results, not production driver capabilities.
Aggregate [machine-readable evidence](../research/evidence/receiver-evidence-2026-09-04.json)
contains firmware hashes and no ambient identifiers or frame bytes.

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

Offline tests cover direction/TID, sequence wrap, retry-history expiry, warm-up,
and exclusions for null/multicast/fragmented data; power tests isolate the modified
TXWI field and signed-byte interpretation. Raw network identifiers never leave RAM.
