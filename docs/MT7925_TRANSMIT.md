# MT7925 transmit exploration, 2026-09-04

Research-only reverse direction of the [receiver-evidence experiments](RECEIVER_EVIDENCE.md).
The production `Mt7925uDevice.inject()` remains deliberately unsupported.
Redacted [hardware evidence](../research/evidence/mt7925-transmit-2026-09-04.json)
preserves all three initial runs, including the insufficient first matcher.

## Source-derived experiment

[`research/mt7925_tx_probe.py`](../research/mt7925_tx_probe.py) transcribes the bounded
injected-management subset of `mt7925_mac_write_txwi`, `mt7925_mac_write_txwi_80211`,
and `mt7925_usb_sdio_tx_prepare_skb` from openwrt/mt76
`c5a3bd91aa735b669618610d5f0ebfa5786845a6`, plus that revision's
`mt76_connac3_mac.h`, `mt7925/init.c`, and `mt792x_regs.h`.
The source files carry BSD-3-Clause-Clear; the MediaTek copyright is retained.
This is an upstream-derived mechanism, not an independently invented transmitter.

Important differences from the working MT7961 experiment:

- TXWI word 1 has a fixed-rate flag, different header geometry, and no connac2
  LONG_FORMAT flag. The numerical bit 31 now means fixed rate.
- Word 6 supplies a six-bit **rate-table index**, not the connac2 inline PHY rate.
  The probe programs volatile table slot 18 to OFDM 6 Mbps (`0x4b`), exactly the
  upstream basic-rate initialization entry `MT792x_BASIC_RATES_TBL + 4`.
- Multicast/BCM is in word 3 bit 4; word 6 includes one MSDU and DAS.
- TX status has a four-word prefix and twelve-word records, not two/eight.
- Word 6 bit 3, `MT_TXD6_DIS_MAT`, is a candidate control for preserving raw
  injected addresses. The upstream non-MLD vif path sets it.

No association, keys, firmware patch, persistent configuration, sustained/high-packet-rate
traffic, deauthentication, or ACK solicitation is used. The rate-table write is followed
by firmware reload and a monitor-mode reconfiguration in cleanup. Read-back of the
staging register is not proof of rate-table contents; independent receive is the
acceptance criterion. Both radios' register-alive checks are recorded.

## Initial hardware result

Test bed: attached A9000 `0846:9072` transmitting, ALFA MT7961 `0e8d:7961`
receiving, macOS host, checksum-pinned firmware recorded in each JSON output.
Both are tuned to channel 36 / 20 MHz. Directed Probe Requests use a synthetic
SSID and source address; no ambient addresses or payloads are serialized.

```bash
./.venv/bin/python research/mt7925_tx_probe.py --channel 36 --count 10 \
  --acknowledge-experimental-transmit --output /tmp/mt7925-tx36.json
```

First run: ten TX status records, all OFDM `0x4b`, PID 3, raw power 26, no ACK
error bits. A source-address-only receive matcher found zero frames. This was
**not** sufficient evidence of transmit failure.

Second run: match the synthetic directed SSID and sequence instead of requiring
the submitted source address. **10/10 distinct sequences were independently
decoded at OFDM 6 Mbps**, median receiver RSSI -48. All ten had a rewritten source
address. TX status reported one transmission each, with error bits 16:22 clear.
Both radios stayed alive, and transmitter firmware reload succeeded.

Thus MT7925 transmit works in this bounded configuration, but the initial raw-frame
path does not preserve the requested source address. The replacement address is
not logged. The first negative result was an observation-matcher failure, not an
established RF failure. `--disable-mat` tests the upstream flag separately.

Third run: add `--disable-mat --count 20`. **20/20 received frames match the
submitted bytes exactly**, including source address, sequence, and payload.
The only descriptor change is word 6 bit 3. All 20 TX statuses report OFDM 6 Mbps,
one transmission, and zero error bits. Both chips remain alive and firmware cleanup
succeeds. This validates DIS_MAT for byte-preserving Probe Requests on this setup.

## Cross-channel and attenuation follow-up

The [follow-up evidence](../research/evidence/mt7925-transmit-followup-2026-09-04.json)
contains all three additional runs. Report dates use the host's local date;
individual JSON timestamps are UTC.

Channel 149 with `--count 60 --disable-mat`: 59/60 distinct frames were independently
decoded, all 59 byte-exact. There were 60 TX statuses with one transmission and no
reported error bits. The missing independent decode is unexplained and must not be
silently counted as received; TX status is not delivery proof for no-ACK frames.

```bash
./.venv/bin/python research/mt7925_tx_probe.py --channel 149 --count 60 \
  --disable-mat --power-cycle --acknowledge-experimental-transmit \
  --output /tmp/mt7925-power149.json
```

This sends five 12-frame phases with power codes `0, -8, 0, -16, 0`, modifying
connac3 word 2 bits 31:26 (`MT_TXD2_POWER_OFFSET`). The connac2 location is different.
Acceptance requires independent receive, a signal reduction relative to adjacent
zero-code controls, a corresponding TX-status change, and successful cleanup.

| Channel 149 phase | 0 | -8 | 0 | -16 | 0 |
|---|---:|---:|---:|---:|---:|
| Independent byte-exact frames | 12 | 12 | 12 | 12 | 12 |
| Receiver median RSSI | -60 | -65 | -62 | -70 | -62 |
| TX-status raw power byte | 26 | 18 | 26 | 10 | 26 |

Relative to adjacent zero-code medians, attenuation is 4 and 8 dB. This independently
agrees with the roughly half-dB code steps found on MT7961, now with transmitter
and observer roles reversed. It does not calibrate absolute power or justify
labeling raw 26 as 26 dBm. Both radios stayed responsive and the post-experiment
firmware reload succeeded. No association or AP/client settings were changed.

Repeating the same power-cycle command with `--channel 36` again receives all
60 frames byte-exact, with the same `26, 18, 26, 10, 26` TX-status power sequence.
Receiver medians are `-50, -54, -51.5, -58, -52`. Relative reductions against
adjacent baseline medians are 3.25 and 6.25 dB: correct direction, but less than
channel 149's 4 and 8 dB. The difference reinforces that this is an RF observation
with baseline variation, not a calibrated code-to-dBm transfer function. Both
radios and the cleanup reload pass again.

Across the four DIS_MAT runs, 199/200 submitted frames are independently received
byte-exact (20/20, 59/60, 60/60, 60/60). The single missing observation remains
unexplained. Zero-code TX power stays raw 26 in these MT7925 runs; this differs
from MT7961's raw 44 but is not an absolute-power or cross-chip calibration.

For Network Weather, the new capability is a controlled transmitter/observer pair
in either direction: characterize receive bias, signal-dependent telemetry, and
observer visibility without associating or changing the home's AP settings.
This is not yet a link-quality estimator, automatic power plan, or dependable
general-purpose packet injector.

The complete `scripts/check.sh` gate passes: 412 Python tests, Ruff, documentation,
distribution builds, dependency consistency, and C offline tests. The production
driver files are unchanged. No captures, firmware, or ambient identifiers are
committed, only aggregate evidence and synthetic test cases.

## Interleaved PHY rates and stronger attenuation

Redacted [rate/power evidence](../research/evidence/rate-power-2026-09-04.json)
preserves both runs with firmware hashes and per-rate/per-phase aggregates.

Follow-up on the same local date, after the channel-geometry experiments. This
adds optional per-packet alternation between OFDM 6 and 54 Mbps, while retaining
50 ms submission spacing and the 60-frame ceiling. The higher PHY rate does not
mean higher offered packet load. Both radios remain on channel 149 / 20 MHz.

The table initializer now optionally programs slot 25 to `0x4c`, matching
`mac80211.c:mt76_rates` entry 11 (OFDM hardware index 12) plus the basic table base
14, at the same pinned mt76 revision. Slot 18 remains `0x4b` for 6 Mbps. TXWI selects
between the two preprogrammed slots without intervening MCU commands. Cleanup
reloads firmware after modifying these volatile slots; exact post-reset table
contents are not independently read back. Frames advertise both
supported rates, and the receive side checks the actual PHY rate against each
sequence's planned rate. Existing default commands still use only 6 Mbps.

```bash
./.venv/bin/python research/mt7925_tx_probe.py --channel 149 --count 60 \
  --disable-mat --power-cycle --alternate-rate \
  --acknowledge-experimental-transmit --output /tmp/rate-power149.json
./.venv/bin/python research/mt7925_tx_probe.py --channel 149 --count 60 \
  --disable-mat --power-cycle --cycle-depth 32 --alternate-rate \
  --acknowledge-experimental-transmit --output /tmp/rate-power149-deep.json
```

Each phase sends six frames at each rate. The first run uses codes
`0,-8,0,-16,0`; all **60/60 are byte-exact, 30 per PHY rate, with zero rate
mismatches**. At code -16, median RSSI is -70 at 6 Mbps and -72 at 54 Mbps.
There are 60 matching TX statuses; raw powers are `26,18,26,10,26` at both rates.

The second run extends the signed six-bit offset experiment to its -32 boundary:

| Power code | 0 | -16 | 0 | -32 | 0 |
|---|---:|---:|---:|---:|---:|
| Byte-exact 6 Mbps frames / sent | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| Byte-exact 54 Mbps frames / sent | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| Median RSSI, either PHY rate | -58 | -68 | -60 | -76 | -61 |
| TX-status power byte, either PHY rate | 26 | 10 | 26 | 250 | 26 |

The -32 code yields approximately 15.5 dB attenuation relative to adjacent
baselines. Raw power **250 is consistent with signed eight-bit -6**, exactly
`26 - 32`; it is not a rise to 250 units. The simultaneous signal reduction
supports that interpretation. Units and absolute radiated power remain uncalibrated.
Both runs pass all alive checks and firmware cleanup, with zero observed USB errors.

**No decoding boundary was found.** Receiving six short frames at each rate in
the deepest phase is not a sensitivity specification, statistically strong loss
estimate, throughput result, or guarantee for long data frames. This experiment
establishes independent rate selection, stronger attenuation, and the signed-power
encoding evidence; it does not demonstrate that rate-dependent packet loss is absent
in general. Noise floor/SNR and absolute RSSI calibration are still unresolved.

Validation after the geometry and rate extensions: complete `scripts/check.sh`
passes with 418 Python tests, plus Ruff, documentation, builds, dependencies, and
C offline tests. No production driver changes are included.

The tool returns 2 for no independent decode, 1 for observed execution/cleanup
errors, and 0 for independent receipt. A zero exit code does not promise complete
delivery, arbitrary frame types, auto-ACK, absolute power calibration, or regulatory
enforcement. The CLI permits only channels 36/149, 20 MHz, at most 60 frames and
50 ms spacing. Offline tests cover descriptor geometry, bounded codes, exact
rate-table write order, and connac3 TX-status record sizes.
