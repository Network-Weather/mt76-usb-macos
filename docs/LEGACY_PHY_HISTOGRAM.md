# MT7961: a working legacy PHY histogram engine

**A second histogram path accumulates samples in normal monitor mode.** Unlike
the earlier EXT0xa3 path at `0x830af...`, this one uses eleven words starting at
`0x83088600`. Two fresh-boot passive tests establish enable, time-dependent
accumulation, reset-to-zero and stopped repeat-read stability. All observed
samples occupy bin0; responsiveness across power bins and calibrated noise
estimates are **not established**. No non-Wi-Fi classification is claimed.

Pinned MT7961 RAM SHA-256:
`b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`.

## Actual firmware path, not a sibling-chip address guess

Wrapper `0x00942d2a` calls `0x00936f16`. The latter implements:

| Operation | Band0 effect |
|---|---|
| 0: reset | `0x83088230` bit29 clear → set → clear, preserving all other bits |
| 1: enable | OR `0x30000` into `0x83088234`; replace `0x83082004` bits2:0 with5 |
| 2: stop/read | Clear `0x83082004` bits2:0; copy contiguous32-bit bins from `0x83088600`; copy ten threshold bytes |

All addresses add `band << 16` in firmware; only band0 is tested or exposed by
the probe. Operation2 has only a lower bound on the requested count, so it is
unsafe to infer an arbitrary dump API. Callers `0x0092277c..0x0092278c`,
`0x0096175a..0x00961764`, and `0x009627d8..0x009627ea` explicitly use **11**.
The probe likewise reads only eleven words: `0x83088600..0x83088628`.

The threshold table referenced at `0x00936f6c` is runtime GP+`0x1a230`,
or `0x0201d230`. Its ten signed-byte constants are
**−92, −89, −86, −83, −80, −75, −70, −65, −60, −55**. The file-layout r1
offset is `0x71e4`, accounting for the established +`0x44c` runtime relocation.
No firmware bytes are redistributed. These are labels, not proof of dBm units,
inequality boundaries, per-chain provenance or an accurate noise-floor estimate.

The pinned mt76 `mt7915/mac.c:mt7915_mac_enable_nf` independently uses the same
low-bit enable value5, and `mt7915_phy_get_nf` uses corresponding power weights.
Its counter addresses and reset details differ. We use the **actual MT7961
firmware trace**, not that driver's address map or weighted-average formula.
Local mt76 pin: `c5a3bd91aa735b669618610d5f0ebfa5786845a6`.

`0x00961728` is a timer callback that stops/reads eleven bins and can re-enable
sampling. Another caller around `0x009627b0` configures the timer and performs
reset/enable. A public host command route to this particular engine has not yet
been established; EXT0xa3 instead reaches the separately documented zero path.

## Bounded passive validation

Run `research/legacy_noise_hist_probe.py --enable-histogram`. It requires exclusive
ownership, refuses an already-enabled engine, uses normal channel36/20MHz monitor
mode, and sends **no frames** or RF-test commands. It preserves bits outside the
three traced masks, verifies enable/readback, restores original masked state on
exit, and reloads normal firmware. Histogram history is reset and cannot be
restored; this is an experimental shared-statistics operation.

Each run includes a disabled quarter-second baseline, then reset-separated
quarter-second and one-second enabled windows (512-transfer ceiling each).
Before each enabled window all eleven bins read zero. The table gives measured
host receive-loop durations, excluding the small USB enable/read/stop overhead.

| Fresh boot | Short window / bin0 | Long window / bin0 |
|---|---|---|
| 2026-09-05 11:14:59 UTC | 0.259s / 32,805 | 1.023s / 128,195 |
| 2026-09-05 11:15:21 UTC | 0.262s / 33,047 | 1.014s / 127,147 |

Disabled baselines remain zero. Other ten bins remain zero. Stopped reads repeat
exactly, and all three masked restorations plus reload/alive checks pass in both
runs. Short windows have **zero host transfers despite tens of thousands of
samples**, so this is not simply a delivered-frame counter. The observed scale
is roughly125,000 samples/second, consistent with an8µs cadence; that cadence
is an inference, not a traced clock definition or calibrated sampling guarantee.

[Sanitized evidence](../research/evidence/legacy-phy-histogram-2026-09-05.json).
Only bin totals, fixed control masks and aggregate packet counts are retained.
No identities, raw frames, IQ values, hashes of captures or firmware replies.

Next discriminations: independently confirmed stimulus versus quiet baseline,
bin response across channels, and the firmware's own consumer/threshold
interpretation. Do not report a constant −92dBm noise floor from bin0-only data.
See also [normal PHY counters](PHY_RX_COUNTERS.md) and
[the earlier IPI investigation](FIRMWARE_FIELD_MAPS.md).

## Controlled reception and busy-time follow-up

`--stimulus --acknowledge-experimental-transmit` adds at most12 synthetic no-ACK
HT/MCS8/NSS2 frames from the MT7925 on channel36 only, four per receive window.
Exact private per-run frame matching, good FCS and PHY metadata establish receipt;
no identities or frame bytes are exported. Both radios are reloaded on exit.
At11:17:25 UTC all three windows received4/4 exact frames, including both enabled
windows. Those histogram totals were33,613 and126,697, again entirely in bin0.
Thus the engine and packet capture coexist, but valid Wi-Fi receipt alone did
not produce a spread across power bins. This sparse, weak-signal control does
not establish whether Wi-Fi samples are included or excluded from the histogram.

Passive `--channel 1` received27/88 normal transfers in the short/long windows,
with totals31,098/115,048; channel149 received0/0 with32,915/125,643. All remain
bin0-only and restore/reload successfully. Only channels1/36/149 were tested;
the CLI also permits passive6/11, not arbitrary channels or transmit parameters.

The lower sample rate on busy channel1 motivated `--cca-crosscheck`. This opts
into the established EXT0x5a primary CCA counter, offset11, before enable and
after stop. MCU waits can consume normal frames. The tool records both the
histogram enable/stop interval bounds and CCA call bounds; the CCA window
**encloses**, rather than exactly matches, the histogram window. At most about
5.2ms of extra time separates their boundaries in these runs.

| Channel / window | Histogram enable interval | Samples × tentative8µs | CCA busy |
|---|---|---|---|
| 36 / short | 268.164–271.171ms | 269.816ms | 0ms |
| 36 / long | 1007.174–1010.112ms | 1008.616ms | 0.093ms |
| 1 / short | 271.788–275.017ms | 229.984ms | 37.754ms |
| 1 / long | 1006.398–1009.095ms | 857.840ms | 126.157ms |

Quiet-channel counts fit an8µs cadence within the enable/stop bounds. CCA
explains much, **not all**, of the busy-channel sample deficit: even adding all
126.157ms from the enclosing CCA window leaves at least22.401ms unexplained in
the long window. Additional receiver gating/holdoff is a hypothesis, not a new
identified counter. Do not substitute `elapsed − 8µs × bins` for CCA, or label
that residual non-Wi-Fi time. No broad clock, RF power, gain or threshold writes
were used to force a different result.

[Sanitized follow-up evidence](../research/evidence/legacy-histogram-controls-2026-09-05.json).

## Firmware's own histogram interpretation

The consumer at `0x00922922..0x0092295c` reads eleven bins and the ten thresholds,
gets another PHY field, selects a threshold index, then computes a tail fraction.
`0x00922836` compares its signed input with the signed threshold bytes, returning
the first index whose threshold is at least the input, clamped at9 above the
last threshold. `0x0092285c` sums all eleven bins, separately sums bins whose
index is at least the chosen index, and returns integer `100 × tail / total`
(zero when total is zero). This describes the short-window non-overflowing case;
the actual arithmetic is32-bit and is not an overflow-safe host API.

One input source is `0x00942a96 → 0x00936e14`: its read form extracts three
bytes from `0x83088554` into16-bit fields. The histogram caller takes the first
field, subtracts3, then narrows it to a signed byte before threshold selection.
Another path uses `0x00936eee` to read bytes31:24 and23:16 of `0x8308838c`,
then sign-extends the first for threshold selection. These are **threshold/
decision inputs**, not established instantaneous noise measurements. Neither
register was written by the host. This consumer supports interpreting the bin
array as a distribution used for threshold-relative occupancy, but does not
calibrate its physical power scale or establish a noise-floor estimate.
