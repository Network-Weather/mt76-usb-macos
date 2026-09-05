# MT7925: multi-bin, channel-dependent PHY histograms

**A firmware-traced histogram engine works in normal monitor mode and responds
to channel changes.** Channel6 repeatedly concentrates samples in bins7–8;
channel36 concentrates them in bin0; returning to channel6 restores the earlier
distribution. Two firmware-referenced register views have different bin values
but exactly equal totals in all eight windows. This is a useful new measurement
surface, **not yet a calibrated noise-floor reading or interference classifier**.

Unlike [MT7961's bin0-only observations](LEGACY_PHY_HISTOGRAM.md), this result
demonstrates a nontrivial distribution. No transmitter or ambient frame decoder
was used. Firmware thresholds, receiver gain, signal inclusion/exclusion and
physical chain provenance still need qualification before using dBm labels.

## Recovered engine and a distinct host-command path

Pinned MT7925 RAM SHA-256:
`23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`.
Source [UNI command/event enums](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h#L227)
name ID0x36 NOISE_FLOOR. A bounded live command-table read at `0221c04c`
locates handler `e0053786`. It tests an internal-buffer u16 at+0x34 for2, then
calls initializer `e00532bc`. The later [dispatcher trace](MT7925_UNI_DISPATCH.md)
places +0x34 at the first TLV after the standard header and four reserved bytes.
The initial direct-control experiments sent no UNI36; the later one-shot test
below validates that host request and its asynchronous measurement event.

Initializer `e00532bc` registers callback `e0054194` on timer state `0224c3e8`,
calls wrapper `e0078ffe` four times, and arms a timer with argument500 (time unit
not validated here). The four calls are **index0 reset, index0 enable, index1
reset, index1 enable**. These are raw helper indices: the physical band/chain
mapping must not be inferred uniformly across register blocks. Wrapper `e0078ffe` calls
ordinary histogram helper `e005ae5e`:

| Operation | Index0 hardware effect |
| --- | --- |
| 0 reset | `83088230` bit29 clear → set → clear; preserve other bits |
| 1 enable | Set `83082004` bits2:0 to5; preserve other bits |
| 2 stop/read | Clear those three bits, copy requested u32 bins from `83088600`, copy ten threshold labels |

Firmware adds `index << 16` to these addresses. The direct-control reproducer
writes only index0 and reads eleven counters, never an arbitrary count.
**MT7925's enable helper does not write `83088234`**, unlike MT7961's helper.
No sibling-chip option bits were added to the test.

Operation2 references ten signed bytes at GP+18220 = `02216f2c`:
−92, −89, −86, −83, −80, −75, −70, −65, −60, −55. These live labels match the
older engine, but are not a demonstrated conversion from bins to received dBm.

The timer callback uses a different getter: `e007900c` → `e005af12` stops both
control indices and reads eleven words each from **`83001000` and `83011000`**. Result
formatter `e0054118` constructs EID0x36 with tag2/length92 and two44-byte arrays.
This is an event-producing path, not merely firmware log output. The later
one-shot test validates it. The initial test independently reads only
the **index0** view at `83001000` alongside `83088600`.

## Bounded passive controls

[`mt7925_noise_hist_probe.py`](../research/mt7925_noise_hist_probe.py) requires
`--enable-histogram` and exclusive ownership. It verifies four fixed code windows
plus the instruction table (1174 aligned reads) before experimental writes,
refuses a pre-enabled engine, and runs a disabled quarter-second baseline,
then reset-separated quarter-second and one-second acquisition windows. Each
window ends with two stopped counter snapshots50ms apart. Both original masked
controls are restored and checked, then normal monitor firmware is reloaded.

`--channel` accepts only1,6,11 or36 at20MHz. There is no TX, RF-test mode, index1
write, host-memory DMA, nonvolatile programming, or ambient payload/identifier
export. Shared histogram history is reset and **cannot be restored**. Snapshot
timing includes USB control overhead, not a hardware-latched acquisition duration.
No sampling-frequency claim is made.

| Fresh boot / channel | Short total, both views | Long total, both views | Main distribution |
| --- | --- | --- | --- |
| 19:28:18 / 6 | 27,257 | 105,854 | bins7–8 |
| 19:28:43 / 6 repeat | 28,053 | 107,387 | bins7–8 |
| 19:28:49 / 36 | 31,855 | 121,938 | bin0 |
| 19:29:21 / 6 return | 26,705 | 105,331 | bins7–8 |

Times are UTC on2026-09-05. Channel6's ordinary view places98.9–99.2% of samples
in bins7–8; the timer view places99.6–99.8% there. Channel36 places over99.6% in
bin0. All baselines and post-reset counters are zero. Both stopped views repeat
exactly in all eight windows. Their sums agree exactly even when individual bins
differ: do not treat them as interchangeable aliases or independent observations
without further provenance work.

All live code hashes match, both masked restorations pass on each run, and
alive/reload checks pass. The first prototype used fixed channel6 and predates
the explicit channel field; the evidence wrapper records that scope. The last
run also records the ten live threshold labels. No firmware code bytes or
calibration blobs are redistributed. Experimental Andes annotations remain a
static-trace limitation; reset/enable/time/stop/channel controls provide separate
live evidence of measurement behavior.

[Sanitized evidence](../research/evidence/mt7925-noise-histogram-2026-09-05.json).
Next: distinguish environmental power from receiver configuration/gain effects,
resolve the relationship between the two views. The host-event request is now
validated below. Do not infer a −65dBm home noise floor from bin7 dominance.

## Four-view comparison: counter indices are not interchangeable with controls

`--compare-views` adds fixed reads at `83098600` and `83011000`, both derived
from the same firmware helpers. It performs **no additional writes**. Two later
runs also read low control bits during sampling: `83082004 =5` while
`83092004 =0`; both are0 after stopping.

Despite control index1 remaining disabled, the `83011000` view accumulates,
resets and stops with index0. Its total equals those of `83088600` and
`83001000` in every window, while `83098600` remains all zero:

| Fresh boot / channel | Short total, each active view | Long total, each active view |
| --- | --- | --- |
| 19:32:37 / 6 | 18,001 | 105,760 |
| 19:33:26 / 36 | 31,899 | 121,933 |
| 19:33:32 / 6 | 27,914 | 107,093 |

On channel6, `83001000` is concentrated in bins7–8 and `83011000` in bin6.
On36, both are concentrated in bin0; returning to6 restores the split. All
baselines/post-reset views are zero and all stopped snapshots repeat exactly.
All code checks, masked restorations and normal reloads pass. The first short
window has a lower total than prior trials; these are sample counts, not a
promise of wall-clock coverage or a calibrated sampling rate.

This supports distinct per-chain or processing-stage observations within one
enabled engine, **not two independently enabled RF bands**. Pinned mt76's
[MT7916-style IRPI address map](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7915/regs.h#L1203)
and [MT7996 CSD map](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7996/regs.h#L760)
use the same0x1000 base and0x10000 per-chain stride. That is corroborating
sibling-driver evidence, not proof of MT7925 physical antenna labels or the
meaning of the ordinary getter's distribution. The earlier provisional band0/
band1 wording for these helper indices is therefore replaced with raw indices.

[Four-view evidence](../research/evidence/mt7925-histogram-views-2026-09-05.json).
The new capability is synchronized, nonidentical histogram views; it does not
yet identify which antenna sees a particular interferer.

## Within-2.4GHz channel controls and sample coverage

Three additional fresh boots at1→11→6, all20MHz, retain the synchronized
three-view behavior while changing the distributions within one RF band:

| Channel | Short total per active view | Long total per active view | Long-window dominant bins, timer0 / timer1 |
| --- | --- | --- | --- |
| 1 | 27,211 | 98,177 | 6 / 5 |
| 11 | 22,947 | 64,592 | 7 / 6 |
| 6 return | 28,214 | 106,713 | 7 / 6 |

Run starts are19:35:15,19:35:21 and19:35:27 UTC. All counters reset to zero,
stopped snapshots remain unchanged, control1 stays disabled, and restorations/
normal reloads pass. This rejects a fixed2.4GHz-versus5GHz-only distribution,
but does not isolate ambient interference from device/gain/channel configuration.

Long host enable/stop intervals are1.014,1.012 and1.008 seconds, yet totals differ
substantially. **Histogram fractions describe collected samples, not necessarily
the whole dwell time.** Gating, busy periods and sample cadence need separate
measurement before combining these with occupancy or ranking channels. Do not
call channel11 quieter solely because it collected fewer samples, or recommend
a channel change from these uncalibrated distributions alone.

[Within-band evidence](../research/evidence/mt7925-histogram-channels-2026-09-05.json).

## MIB crosscheck does not justify a CCA-complement conversion

`--mib-crosscheck --acknowledge-consuming-counters` brackets each acquisition
with one source-defined UNI22 request containing offsets11/12/13/17/19/20/52:
MDRDY count, CCK/OFDM MDRDY duration, primary CCA, CCA+NAV+TX, primary ED and NAV.
The MCU is the sole MIB-counter owner; there are no direct consuming MIB reads
or MIB-enable writes. Normal histogram control restoration/reload still applies.

Three fresh passive runs on11/36/6 pass, with all active views retaining equal
totals and all stopped reads stable. Representative long windows:

| Channel | Histogram samples | Host enable/stop ms | MIB midpoint interval ms | Primary CCA raw ticks | CCK / OFDM MDRDY raw ticks |
| --- | --- | --- | --- | --- | --- |
| 11 | 100,010 | 1010.925 | 1018.482 | 320,215 | 150,989 / 4,521 |
| 36 | 122,910 | 1015.788 | 1021.301 | 28,347 | 0 / 21,532 |
| 6 | 104,824 | 1016.441 | 1020.177 | 323,442 | 154,479 / 0 |

If one tentatively assigns8µs per histogram sample and1µs per primary-CCA tick,
their sums are1120.295/1011.627/1162.034ms. The2.4GHz cases exceed the observed
intervals substantially: **the simple CCA-complement model is not supported**.
This does not identify the correct gating or independently settle either unit.
Decoded-duration fields provide another possible comparison, not a demonstrated
formula. No additive channel-occupancy decomposition is claimed.

The short channel11 baseline query took97.2ms; other query durations and both
opened/closed times remain in the evidence. MCU waits can discard delivered
frames, and query windows are not atomic with histogram start/stop. These
limitations must not be hidden by reporting just the requested sleep duration.

[Histogram/MIB evidence](../research/evidence/mt7925-histogram-mib-2026-09-05.json).
The operational result remains a normalized distribution of **collected** power
samples, with wall-time coverage and physical power scale explicitly unqualified.

## One-shot firmware event now works

The pinned normal UNI dispatcher passes its original outer object to the noise
handler. The request is **UNI0x36, SET/ACK option7, payload
`00 00 00 00 02 00 04 00`**: four reserved bytes and tag2/length4. No duration,
selector or host-buffer address is supplied. This operation resets and enables
both control indices; the firmware timer subsequently stops them.

[`mt7925_noise_event_probe.py`](../research/mt7925_noise_event_probe.py) sends
one activation after fresh normal monitor bringup and code/dispatch verification.
It requires `--activate-noise-histogram`, refuses pre-enabled controls, and polls
both endpoints with a three-second/2048-transfer bound. Only the matching status
and strictly shaped histogram event are exported; ambient frames are discarded.

The acknowledgment is CID0x36/status0. The asynchronous event is **EID0x36,
sequence0**, on endpoint0x84, with a96-byte body: four reserved bytes,
tag2/length92, then two arrays of eleven little-endian u32 counters. Header44
plus body96 gives a140-byte declared event; USB padding is excluded.
The arrays match `83001000` and `83011000` exactly, respectively.

| Fresh boot / channel | Host command-to-event ms | Samples in each event array |
| --- | --- | --- |
| 20:00:30 / 6 | 514.856 | 53,901 |
| 20:00:55 / 36 | 511.682 | 61,016 |
| 20:01:01 / 6 return | 512.217 | 50,673 |

Times are UTC on2026-09-05. All three events have equal totals between arrays;
channel6 concentrates in timer0 bin7 and timer1 bin6, while36 concentrates in
bin0. Both controls are stopped by event receipt, and all four register views
repeat exactly50ms later. Delay is consistent with timer argument500 meaning
approximately500ms, but host delivery is not an exact exposure timestamp.

Enabling control1 makes ordinary bank `83098600` accumulate, mostly in bin10,
with a different total (about63,600). The event **does not contain that bank**.
Helper/control indices must not be interchanged with raw timer-view indices or
assumed physical antenna labels.

All four volatile masks (`83082004`/`83092004` low3 and
`83088230`/`83098230` bit29) are restored with readback verification; normal
reload and alive checks pass. Shared histogram histories are irrecoverably reset.
No TX, NVM, host-memory DMA, or power/gain override. This is a working
firmware-timed measurement event, **not calibrated dBm, wall-time occupancy,
or an interference classification**.

[Sanitized one-shot evidence](../research/evidence/mt7925-noise-events-2026-09-05.json).
