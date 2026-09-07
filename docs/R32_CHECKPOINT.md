# R32 checkpoint and next decisions

Checkpoint: 2026-09-06 Pacific / 2026-09-07 UTC, at the user's request.
Work is on `feat/measurement-api` and [draft PR #32](https://github.com/Network-Weather/mt76-usb-macos/pull/32).
Main remains `7eb35d1`; published version remains0.3.0. Nothing is merged or
released for R32. Both supervised radio processes have exited and released USB.

## What we have now

The selected measurement implementation is substantially complete in both
Python and C. Applications can use installed modules/headers rather than import
research scripts. The remaining work is qualification and explicit inclusion
decisions, not another wholesale API or driver rewrite.

| Surface | Delivered | What the evidence does not establish |
| --- | --- | --- |
| Continuous acquisition | One USB worker, bounded queues, serialized commands, epochs/generations, visible failures and orderly stop | No automatic recovery, hot-unplug or sleep/wake qualification; Python two-hour gate remains open |
| Named counters / thermal | Old4/new10 raw counters, width/ownership metadata, reported temperature and new-chip raw ADC | No justified busy-percent conversion or ADC/power calibration |
| TX-status timing | Matching strict decoders, raw clocks and format-specific scale availability;12/12 live records agree | No new TX profiles, synchronized clocks or ranging |
| Old-chip Group5 | Matching bounded raw-field decoders and saved-mask guards | Enabled-phase near-silence means dependable live streaming is not qualified |
| MT7925 beacon CSI | Narrow channel36/20MHz parser and session-bound lifetime; coexistence, ordering, overflow and cancellation tests | No wider/stale-CCK profile, receiver-pair completeness, calibrated CSI or multi-hour CSI claim |
| Raw histograms | Matching old/new records and guarded one-shot acquisition;12 short normal/cancellation runs | No calibrated dBm, physical antenna labels or full-dwell coverage; old receiver health remains unresolved |
| Reuse and handoff | Python/native examples, shared malformed/fault fixtures, packaging and [Linux pointers](LINUX_MEASUREMENT_HANDOFF.md) | No upstream implementation or outreach; no networking-driver or iPad implementation |

The [scope matrix](MEASUREMENT_RELEASE_SCOPE.md) is the inclusion authority;
[C parity](C_PARITY.md) is per capability, not per research-script count.
Full local dual-Python/native/sanitizer/package checks and the four-job CI matrix
pass at the recorded checkpoints; the local suite has2,027 tests. CI runs2,022
plus5 optional tshark skips per job. See [offline evidence](../research/evidence/r32-offline-ci-matrix-2026-09-06.json).

## What the long run actually showed

[Summary and limitations](../research/evidence/r32-a9000-soak-checkpoint-2026-09-07.json)
and [all retained redacted records](../research/evidence/r32-a9000-soak-retained-2026-09-07.json)
are committed. Both runs passively alternated channels1/11 every30s while querying
ten named counters and thermal actions every10s.

- Native A9000:7,200.058s,857,759 decoded/delivered frames,3,099 matched/completed
  commands,715 measurement rounds and239 retunes. Zero reported queue drops,
  USB errors, malformed/unmatched replies or legacy MCU frame discards. One
  timestamp-wrap candidate; zero backsteps/ambiguous gaps. Orderly exit0.
- Python A9000:2,372.772s (39.5min),288,445 decoded/delivered frames,1,018 matched/
  completed commands,235 rounds and78 retunes. No reported drops/errors; orderly
  SIGTERM exit130 at the user's checkpoint request. **Not a two-hour pass.**
- Observed heartbeat RSS remained about12.6MiB native /31.2MiB Python. Three
  host telemetry-collection gaps omit intermediate records; final process
  summaries retain cumulative counts. This is not a lossless telemetry series
  or proof that memory can never grow. Native/Python recorded333/123 frames off
  the currently requested channel; retune/buffered-frame provenance matters.
- Native used `2074599`; Python core was unchanged from that checkpoint, with
  later probe-only timestamp diagnostics identified by its emitted SHA. The
  later native reset-error fix still needs current-build A9000 bring-up smoke.

The old MT7921 remains RF-silent, including clean-main and feature-branch fresh
controls. Earlier native histogram channel6 still received131 frames; a later
cancellation baseline was already silent before activation. Firmware reload and
register aliveness do not prove RF recovery. A logical USB port-power cycle did
not establish a real supply cut. Exact cause/onset remains unknown; neither a
feature-only software regression nor permanent hardware damage is established.

## Roadmap from here, in order

### 1. Restore the reference fixture and close bounded acceptance

- Physically remove/reapply power to the old dongle, or substitute a known-good
  old-chip reference. First run unchanged-main passive controls, then current
  Python/C controls. Preserve failures; stop repeated identical software-reset
  attempts. This requires a physical fixture change, not more blind commands.
- On A9000, run fresh current-build Python/C passive smoke and validate private
  capture files independently with capinfos/tshark. Keep ambient captures out
  of Git. Complete the Python two-hour run in a separately scheduled window;
  this checkpoint's partial run must not be relabeled or stitched into one.
- After old-chip RF recovery, perform its two-hour Python/C runs and the exact
  included experimental-profile checks. If recovery is unavailable, make an
  explicit release-scope decision; do not silently convert the failed gate to a pass.

Exit: current RF controls and the selected session matrix are evidenced, with
source/firmware hashes, final counters and cleanup. No new monitoring framework.

### 2. Prepare the point release, then request a decision

Review draft PR32 against the [ordered release plan](NEXT_RELEASE.md); rerun
offline/package gates if implementation changes. Decide each experimental
surface separately: keep Group5 reliability unqualified, and retain narrow
CSI/histogram profiles only where their gates hold. Refresh support/Unreleased
notes from the final evidence. Select a version and seek explicit merge/release
direction; neither operation is authorized by this checkpoint.

### 3. Resume research with discriminating experiments

Prioritize measurements that could change a Network Weather decision:

1. **Counter interpretation:** with a healthy independent reference and bounded
   known traffic, resolve duration tick scales and read/reset intervals before
   deriving occupancy. Until then, expose raw values and unknown conversion.
2. **Histogram meaning:** separate receiver-health failure from the old bin0-only
   result; vary a known stimulus and verify coverage/view behavior. Promote no
   noise-floor or non-Wi-Fi interference classifier from raw thresholds alone.
3. **CSI repeatability:** use the discovered START → add-transmitter → receiver-
   restriction ordering, repeated short captures and explicit queue/epoch loss
   accounting. Characterize consistency before adding pairing or analysis APIs.
4. **Transmit expansion:** only after before/after independent good-FCS controls
   recover, qualify one small named profile. No rate/width cross-product sweep
   and no success inferred merely from ACK/TXS.

For each experiment, decide the discriminating control and stop condition first,
keep positive and negative evidence, and promote only a bounded matching Python/C
contract. Analysis and topology inference stay above acquisition. Retain the
prepared Linux documentation gift for later review; sending it is a separate choice.

Proper networking-driver work remains out of scope. The iPad walk-around spike
stays deferred. ICAP/IQ retrieval, wide-packet CSI, calibrated ranging/noise/power
and the known hazardous diagnostic paths are not point-release prerequisites.

## Resume without reconstructing this session

Start from this checkpoint, the scope matrix and `TODO.md`. No radio process from
the supervised soak remains active. Native two-hour acceptance is recorded;
Python was intentionally stopped, not crashed. Do not restart it automatically
just because a previous goal requested uninterrupted exploration. Choose the
next bounded work package and a suitable acquisition window with the user.
