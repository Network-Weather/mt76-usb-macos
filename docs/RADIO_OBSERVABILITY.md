# Radio observability exploration

Started 2026-09-04. Branch: `spike/radio-observability`.

Selected redacted machine-readable results are preserved in
[`radio-observability-2026-09-04.json`](../research/evidence/radio-observability-2026-09-04.json).
Detailed Group-5 word distributions are omitted from that record; commands below
regenerate them. No network identifiers, payloads, or packet hashes are included.

## Questions and experiment order

1. What is in the extended receive vectors already delivered by MT7925 USB?
   Establish group boundaries, variation by PHY mode, and agreement with independently
   decoded frame fields before assigning meanings to unknown words.
2. What link evidence is lost by the minimal control-frame parser? Decode RTS/BlockAck
   transmitter addresses, sequence windows, and acknowledgment bitmaps. Separate observer
   loss from the receiving station's reported delivery.
3. Can the two radios share a useful time base through jointly received frames?
   Measure wrap, drift, ambiguity, and residual error before using packet timing for
   cross-channel forwarding hypotheses.
4. Can a bounded controlled transmitter or documented receive-vector enable falsify
   candidate fields? Keep the reference receiver running; record recovery and failures.
5. Follow ICAP, TX-status, and Bluetooth leads when the above results identify a specific
   question. Existing negative IPI results are not a reason to repeat the same probes.

The operator authorized transmit and receive experiments on both dongles for this session,
and requested regular commits. Tools retain explicit transmit flags for future operators.
Network identifiers and payloads stay out of committed evidence. Findings remain instrument
measurements, not site-specific topology verdicts.

## Initial passive census

Reference firmware and adapters: same pair and pinned firmware as
[MT7925 MIB characterization](MT7925_MIB.md). Three seconds per target, sequential
20 MHz dwells on 2.4 GHz channel 6, 5 GHz channel 36, and 6 GHz channel 37.
These initial results came from an inline diagnostic, before the reproducible probe below.

| Adapter | Frames by band (2.4 / 5 / 6 GHz) | RX group mask |
| --- | --- | --- |
| MT7961 `0e8d:7961` | 159 / 196 / 74 | `0x07`: groups 1, 2, 3 |
| MT7925 `0846:9072` | 143 / 242 / 17 | `0x17`: groups 1, 2, 3, 5 |

A separate four-second MT7925 channel-36 dwell returned 374 Group-5 records.
Of its 24 words, words 2, 6, 7, 8, 9, 10, 19, 20, and 21 varied (nine words).
The prior conversational summary incorrectly said ten: the recorded distinct-value counts
establish nine. Word variation alone does not prove a measurement's meaning or freshness.
The capture also contained 8 RTS, 121 CTS, 5 BlockAck, and 1 ACK.

The first inline census's control-frame count used the wrong dictionary key (`type` instead
of `ftype`), so its empty control counts are invalid. The separate dwell fixed that key;
group-mask and frame-count results are unaffected.

## Reproducible receive-vector results

Tool: [`rx_vector_probe.py`](../research/rx_vector_probe.py). Output contains word
variability by PHY mode and exploratory byte/RSSI correlations, never raw frames or
network identifiers. Synthetic tests check group offsets, descriptor-length bounds,
and the Group-3 origin of connac3 HE indexes.

```bash
MT76_FW_DIR=/path/to/firmware /path/to/venv/bin/python research/rx_vector_probe.py \
  --usb-id 0846:9072 2.4GHz:6 5GHz:36:42:80 5GHz:149:155:80 6GHz:37:47:160 \
  --seconds 8 --output /tmp/mt7925-rx-vectors.json
MT76_FW_DIR=/path/to/firmware /path/to/venv/bin/python research/rx_vector_probe.py \
  --usb-id 0e8d:7961 2.4GHz:6 5GHz:36:42:80 --seconds 5 --g5-cycle \
  --output /tmp/mt7921-rx-vectors.json
```

MT7925: 416, 484, 629, and 37 normal frames respectively, all carrying Group 5.
No USB errors or FCS errors; this is a short sample, not a reliability qualification.
The third target delivered 78 HT and 3 VHT frames; the rest were legacy CCK/OFDM.
**No HE frames were present**, so the HE-field/beacon-color check was not exercised.
Group-5 word 6 bytes 0/1 repeatedly correlate with decoded RSSI (up to r=0.9983).
This is a strong lead for duplicate RCPI, not a new independent signal measurement.
Other correlations are exploratory and confounded by transmitter and frame type.

MT7961: the documented Group-5 bit **works over USB**, without RF-test mode.

| Target | Baseline | Enabled | Restored |
| --- | --- | --- | --- |
| 2.4 GHz ch 6 / 20 MHz | 295 frames, no G5 | 289 frames, all G5 | 267 without G5, 1 with G5 |
| 5 GHz ch 36 / 80 MHz | 326 frames, no G5 | 331 frames, all G5 | 332 frames, no G5 |

`MT_DMA_DCR0(0)` changed from `0x02773400` to `0x02f73400`, then back to
`0x02773400`; final readback confirmed restoration. The single G5 record after
restoration is compatible with an in-flight/buffered descriptor; transitions are not
atomic at the host. There were no USB errors or descriptor-length failures.
The short runs do not resolve the upstream warning about hardware issues. Default
driver behavior is unchanged; enabling is confined to the explicit research option.

## Paired clocks, control exchanges, and 5 GHz transmission

Tool: [`dual_radio_probe.py`](../research/dual_radio_probe.py); control helper:
[`control_frames.py`](../research/control_frames.py). Each radio has one receive
reader. Both rendezvous with the transmitter before a timed window. Matching uses
identical beacon/probe-response bytes in memory and excludes fingerprints occurring
more than once on either radio. Only counts and fit residuals leave the process.

```bash
MT76_FW_DIR=/path/to/firmware /path/to/venv/bin/python research/dual_radio_probe.py \
  2.4GHz:6 --seconds 12 --transmit 60 --rate cck1 --tx-status \
  --acknowledge-experimental-transmit --output /tmp/dual-cck-control.json
MT76_FW_DIR=/path/to/firmware /path/to/venv/bin/python research/dual_radio_probe.py \
  5GHz:36 --seconds 12 --transmit 60 --rate ofdm6 --tx-status \
  --acknowledge-experimental-transmit --output /tmp/dual-ofdm5.json
```

**A working 5 GHz transmit path was found.** Both runs submitted 60 directed Probe
Requests, 50 ms apart; the A9000 independently received all 60 with distinct sequence
numbers. The 2.4 GHz frames decoded as 1 Mb/s CCK; the 5 GHz frames as 6 Mb/s OFDM.
Both radios answered register reads after both runs. No USB errors were recorded.

The existing injector always encodes CCK. The experiment changes only its fixed-rate
TX descriptor word to `0x004b0004`: mode 1 (OFDM), legacy rate index 11 (6 Mb/s),
fixed 20 MHz bandwidth. The probe's Supported Rates element also advertises OFDM.
This narrows the old 5 GHz negative result to the CCK-only injection configuration;
it does not qualify arbitrary rates, power control, association, or MT7925 TX.
The shipped driver retains its existing behavior; rate selection is research-only.

Requesting host TX status produced **60 TXS packets on MT7961** in each run,
not TXRX_NOTIFY packets. Since these are no-ACK probes, they cannot calibrate ACK
signal quality or packet-error rate. USB submission alone remains insufficient evidence
of radiation; the A9000's independent frame decode is the criterion.

Shared receive timestamps support a tight relative time base within each dwell:

| Target | Unique shared beacons/responses | Relative clock drift | Holdout p95 absolute residual | Holdout maximum |
| --- | ---: | ---: | ---: | ---: |
| 2.4 GHz ch 6 | 573 | -1.2120 ppm | 1.086 us | 1.420 us |
| 5 GHz ch 36 | 614 | -0.7133 ppm | 0.752 us | 0.967 us |
| 5 GHz ch 149 (15 s repeat) | 30 | -0.7948 ppm | 0.635 us | 0.882 us |

A second OFDM burst on channel 149 also decoded **60/60** at 6 Mb/s. Its 60 TXS
records were format 0, PID 3, rate `0x4b`, ACK-error bits zero, power byte 44.
The rate corroborates the independent receiver. The power byte's physical units and
calibration are not established; it is not evidence of 44 dBm output. No-ACK TX
does not prove acknowledged delivery, regardless of the ACK-error bits.

The model is trained on the first half of pairs and predicts the second half; the
table is that independent holdout, not an in-sample fit. Tick rates are approximately
1 MHz against host time (host USB arrival timestamps are noisy). The timestamps are
32-bit and the fit uses modular differences. This is receiver timestamp alignment,
not time-of-flight ranging. Retuning is tested below; longer drift, temperature
dependence, and receive-pipeline offsets while on different channels remain untested.

On channel 36, each observer saw six distinct directed RTS/BlockAck endpoint pairs.
MT7961 decoded 33 compressed single-TID BlockAcks; A9000 decoded 45. Their summed
set bits were 38 and 50, respectively, and both saw two zero positions before the
last set bit. Repeated windows can count packets repeatedly, and zeros can be unsent
sequences; **neither these sums nor observer differences are a packet-loss rate**.
This establishes live endpoint/acknowledgment evidence beyond the shipped parser's
receiver-address-only control path. No endpoint identifiers are committed.

## Extended-vector cross-checks

A second passive matrix on 5 GHz ch 132 / 80 MHz and 6 GHz ch 53 / 160 MHz returned
1,370 and 1,926 frames. **Group-5 word 6's lower two bytes exactly equaled the
primary vector's two RCPI bytes in all 3,296 frames.** This validates duplicate
signal metadata, not an independent RF measurement.

The 5 GHz capture contained 17 HE-SU frames. Four transmitted by an AP with a
captured HE Operation element had matching RX-vector BSS color (4/4). This is a
small positive consistency check; the probe now also checks infrastructure direction
and includes EHT. The 6 GHz capture had 139 EHT-MU frames, excluded by the first
HE-only probe. No HE result is inferred from those EHT records.

Applying the neighboring MT7915 standalone-vector SNR extraction to MT7925 G5
word 20 gives numbers in the range 5..10 on these captures. The layout is not
established; these are explicitly named **hypothesis values**, not a noise floor
or supported SNR measurement. Low variance alone cannot validate them.

The final 15-second-per-channel pass strengthens the independently checked fields:

| PHY / target | BSS color vs beacon | Uplink bit vs infrastructure frame header |
| --- | ---: | ---: |
| HE-SU, 5 GHz ch 132 / 80 MHz | 28/28 match | 28/28 match (19 downlink, 9 uplink) |
| EHT-MU, 6 GHz ch 53 / 160 MHz | 32/32 match | 32/32 match (uplink only) |

Comparison uses the inferred infrastructure BSSID (RA on uplink, TA on downlink),
not the client's transmitter address, and ignores FCS-failed frames. No mismatches
were observed. Spatial-reuse candidates were zero throughout; their semantics are
still unvalidated. TXOP candidates varied but were not independently checked.
Another 3,135 frames had exact duplicate RCPI bytes, bringing that check to 6,431/6,431.

## Clock calibration across a retune

Tool: [`clock_retune_probe.py`](../research/clock_retune_probe.py). Both radios listen
on 5 GHz channel 36 / 20 MHz for 15 seconds. One radio tunes away for two seconds,
returns, and both listen for another 15 seconds. Neither is rebooted between phases.
The pre-excursion model predicts every matched post-excursion frame; the holdout split
is at the actual phase boundary, not half of the combined sample count.

```bash
MT76_FW_DIR=/path/to/firmware /path/to/venv/bin/python research/clock_retune_probe.py \
  5GHz:36 5GHz:149 --radio mt7921 --seconds 15 --output /tmp/clock-retune-mt7921.json
MT76_FW_DIR=/path/to/firmware /path/to/venv/bin/python research/clock_retune_probe.py \
  5GHz:36 6GHz:53:47:160 --radio mt7925 --seconds 15 --output /tmp/clock-retune-mt7925.json
```

| Moving radio / excursion | Before / after matched frames | Post-return p95 prediction error | Maximum |
| --- | ---: | ---: | ---: |
| MT7961, 5 GHz ch 149 / 20 MHz | 842 / 792 | 1.751 us | 2.323 us |
| MT7925, 6 GHz ch 53 / 160 MHz | 824 / 854 | 0.786 us | 1.085 us |

These results support clock continuity through the tested band/channel/width changes,
with approximately 32.5 seconds spanned by each experiment. They do not measure a
channel-dependent timestamp bias while the radios are apart, or establish long-term
clock stability. Exact-frame matching itself does not infer forwarding: forwarded
traffic generally changes its 802.11 header and cannot use the same matching rule.
Both radios remained register-responsive and reported no USB errors.

## Verification and next evidence needed

The full project gate passed during this work: formatting/lint, documentation, Python
tests, source/wheel builds, dependency checks, and C build/offline tests. The final Python
suite has 400 passing tests on this host, including four optional independent TShark
checks. TShark 4.6.8 (`e677bf052328`) agrees on compressed BA type, starting sequence,
bitmap length, and acknowledgment count for synthetic 64/256/512/1024-bit bitmaps.
Unsupported BA variants are explicit; trailing zero bitmap positions are not called loss.

Next experiments, in order of new evidence they could provide:

1. Validate extended RXV fields across more transmitters and conditions; investigate
   per-chain quality with documented layouts, not arbitrary byte correlations.
2. Test cross-channel clock biases with a known timing reference, longer drift, and
   periodic recalibration before using timing to correlate backhaul forwarding.
3. Associate observed BlockAck windows with matching data sequences and TIDs, retaining
   separate labels for receiver-reported receipt, observer visibility, and retransmission.
4. Characterize higher-level TX status with a cooperating receiver if acknowledged
   traffic is needed; no-ACK probes cannot establish bidirectional link quality.
5. Pursue ICAP/true noise-floor interfaces as a separate spike. No non-Wi-Fi classifier,
   calibrated SNR, calibrated power setting, or complete mesh reconstruction was obtained.

## Source evidence and limitations

All mt76 references in this section are at `c5a3bd91aa735b669618610d5f0ebfa5786845a6`.

- `mt7925/mac.c:mt7925_mac_fill_rx` describes Group 3 as four words and Group 5 as
  24 words; the local `rxd_connac3.py` steps over Group 5 without decoding it.
- `mt76_connac3_mac.c:mt76_connac3_mac_decode_he_radiotap` reads BSS color, TXOP,
  uplink indication, spatial reuse, and other fields from extended RXV words. Its indexes
  start at Group 3, not Group 5. This distinction must be tested.
- `mt7915/mac.c:mt7915_mac_fill_rx_vector` reads in-band/wideband RSSI, SNR, and
  frequency offset from a standalone RX-vector record. That is a different record type
  and chip; its offsets cannot be pasted into the MT7925 Group-5 decoder.
- `mt792x_mac.c:mt792x_mac_init_band` clears `MT_DMA_DCR0_RXD_G5_EN`, commenting
  that it disables RX rate reporting because of hardware issues. The userspace path
  nevertheless receives Group 5 on the A9000. Neither fact establishes that every field
  is correct. The corresponding MT792x register is band-0 `0x820e7000`, bit 23.
- `mt76_connac3_mac.h` contains MPDU-format TX-status noise/RCPI fields. Presence in a
  shared header is not evidence that MT7925 USB emits that format or valid noise values.
- Plaintext MT7961 region 1 contains `Current FWOpMode isn't ICAP`, `EvmRx%d=0x%02x`,
  and CFO diagnostics. This is evidence of code concepts, not a working host API.

## Interpretation boundaries

Received signal is the transmitter-to-observer path, not a measurement of the backhaul
receiver's signal. Clock agreement, packet correlation, four-address traffic, and advertised
Multi-AP/MLO roles are complementary evidence; none individually reconstructs an entire
mesh. A missing observed ACK or MPDU is not proof that the receiver missed it.
Per-frame signal quality is not an idle-channel noise survey. ED-active time remains
overlapping energy detection, not a non-Wi-Fi-only counter.
