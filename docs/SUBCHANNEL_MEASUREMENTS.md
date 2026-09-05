# MT7925 NAV, idle slots and subchannel measurements

2026-09-05; pinned RAM SHA256
`23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`.

## Result and naming correction

The firmware exposes separate NAV time, RX FCS-good count, three secondary-CCA
fields and eight ED-index fields through ordinary UNI22 queries. They change
during passive capture, without counter-enable writes or TX. The eight ED
indices are not yet eight validated absolute channel labels: primary rotation,
configured bandwidth and inactive-width artifacts matter.

The newly located [vendor UNI counter enum](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h#L2649)
names17 primary CCA,18 secondary CCA,19 CCA+NAV+TX. This **supersedes our earlier
tentative17/19 assignments**. The [UNI-to-ROM trace](MT7925_MIB.md) independently
resolves the hardware fields; related register names alone are insufficient.
Source names do not establish configured source selection, exact tick units,
calibration, or an additive decomposition of channel occupancy.

## Independently resolved fields

The ordinary mapper is ROM`0x8334a6` → domain29 mapper`0x83299a`, register table
`0x84d79c`, band0 base`0x820ed000`. Exact translation and descriptor addresses
are preserved in the evidence. Only source-selected entries were read; no RAM
or command-space sweep and no new direct hardware-counter reads were used.

| UNI offset | Internal ID | Hardware field | Source name / interpretation limit |
| ---: | ---: | --- | --- |
| 7 | 247 | `0x820ed020[15:0]` | Idle slots;16-bit saturation |
| 11 | 114 | `0x820ed994[31:0]` | MDRDY count |
| 12 | 211 | `0x820edb60[31:0]` | CCK MDRDY duration |
| 13 | 212 | `0x820edb64[31:0]` | OFDM-family MDRDY duration |
| 16 | 124 | `0x820ed9bc[31:0]` | Length mismatch; trigger not tested |
| 17 | 214 | `0x820edb6c[31:0]` | Primary CCA |
| 18 | 215 | `0x820edb70[31:0]` | Secondary CCA; invalid occupancy at20MHz |
| 19 | 0 | `0x820ed024[23:0]` | CCA+NAV+TX |
| 20 | 2 | `0x820ed030[23:0]` | Primary ED; not non-Wi-Fi-only |
| 32 | 122 | `0x820ed9b4[31:0]` | RX out-of-range; not a distance measurement |
| 52 | 1 | `0x820ed028[23:0]` | NAV time |
| 84 | 48 | `0x820ed7ec[31:0]` | RX FCS-good; not NSS2/MCS7 |
| 91–93 | 217–219 | `0x820edb78/7c/80[31:0]` | Secondary20/40/80 CCA |
| 94 | `0xffff` | No valid translation | Secondary160 source enum exists; **not queried** |
| 95–102 | 220–227 | `0x820edb88 + 4*i[31:0]`,i0…7 | Eight20MHz-named ED indices |

Offset7 takes the ROM's special packed-field path, key`0x1d20c1`, descriptor
`0x84dfcc` / field table`0x85575c`. Unlike the ordinary read accessor, this path
extracts the selected field and writes back the word with that field cleared
(`0x83352e..0x833548`). This is firmware's existing query behavior, not a new
host register-write recipe. Other consumers still must not compete for counts.

## Passive width/primary controls

Two one-second windows each at ch36/20,36/40(center38),36/80(center42),48/80,
36/160(center50),64/160, then36/20. One UNI request samples all23 exact offsets
at each boundary. Received frames are counted anonymously; MCU response waits
can discard frames, and sequential TLV reads are not simultaneous hardware
latches. A common request interval is useful but does not remove those gaps.

The first run's representative **raw tick** vectors, indices0…7:

| Width / primary | ED0…7 |
| --- | --- |
| 20 / 36 | 1675,1334,1334,1334,1334,1334,1334,1334 |
| 40 / 36 | 2013,1838,1671,1671,1671,1671,1671,1671 |
| 80 / 36 | 3009,18173,12686,44983,2029,2029,2029,2029 |
| 80 / 48 | 2243,14724,2310,40238,1890,1890,1890,1890 |
| 160 / 36 | 2268,13432,6758,32461,7120,1514,1513,14115 |
| 160 / 64 | 632,12654,4609,30820,6091,456,456,12804 |

This is useful evidence of multiple live ED measurements in one capture, not
proof of their absolute RF frequency order. On80MHz, ch36 primary ED tracks
index0 and ch48 tracks index3 roughly. On160MHz with primary64, the primary-ED
query is441/468 ticks while index7 is12804/12751; that comparison does not
validate a simple index-to-channel assignment. Different source selections or
thresholds could contribute. Do not label or normalize these entries into a home
channel heatmap yet. No gain, sensitivity or non-Wi-Fi attribution is inferred.

Width-invalid CCA fields show an especially dangerous artifact:

- At20MHz, offsets18/91/92/93 advance about1,003,520–1,011,712 ticks per window.
- At40MHz, secondary20 offset91 gives5378/4240, while92/93 remain near wall time.
- At80MHz,91/92 are variable, while93 remains near wall time.
- At160MHz, all three secondary-width fields vary below wall time.

Thus a disabled/nonexistent secondary can look fully busy. The reproducer
retains the raw values but excludes width-inapplicable fields from its summary.
Offset18 roughly follows91, consistent with a selected secondary-CCA source;
neither is a free-running clock.

Separate NAV offset52 is live: ch36/20 gives80809/88430 ticks, ch48/80 gives
2296/2657, ch36/160 gives72029/115568 and ch64/160 gives519/492. Do not compute
NAV by subtracting17 from19; overlapping sources and potentially different tick
units prevent that interpretation. FCS-good84 equals delivered-MPDU2 in all14
windows, within0–3 of decoded good frames; filtering/aggregation differences
under other traffic remain unqualified.

A fresh repeat reproduces the width-invalid CCA plateaus, distinct active ED
vectors and primary-sensitive NAV. FCS-good84 differs from MPDU2 by at most one
in three of14 windows and matches in the other11; decoded frames differ from
MPDU2 by up to four, retaining sequential-query/capture gaps rather than imposing
an exact identity. Both runs receive normally and reload cleanly.

## RF-center and primary-rotation follow-up

Two fresh10-window80MHz primary rotations36→40→44→48→36 reproduce a broadly
stable ED vector but different primary-ED/NAV readings. For example, first-run
primary40 ED is1958/2049 ticks while index1 is14514/14627; primary44 ED is
2722/2476 while index2 is11209/10852. Therefore even at80MHz these counters
cannot yet be equated by simple index matching. The repeat shows the same
mismatch. This does not prove the index order is wrong: primary and secondary
ED sources/thresholds or PHY mapping may differ.

A separate return-controlled center rotation42→58→106→155→42 changes the
vectors substantially while keeping80MHz and the lowest primary per block:

| Center / primary | First-window ED0…3 raw ticks |
| --- | --- |
| 42 / 36, before | 1959,14577,9865,40504 |
| 58 / 52 | 5869,286,264,323 |
| 106 / 100 | 10539,133,133,15243 |
| 155 / 149 | 994,8607,1341,9062 |
| 42 / 36, after | 2237,14869,10180,40931 |

This demonstrates RF-center-dependent readout and a returning pattern, rather
than a fixed vector independent of tuning. It does not distinguish external
interference from adapter/host emissions or validate per-index RF frequencies.
No signal-source identity, threshold sensitivity or calibration is inferred.

Four source-defined MIB configuration words remain identical across all center
steps and across the primary-rotation repeat:
`0x820ed000=0x7e25f808`, `004=0x00f8c310`, `008=0x0000100f`,
`010=0x3fc301cf` (abbreviated addresses retain the same base).
They are read only; no configuration edit was used to obtain these results.
Other PHY configuration can still change on a retune. All three follow-up runs
pass alive and normal-reload checks. The
[separate sanitized follow-up evidence](../research/evidence/subchannel-rotation-2026-09-05.json)
preserves the full counter windows and control words.

The same reproducer supports`--suite primary80` or`--suite centers80`, with
optional`--read-controls`. Its default remains the original width matrix.

## Idle slots: usable at shorter cadence

The old3–6 second dwells always added65,535. The newly resolved16-bit field
explains why: short sampling recovers varying counts. On ch36/20 after the width
matrix, requested inter-query delays0/2/10/100/500/1000ms give
154/520/1346/10481/48933/65535 respectively. Actual midpoint intervals are in
the evidence and include USB/firmware overhead; zero requested delay is not zero
measurement time. This is a saturating idle-slot instrument, not microseconds
and not an inherently constant firmware placeholder. Slot duration and busy
backoff conditions still need qualification before deriving utilization.
The fresh repeat gives228/565/1390/9853/48447/65535 at the same requested delays.

## Units and ownership

The [related detailed MT6655 header](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/chips/coda/mt6655/bn0_wf_mib_top.h)
describes slots for idle,1µs for primary/secondary CCA and1.024µs for some other
duration counters. Its addresses do not match all our firmware-derived fields;
these are unit hypotheses, not a calibration transfer. The earlier survey
percentages assumed1µs per tick and should retain that qualification. The
24-bit fields cannot be assumed lossless across long intervals merely because
the firmware returns a64-bit accumulated total. Saturation/wrap timing of each
duration field is not measured here.

Use one counter owner and UNI-only sampling for normal acquisition. The
[FCS/MPDU ownership experiment](MT7925_MIB.md) demonstrates direct reads stealing
samples from firmware; this probe makes no direct counter reads. Both new
mapping runs and both passive matrices pass alive/normal-reload checks.

Reproducer: [`mt7925_subchannel_probe.py`](../research/mt7925_subchannel_probe.py)
with`--acknowledge-consuming-counters`.
[Sanitized evidence](../research/evidence/subchannel-measurements-2026-09-05.json)
contains selected ROM descriptors, anonymous counts and request timing; no
firmware code, ambient identifiers or packet bytes. Production APIs unchanged.
