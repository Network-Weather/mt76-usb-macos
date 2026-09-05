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
calls initializer `e00532bc`. **A validated host request layout has not been
established; no UNI36 request was sent.** Internal-buffer offsets must not be
copied blindly into a host TLV.

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

Firmware adds `index << 16` to these addresses. Only index0 controls are written; the
reproducer reads exactly eleven counters and never exposes an arbitrary count.
**MT7925's enable helper does not write `83088234`**, unlike MT7961's helper.
No sibling-chip option bits were added to the test.

Operation2 references ten signed bytes at GP+18220 = `02216f2c`:
−92, −89, −86, −83, −80, −75, −70, −65, −60, −55. These live labels match the
older engine, but are not a demonstrated conversion from bins to received dBm.

The timer callback uses a different getter: `e007900c` → `e005af12` stops both
control indices and reads eleven words each from **`83001000` and `83011000`**. Result
formatter `e0054118` constructs EID0x36 with tag2/length92 and two44-byte arrays.
This is an event-producing lead, not merely firmware log output. No live event
or two-control activation is claimed. The initial test independently reads only
the **index0** view at `83001000` alongside `83088600`.

## Bounded passive controls

[`mt7925_noise_hist_probe.py`](../research/mt7925_noise_hist_probe.py) requires
`--enable-histogram` and exclusive ownership. It verifies four fixed code windows
plus the instruction table (1174 aligned reads) before experimental writes,
refuses a pre-enabled engine, and runs a disabled quarter-second baseline,
then reset-separated quarter-second and one-second acquisition windows. Each
window ends with two stopped counter snapshots50ms apart. Both original masked
controls are restored and checked, then normal monitor firmware is reloaded.

`--channel` accepts only6 or36 at20MHz. There is no TX, RF-test mode, index1
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
resolve the relationship between the two views, and establish a safe host-event
request if useful. Do not infer a −65dBm home noise floor from bin7 dominance.

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
