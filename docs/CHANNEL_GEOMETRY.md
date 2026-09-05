# Controlled channel geometry, 2026-09-04

Started after merging receiver evidence and MT7925 transmission into local main
at `559fecd`. This is instrument characterization, not a network-specific verdict.

Question: does an 80 MHz monitor configuration decode an independent 20 MHz OFDM
transmission anywhere inside its frequency span, or does the selected primary
channel matter? Passive traffic counts alone cannot answer this: traffic changes
while the observer retunes. The now-working [controlled transmit paths](MT7925_TRANSMIT.md)
provide labeled, byte-exact inputs instead.

## Method and acceptance criteria

[`channel_geometry_probe.py`](../research/channel_geometry_probe.py) sends 12
directed no-ACK OFDM 6 Mbps Probe Requests per phase, 50 ms apart, for seven phases
(84 frames total). Transmit width is always 20 MHz; transmit channels are 36/44.
Receive configurations vary, with 80 MHz center held at 42 and primary set to
36 or 44. Each capture lasts three seconds, starting 300 ms before submission.

The attached ALFA MT7961 `0e8d:7961` and A9000 MT7925 `0846:9072` share a host;
firmware hashes are recorded. Both capture loops are active in each phase, so TX
status is drained while the other radio receives. Each phase has its own sequence
range; only exact matches to the controlled synthetic frame count. Stale frames
from the preceding dwell cannot count as reception in the next one. No ambient
addresses, hashes, or frame payloads are serialized.

```bash
./.venv/bin/python research/channel_geometry_probe.py --transmitter mt7921 \
  --acknowledge-experimental-transmit --output /tmp/geometry-mt7925-observer.json
./.venv/bin/python research/channel_geometry_probe.py --transmitter mt7925 \
  --acknowledge-experimental-transmit --output /tmp/geometry-mt7921-observer.json
```

For evidence of primary-dependent visibility, require successful same-primary
20/80 MHz controls at both transmit frequencies, a successful return control,
and responsive radios throughout. Compare off-primary counts only after those
controls succeed. TX-status records alone do not prove delivery. The script's
exit code describes execution health, not whether every transmitted frame arrived.

No new register definitions are needed: the experiment composes previously tested
tuning and OFDM TX helpers. The MT7925 transmitter uses DIS_MAT and its programmed
rate table; cleanup reloads its firmware. Both devices return to channel 36/20 MHz.
Production driver files are unchanged.

## MT7925 observer, MT7961 transmitter

Redacted [machine-readable evidence](../research/evidence/channel-geometry-mt7925-2026-09-04.json)
includes all phases, TX status aggregates, and firmware hashes.

| Phase | TX channel | RX primary | RX center | RX width | Byte-exact received / sent |
|---|---:|---:|---:|---:|---:|
| 0: initial control | 36 | 36 | 36 | 20 | 12/12 |
| 1: matching primary | 36 | 36 | 42 | 80 | 12/12 |
| 2: other primary, same span | 44 | 36 | 42 | 80 | 0/12 |
| 3: narrow control | 44 | 44 | 44 | 20 | 12/12 |
| 4: matching primary | 44 | 44 | 42 | 80 | 12/12 |
| 5: other primary, same span | 36 | 44 | 42 | 80 | 0/12 |
| 6: return control | 36 | 36 | 36 | 20 | 12/12 |

All 60 received frames report OFDM 6 Mbps, PHY width 20 MHz, and the correct
36/44 descriptor channel. Same-primary medians range from -39 to -42 RSSI.
The transmitter returns 12 TX statuses per phase, all raw rate `0x4b`, raw power
44, and zero error bits. Both radios pass all seven alive checks and cleanup.

This is a clear limitation of the tested capture configuration: increasing the
receive width to 80 MHz is **not equivalent to four independent 20 MHz observers**.
It does not prove the off-primary signals are absent from the RF front end or
energy counters, nor distinguish demodulator behavior from firmware filtering.
It does not characterize HE/EHT, duplicate legacy transmissions across subchannels,
40/160 MHz receive configurations, or arbitrary signal levels.

For Network Weather, survey and topology-inference records need the configured
**primary channel as well as center and width**. A missing frame on another primary
inside the same span cannot safely imply a dead node, packet loss, or an absent
backhaul. The existing channel-149 missing-QoS observation is still unexplained;
this experiment does not retroactively assign it a cause.

## Reverse direction: MT7961 observer, MT7925 transmitter

The [reverse-direction evidence](../research/evidence/channel-geometry-mt7921-2026-09-04.json)
uses the same seven phases. Independent byte-exact receive counts are
`12, 12, 0, 12, 11, 0, 12` out of 12 submitted per phase. The one missing frame
in phase 4 is unexplained; the same-primary control is strong but not perfect.
Same-primary median RSSI is -49 to -52. Every phase returns 12 TX status records,
raw OFDM rate `0x4b`, power 26, zero error bits. All alive checks pass, as does
the MT7925 firmware reload and both radios' return to 36/20 MHz.

Thus both chipsets show the same tested primary dependence. Across both runs,
119/120 matching-primary control frames are decoded, versus 0/48 other-primary
frames. The MT7925 rate-table entry also survives the channel retunes in this
experiment; it does not need to be reprogrammed for every phase.

This result motivates primary-aware coverage accounting, not a change to the
driver's supported 80 MHz wide-PPDU receive capability. It remains a test of
20 MHz OFDM probes, not every waveform an 80 MHz receiver can decode.
