# MT7925 UNI MIB characterization

Date: 2026-09-04

## Result

The Netgear A9000's MT7925 firmware exposes useful live radio-environment
counters through connac3 `MCU_UNI_CMD_GET_MIB_INFO` (`0x22`).  Passive hardware
measurements now support a working, though partly provisional, counter map:

| Offset | Provisional meaning | Confidence | Observed behavior |
| ---: | --- | --- | --- |
| 0 | RX FCS/error count | Medium | Rises most on busy/noisy channels; zero on the quiet 6 GHz sample |
| 2 | delivered RX MPDU count | High | Matched decoded frames within 0-3 frames in every atomic-sampled dwell |
| 7 | saturated/read-side artifact | High | Advanced by exactly 65,535 on every 3-6 second dwell, independent of traffic and width |
| 11 | PHY receive attempts / MDRDY count | High | Always at least the delivered MPDU count and grows when the PHY detects frames it does not deliver |
| 12 | CCK MDRDY duration, microseconds | High | Active only on 2.4 GHz and, with offset 13, closely tracks reconstructed receive airtime |
| 13 | OFDM/HT/VHT/HE/EHT MDRDY duration, microseconds | High | Tracks reconstructed receive airtime on 5 and 6 GHz, where CCK cannot occur |
| 17 | broader busy-time counter, possibly CCA+NAV(+TX) | Medium | Closely tracks offset 19 and normally exceeds decoded receive duration; direct reference comparison is compatible but not conclusive |
| 18 | width-dependent/unknown duration | Low | Tracks wall time at 20 MHz but becomes a variable, usually small duration at 40/80/160 MHz; it is not a general clock or usable occupancy value |
| 19 | primary CCA busy duration, microseconds | Medium-high | Exceeds decoded receive duration and closely tracked an independent MT7921 `P_CCA_TIME` reference on repeated 6 GHz samples |
| 20 | primary energy-detect duration, microseconds | High | Nearly equals the busy counters on 2.4 GHz, is tiny on ordinary 5 GHz traffic, and rises under controlled valid Wi-Fi load; it is not non-Wi-Fi time |
| 32 | unknown event count | Low | Intermittent, most visible during wide 5 GHz capture |

The names for 12, 13, 17, 19, and 20 are behavioral identifications, not a
published MT7925 enum.  Their relationships match MediaTek's documented MT7915
MIB instruments:

```text
CCK_MDRDY_TIME + OFDM_MDRDY_TIME  ~= decodable PHY receive duration
P_CCA_TIME                         >= PHY receive duration
CCA_NAV_TX_TIME and P_CCA_TIME     are closely related busy-time counters
P_ED_TIME                          overlaps P_CCA_TIME; it is not additive
```

Offset 19 is now the best-supported `P_CCA_TIME` identification. Offset 17 is a
closely related, usually broader busy-time counter, but passive data does not
prove that it is `CCA_NAV_TX_TIME`: offset 17 is larger on channel 36, while
offset 19 is slightly larger on channel 149. Offset 20 is a valuable view of
energy detection, but it must not be labeled "non-Wi-Fi time": energy-detect
can overlap valid Wi-Fi and its threshold is not calibrated.

## Hardware and method

- Adapter: Netgear A9000, USB `0846:9072`, chip ID `0x7925`.
- Initial matrix: passive monitor receive only.
- Controlled follow-up: bounded probe-request transmission, as described below.
- Bands exercised: 2.4, 5, and 6 GHz.
- Widths exercised: 20, 40, 80, and 160 MHz.
- Driver/tooling: `mt76-usb-macos` 0.3.0.
- RAM firmware SHA-256:
  `23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`.
- Patch firmware SHA-256:
  `8eb46014d2a6b4124472eee7476d995008a6f40b1daffef87eb42f30d98699e1`.

The characterization tool sends the MT7996-shaped UNI request: a four-byte band
header followed by one or more `{le16 tag, le16 len, le32 offset}` TLVs.  The
firmware returns echoed offsets and 64-bit values.  All selected offsets are read
in one request immediately before and after the receive dwell, so they share the
same sampling interval.  Frame airtime is aggregation-aware: an A-MPDU is charged
one preamble rather than one preamble per subframe.

Tool: [`mt7925_mib_characterize.py`](../research/mt7925_mib_characterize.py)

## Relationship to the existing MT7921 evidence

The MT7921 work already on `main` supplies controls which strengthen this
characterization's method:

- It independently establishes that the MT7921 injector's 2.4 GHz frames reach
  the air and that a 32-byte injected frame occupies 480 microseconds after the
  hardware-appended FCS. This agrees with the 60-frame/28,800-microsecond
  calibration used here.
- It corrects counter windows to use the interval the counter reads actually
  span, uses aggregation-aware decoded airtime, and refuses to calculate a
  busy-minus-decoded residual when CCA and decoded airtime cover different
  bandwidths. The local MT7925 tools already use midpoint-to-midpoint counter
  intervals, aggregation-aware airtime, atomic UNI batches, and explicit
  primary-channel scope.
- Its controlled MT7921 burst did not distinguish `P_CCA_TIME` from
  `CCA_NAV_TX_TIME`; ambient NAV changed more than the injected TX contribution.
  That negative result directly supports retaining only the behavioral name
  "broader busy time" for MT7925 offset 17.

The earlier [`uni_mib_probe.py`](../research/uni_mib_probe.py) result records the
initial offset sweep and intentionally leaves the MT7925 counters unidentified.
The experiments here extend that evidence with atomic multi-counter reads,
multi-band and multi-width behavior, controlled Wi-Fi traffic, primary rotation,
and an identified MT7921 counter as an independent reference.

One upstream conclusion needs narrowing: offset 18 advances at wall-clock rate
in 20 MHz mode, which does support a microsecond unit, but the width sweep here
shows that it is not a free-running clock in general. It becomes small and
variable at 40/80/160 MHz. The semantic identification is withdrawn while the
20 MHz unit evidence is retained.

## Representative evidence

Percentages below use the atomic counter interval.  Decoded airtime uses the
receive-loop interval, which differs by only the two bounding MCU round trips.

| Target | Decoded frames | Decoded airtime | offs 12 | offs 13 | offs 17 | offs 19 | offs 20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2.4 GHz ch 1, 20 MHz | 695 | 15.37% | 12.80% | 0.69% | 31.44% | 30.62% | 29.96% |
| 2.4 GHz ch 6, 20 MHz | 123 | 7.67% | 7.43% | 0.04% | 30.82% | 30.44% | 30.40% |
| 2.4 GHz ch 11, 20 MHz | 649 | 24.78% | 24.23% | 0.97% | 35.93% | 34.74% | 33.30% |
| 5 GHz ch 36, 20 MHz | 367 | 2.27% | 0.00% | 2.50% | 3.04% | 2.81% | 0.04% |
| 5 GHz ch 36, 80 MHz | 466 | 2.10% | 0.00% | 2.55% | 3.07% | 2.84% | 0.04% |
| 5 GHz ch 149, 20 MHz | 220 | 0.57% | 0.00% | 0.80% | 1.31% | 1.42% | 0.16% |
| 5 GHz ch 149, 80 MHz | 306 | 1.29% | 0.00% | 1.35% | 1.84% | 2.02% | 0.15% |
| 6 GHz ch 37, 160 MHz | 49 | 0.04% | 0.00% | 0.03% | 0.10% | 0.10% | 0.08% |

These are short observations of the local RF environment, not stable channel
rankings.  The important evidence is how the candidate counters move relative
to each other and to decoded traffic.

## Controlled Wi-Fi perturbation

The passive matrix was followed by bounded injection from the attached MT7921U
adapter. The A9000 remained the receiver. Both radios were tuned to 2.4 GHz
channel 6, the transmitter used the injector's fixed 1 Mb/s CCK rate and a
locally administered source address, and both adapters answered normally after
each burst.

Tool: [`mt7925_mib_perturb.py`](../research/mt7925_mib_perturb.py)

### Calibration burst

A 60-frame wildcard Probe Request burst was received 60-for-60 by the MT7925.
The arithmetic airtime was 28,800 microseconds. This established that the
intended frames reached the air and the receiver before interpreting counters.

### Wildcard response-amplification burst

A 300-frame wildcard burst was intentionally bounded at the existing injector's
tested ceiling. The MT7925 saw 298 injected frames but 1,090 total frames: nearby
APs answered the wildcard requests, turning the burst into a larger but still
unambiguously valid Wi-Fi perturbation.

| Measurement | Baseline before | Wi-Fi perturbation | Baseline after |
| --- | ---: | ---: | ---: |
| Decoded airtime | 12.65% | 50.72% | 18.47% |
| Offset 12, CCK duration | 12.20% | 48.25% | 17.87% |
| Offset 17, busy candidate A | 38.94% | 69.42% | 42.01% |
| Offset 19, busy candidate B | 38.62% | 69.96% | 41.88% |
| Offset 20, ED-active | 38.54% | 69.25% | 41.54% |

This is the decisive negative result for a tempting interpretation: **offset
20 is not non-Wi-Fi time**. It responds strongly to valid 802.11 traffic.
Energy detection can overlap normal Wi-Fi reception, especially on 2.4 GHz.

### Directed isolation burst

The test was repeated with 300 directed Probe Requests for a synthetic,
nonexistent SSID so nearby APs would not answer. The MT7925 received all 300;
584 total frames were decoded versus 269 and 312 in the bounding baselines.
Offset 2 again equaled the total decoded-frame count in every phase. The
arithmetic injected airtime was 172,800 microseconds.

Ambient channel occupancy fell between the first and second baseline, from
about 44% to 35%. The injected phase also measured about 35%, so subtracting a
single baseline would falsely conclude that transmitted frames reduced busy
time. This run is evidence for counter inclusion and receive accounting, but
not a precise busy-time response coefficient. Longer alternating trials or a
quieter controlled environment are required for that estimate.

### Alternating and independent-reference runs

The 300-frame ceiling was then split into three 100-frame directed bursts with
four interleaved baselines. Every synthetic frame was received. Natural CCK
airtime still varied by more than the 57,600 microseconds injected per phase,
so the experiment again refused to derive an absolute response coefficient.

The MT7921U's already identified `P_CCA_TIME` and `CCA_NAV_TX_TIME` counters were
then sampled simultaneously as an independent reference. A final passive-only
cross-check covered 2.4 GHz channel 6, 5 GHz channels 36 and 149, and 6 GHz
channel 37.

Tool: [`mt7925_mib_crosscheck.py`](../research/mt7925_mib_crosscheck.py)

On 6 GHz, where both receivers observed a quiet and relatively simple channel,
MT7925 offset 19 closely followed the MT7921U primary CCA counter:

| Sample | MT7925 offset 19 | MT7921U `P_CCA_TIME` | Absolute difference |
| --- | ---: | ---: | ---: |
| Initial | 0.650% | 0.631% | 0.019 pp |
| Repeat 1 | 1.766% | 1.679% | 0.087 pp |
| Repeat 2 | 0.890% | 0.752% | 0.138 pp |

This rules out the hypothesis that offset 19 merely has an arbitrary scale and
is the strongest current evidence that it is MT7925 primary CCA time.

Absolute readings diverged on busier 2.4 and 5 GHz channels. On channel 6,
MT7925 offset 19 read 40.5% while MT7921 primary CCA read 18.1%. This is not
explained by a counter-unit mismatch: the A9000 also reported materially more
receive duration and failed/detected receptions on affected channels. Different
antennas, placement, receiver sensitivity, and ED thresholds cause two radios
to observe different effective environments. Survey percentages should
therefore be compared over time on the same instrument, not treated as
hardware-independent absolute truth.

### Count counters

Offset 2 is especially well identified:

| Target | Decoder frames | Offset 2 delta | Offset 11 delta |
| --- | ---: | ---: | ---: |
| 2.4 GHz ch 1 | 695 | 696 | 845 |
| 2.4 GHz ch 6 | 123 | 123 | 129 |
| 2.4 GHz ch 11 | 649 | 650 | 791 |
| 5 GHz ch 36 | 367 | 368 | 408 |
| 6 GHz ch 37, 160 MHz | 49 | 49 | 63 |

Offset 2 therefore behaves like delivered MPDUs.  Offset 11 behaves like the
larger set of detected PHY receptions, including receptions which do not become
delivered frames.

### Receive-duration partition

At 2.4 GHz, `offset 12 + offset 13` closely follows decoded airtime.  On 5 and
6 GHz, offset 12 is exactly stationary and offset 13 alone follows decoded
airtime.  This is the falsifiable signature of CCK duration versus the combined
OFDM-family duration.  The small differences are expected: hardware duration
and reconstructed airtime do not have exactly the same frame acceptance window,
and the decoder model estimates several PHY components.

### Busy and energy candidates

On 5 GHz channel 36 the ordering was:

```text
decoded/OFDM duration < offset 19 < offset 17
offset 20 is close to zero
```

This is compatible with primary CCA, CCA extended by NAV, and a separate
ED-active counter. It is not sufficient to assign the first two names: on
channel 149, offset 19 was 0.11-0.17 percentage points above offset 17. On 2.4
GHz, offset 20 rises close to both on channels 1, 6, and 11. That could be a real
energy-detection blind spot, a local broadband source, or band-specific ED
behavior. A controlled non-Wi-Fi perturbation is required before it can support an
interference diagnosis.

### Width behavior

On the same 5 GHz primary channel, offsets 13, 17, 19, and 20 remained in the
same range at 20, 40, 80, and 160 MHz.  They appear scoped principally to the
primary channel rather than to the entire configured capture width.  Offset 18
advanced at approximately one microsecond per microsecond only in 20 MHz mode;
at wider settings it advanced by roughly 0.1% of the dwell.  It must not be used
as generic channel time until its mode dependency is explained.

### Primary-channel rotation inside one 80 MHz block

The center channel was then held at 42 while the primary rotated through all
four 20 MHz channels in the same 80 MHz block. This changes the primary without
changing the spectrum covered by the wide receiver:

| Primary / center / width | Decoded airtime | Offset 17 | Offset 19 (`P_CCA`) | Offset 20 (`P_ED`) |
| --- | ---: | ---: | ---: | ---: |
| 36 / 42 / 80 | 1.66% | 2.98% | 2.69% | 0.03% |
| 40 / 42 / 80 | 0.04% | 0.31% | 0.19% | 0.02% |
| 44 / 42 / 80 | 0.80% | 2.15% | 1.75% | 0.05% |
| 48 / 42 / 80 | 4.80% | 5.06% | 4.79% | 2.61% |

Offsets 17, 19, and 20 follow the selected primary 20 MHz channel, not the whole
80 MHz block. This also explains why keeping primary 36 fixed while changing
configured width produced similar values: the measurement scope stayed on
primary 36. Offset 18 did not show usable whole-block or secondary-channel
behavior and remains unidentified.

## Instrument interpretation

For a downstream survey instrument, the useful measurement model is now:

1. **Delivered Wi-Fi:** offset 2 plus decoded per-frame PHY metadata.
2. **Detected but not delivered:** offset 11 minus offset 2.
3. **Decoded PHY duration:** offsets 12 and 13.
4. **Primary-channel occupancy:** offset 19, retaining offset 17 beside it as an
   experimental broader-busy counter.
5. **NAV extension:** not derived yet; subtracting 17 and 19 would be premature.
6. **Energy detection:** offset 20, reported separately rather than
   called non-Wi-Fi.

For downstream 40/80/160 MHz characterization, this primary-channel view is not
sufficient. The now-validated method is to rotate the primary and dwell on each
constituent 20 MHz channel. A consumer can then evaluate the wide block without
mistaking one clean primary for a clean 80/160 MHz span.

## Next falsification tests

1. Repeat each channel over multiple minutes and times of day to establish
   variance and counter rollover.
2. Use a controlled 2.4 GHz non-Wi-Fi source at a known distance and confirm
   whether offset 20 changes selectively while offsets 12/13 do not.
3. Repeat the completed controlled Wi-Fi test in alternating short phases or a
   shielded/quieter environment to overcome the observed ambient drift.
4. Repeat the completed primary-rotation experiment across a 160 MHz block to
   verify that the same scope rule holds with eight constituent channels.
5. Search for an enable TLV for the zero MT7996-style counters 26-29; a true
   `NON_WIFI_TIME` counter would be preferable to interpreting ED time.
