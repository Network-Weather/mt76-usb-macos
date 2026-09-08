# R32 selected release scope and remaining gates

Decision snapshot2026-09-06, updated2026-09-08, `feat/measurement-api`; published version remains0.3.0.
This is the implementation/inclusion matrix, not permission to merge, tag or
publish. After physical recovery, current Python/C three-band baselines and
independent capture-file checks pass on both radios. ALFA5/6GHz reception then
degrades during the histogram sequence despite restore/reload: the
[bounded merge check](R32_MERGE_CHECK.md) holds the complete PR pending isolation
or an explicit scope split. The point release is also **not release-ready**.

| Capability | Selected Python/C implementation | Release decision / evidence limit |
| --- | --- | --- |
| Existing passive capture / RXD timestamps | Existing chip-specific decoders and USB capture paths, raw timestamp presence | Preserve interfaces and historical evidence; old-unit short Python2.4GHz RX recovered after physical cycle on2026-09-08. Broader requalification and cause remain open. No ranging/TSF reconstruction |
| Continuous acquisition | One worker, bounded drop-newest queues, short MCU callbacks, explicit epochs/generations and fail-closed errors | Candidate floor; native A9000 two-hour scoped pass. Python intentionally stopped at39.5min for the checkpoint, not a two-hour pass. Old-unit run stopped at164.5s with0frames, not passed. Physical unplug/sleep-wake/automatic recovery remain unqualified |
| Named MCU counters | `read_counters` / `mt_counter_read`, old4/new10 named fields | Include raw profiles; one owner, non-atomic query intervals, distinct wire/hardware/accumulator widths. Unknown duration conversions retained; idle-slot saturation can lose samples |
| Query-only thermal | `read_thermal` / `mt_thermal_read`, reported temperature both chips, raw ADC new only | Include with request intervals and explicit ADC availability; no thermal-control or calibration writes |
| TX-status metadata | Strict `parse_tx_status` / `mt_tx_status_parse`, old/new layouts, qualified new-format0 clock scales | Include decoding only. No new transmit profiles; current independent RF controls are insufficient for broader claims |
| Old-chip Group5 raw signal | Complete-group decoder plus saved-bit/readback/restore guards | Keep opt-in experimental code, **do not advertise dependable live acquisition**. Repeated enabled-phase near-silence and upstream hardware warning remain unresolved; no dBm/SNR/antenna labels |
| MT7925 beacon CSI | Strict version22/64-IQ profile plus session-bound start/accept/stop helpers | Include candidate as narrow experimental channel36/20MHz selected-source capture. Short normal/overflow/cancellation gates pass; no broad bandwidth, CCK freshness, pairing/ranging or multi-hour CSI claim |
| Raw histograms | Separate old ordinary/new timer records; matching guarded begin/finish/restore | Include candidate experimental20MHz channels1/6/11/36. Twelve short public-helper runs pass; modern pending callback needs full reload. No calibrated power, full-dwell coverage or physical view labels |
| Further transmit profiles | No extension in this sprint | Defer until independent RF controls are healthy; an MCU ACK or TXS record is not proof of over-air delivery |

The independent contracts are [measurements](MEASUREMENTS.md),
[sessions](CONTINUOUS_ACQUISITION.md), [CSI](CSI_API.md) and
[histograms](HISTOGRAM_API.md). [C parity](C_PARITY.md) is per capability, not per
research-script count. [Testing](TESTING.md) retains positive and negative runs,
including the initial thermal/MIB failure and the recent old-radio RF silence.

## Acceptance still required

The [bounded acceptance evidence](../research/evidence/r32-bounded-merge-check-2026-09-08.json)
closes initial current-build Python/C three-band reception and independent capture
validation on both radios. It does **not** close sustained ALFA RF recovery:
post-experiment high-band reception degrades while the A9000 control stays healthy.
Independent TX and two-hour gates also remain open.

- Complete the selected two-hour session runs and review memory, queue loss,
  command failures, timestamp wrap/backsteps and channel provenance. Do not count
  interrupted attempts or RF-silent dwells as successful radio qualification.
  The [checkpoint](R32_CHECKPOINT.md) records native A9000 acceptance and Python's
  intentional partial run, including three intermediate telemetry-collection gaps.
  No acquisition remains running; schedule remaining runs separately.
- Recover/requalify the old reference receiver, or explicitly narrow the release
  claim with the unresolved limitation. Its successful register/temperature reads
  do not close that gate. No unattended physical recovery has been performed.
  A clean-main/feature [passive comparison](../research/evidence/r32-old-radio-main-control-2026-09-06.json)
  reproduces zero USB transfers on both revisions; this weakens an active
  feature-only code-path explanation but does not rule out retained device state.
- Small [Python/native composition examples](MEASUREMENT_EXAMPLES.md) pass
  offline checks and outside-checkout packaging/build verification. Current
  passive smoke and independent capture-file validation now pass initially;
  the separate failing post-experiment RF controls are preserved above.
- Offline/docs/packaging checks now pass locally on Python 3.10/3.14 and across
  the four-job CI matrix at `b4b1315`; see [the evidence](../research/evidence/r32-offline-ci-matrix-2026-09-06.json).
  Recheck after implementation changes. Do not run the clean/rebuild script over a native executable
  currently participating in a soak; use a separate build directory or wait.
  A subsequent native reset-timeout error-return fix passes synthetic controls
  and sanitizers. Current-build bring-up and initial RF controls now pass on
  both chips; subsequent old-chip RF degradation remains a separate blocker.
  The completed native soak's recorded base is `2074599`, not later source HEAD;
  the partial Python probe's actual diagnostics revision is separately identified.
- Refresh the final Unreleased/support/privacy notes, then select a version and
  prepare the publication checklist separately. No merge/release is authorized
  by this matrix, and neither has been performed for R32.

## Explicit non-goals and parked work

Proper macOS networking-driver/baseline connectivity is out of scope. The iPad
test spike stays in the roadmap, not this sprint. Linux work is a documentation
gift, not upstream implementation or unsolicited outreach. Calibrated
noise/power/CFO/SNR, wide-packet CSI, ICAP/IQ extraction, ranging and a finished
mesh-topology algorithm are not release prerequisites.

Known diagnostic hazards remain excluded: UNI23 tag3's command-object leak,
unsupported/not-ready link-quality caches, unqualified consuming MMIO, and UNI40's
problematic table-write path. Do not expose their zeros or ACKs as measurements.
