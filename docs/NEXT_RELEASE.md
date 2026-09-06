# Next measurement release: research to Python and C

Planning baseline: `main` at `7eb35d1`, 2026-09-06, after PR #31 merged.
This is the selected R32 delivery plan, not a release announcement or a claim
that the APIs below already exist. The published version remains `0.3.0`;
select the next version under the project's versioning policy at release prep.

## Outcome and scope

Let Network Weather acquire trustworthy channel measurements from either dongle
without importing research CLIs or rebuilding their firmware sequences. Python
and C should expose the same selected measurement contracts, with explicit
availability, units, provenance and cleanup. They need not expose every experiment.

Recommended release floor: the existing continuous-session work, named counter
samples, thermal readout, normal-mode signal fields and richer TX-status decoding.
Target MT7925 beacon CSI and raw histograms as opt-in experimental additions,
in that order. Each has a separate acceptance gate: an unfinished addition stays
in research and does not hold up the qualified floor. Expanded transmit profiles
come after those passive measurements and require healthy independent RF controls.

No proper networking driver, iPad implementation, calibrated ranging/noise/power,
mesh-topology algorithm, extcap, or upstream Linux implementation is required.
Do not turn this into a wholesale driver rewrite or a port of every research script.

## Where we actually are

- **Released:** 0.3.0. **Merged but unreleased:** R30 native acquisition parity,
  later capture/analysis changes, and PR #31's research, fixtures and evidence.
  [CHANGELOG](../CHANGELOG.md) describes the complete unreleased baseline.
- **Production API gap:** PR #31 did not expand the production Python/C drivers.
  The [C parity contract](C_PARITY.md) covers the earlier research baseline, not
  the newly discovered CSI, histograms, thermal command or expanded TX profiles.
  Some Python measurements also exist only as script helpers; this is extraction
  into both libraries, not just C catching up with an already finished Python API.
- **Existing integration work:** `feat/continuous-acquisition` at `0c2fffa` has
  Python `AcquisitionSession`, native `mt_session_*`, bounded frame/event queues,
  command serialization and lifecycle tests. It is pushed, but not merged.
  Its evidence includes short Python/C live runs, five-minute C stress runs,
  cancellation and reinitialization; multi-hour soak and hot-unplug remain open.
  Review/reconcile that branch with current main instead of reimplementing it.
- **Research limitation:** later experiments encountered weak or absent independent
  TX receipts in some directions/bands. Earlier successful configurations are
  useful evidence, not a guarantee that the current fixture can qualify new ones.

## Research and promotion decisions

These are bounded questions, not an instruction to keep probing until every
surface works. Record a negative or unavailable result and narrow the API envelope
when a gate fails. Links below contain the existing source and hardware evidence.
The named-counter API uses the qualified MCU paths; conflicting direct read-clear
register probes remain research-only. Timing layout details are also recorded in
[TX-status timing](TX_STATUS_TIMING.md).

| Surface / priority | Further research or qualification | Python and C landing contract |
| --- | --- | --- |
| Named MIB counters / floor | Confirm reset/read-clear ownership and effective widths for each selected field. Distinguish reply width from counter width. Resolve duration tick scaling before publishing derived percentages: some source descriptions specify 1.024 us, while idle offset7 counts 9-us slots and saturates. Recheck short/long quiet and busy windows with one owner. | Shared counter identifiers and per-chip descriptors: raw value, unit/scale confidence, width, scope, saturation and sampling interval. Reuse C `mt_mib_*`; extract Python query/parse helpers from scripts. Initially prefer primary CCA, CCA+NAV+TX, RX duration, FCS/MPDU, idle and NAV where qualified. No addition of overlapping counters into a synthetic total. [MIB evidence](MT7925_MIB.md). |
| Thermal / floor | Repeat MT7925 UNI35 tag0 actions0/1 through the library/session path, with matching reply and cleanup tests. Check the existing older-chip getter independently; chip parity does not mean identical commands or sensor identity. | Reported temperature and separately labeled raw ADC where supported; no thermal-control API or ADC calibration. Extract `research/mt7925_thermal_probe.py` wire helpers and add native counterparts. |
| Normal RX signal and TX status / floor | Preserve PHY/group validity for old-chip Group5 FAGC fields; verify absent/truncated groups never manufacture zero measurements. Recheck timestamp/front-time/delay layout and scales by TX-status format; raw decoding does not require qualifying new TX formats. | Extend bounded Python/C decoders with raw in-band/wideband receiver-index fields and supported timing fields, presence flags and clock domains. Keep Group5 opt-in with restoration. No calibrated SNR, antenna mapping, pure contention delay or ranging claim. [Signal](INBAND_WIDEBAND_SIGNAL.md), [timing](CROSS_RADIO_CLOCK.md). |
| MT7925 beacon CSI / first experimental target | Qualify normal capture + filtered CSI + routine MCU queries together. Test START resetting filters, post-START receiver restriction, pending reports after STOP, overflow, cancellation and fresh restart. Limit first envelope to the evidenced 5-GHz 20-MHz beacon format. Reject known stale CCK IQ as usable samples. Wider receive configuration is not proof of wider packet CSI. | Strict versioned event parser plus explicit start/read/stop lifecycle; signed I/Q arrays, reported tone count, RX/TX indices, raw metadata and MCU-clock timestamp. Bound event/array sizes and pairing lifetime. Filter or discard pre-configuration events in the host too. MT7921 reports unsupported, not empty successful CSI. [CSI evidence](STATION_CSI.md). |
| Raw PHY histograms / second experimental target | Reproduce enable/reset/one-shot/stop on both chips; measure sample coverage, quiet/stimulus response and interaction with normal RX/MIB. MT7925 firmware emits two 11-bin arrays after about 512 ms; neither the two indices nor thresholds are calibrated antenna/noise labels. Confirm restoration and any ownership conflicts before concurrent use. | One-shot raw histogram result with bin counts, raw threshold/configuration values where known, acquisition interval and coverage/availability metadata. Use chip-specific backends; no mean noise-floor dBm or interference classification. [Histogram findings](OVERNIGHT_EXPLORATION.md). |
| Width-aware ED / follow-up, not floor | Controlled narrow-channel stimulus and primary-channel rotation must map ED indices to RF subchannels. Prove inactive-width behavior and distinguish saturation from genuine activity. Stop if independent stimulus controls fail. | Until mapped, only explicitly raw indexed fields with applicability metadata; no per-channel interference heatmap. Never query known-invalid MIB offset94. [Counter map and ownership](MT7925_MIB.md). |
| Expanded TX profiles / optional after passive targets | Establish received control packets before and after each candidate on the current fixture. Requalify a small named profile first, such as evidenced MT7925 HT MCS8 / channel6 / 20 MHz. Record good-FCS independent receipts, rate/width and recovery, not just successful command/TXS. No inferred cross-product of rates, widths and channels. | Shared finite profile definitions and pure descriptor fixtures, then bounded native/Python transmit primitives. Preserve frame/count/pacing/power-code restrictions, explicit opt-in and cleanup; validate before any table write. Keep the problematic UNI40 write path out. Broader TX remains gated by [roadmap transmit prerequisites](../ROADMAP.md#gated-optional-track-transmit). [PHY evidence](PHY_TRANSMIT.md). |

Power-table reports, PHY-error metadata, ICS and RF-test CFO/SNR are useful later
adapters, not prerequisites for this release. A future power report is configuration
data, not measured output power; error frames need metadata-only privacy defaults;
RF-test/ICS needs a separately qualified exclusive-mode lifecycle. Do not silently
enable those modes to populate an otherwise unavailable normal-mode measurement.

## API shape: one contract, two implementations

Names below are proposals. Keep existing device/open/capture calls compatible;
there is no stable C binary ABI promise, so document any struct changes and rebuild
requirements. Do not introduce a general plugin framework to implement this slice.

1. **Transport and session:** reuse `mt76_session.AcquisitionSession` and
   `mt_session_*`. One owner drains USB and routes matched replies, normal frames
   and unsolicited measurement events. No measurement helper may become a second
   bulk-IN reader. Slow consumers use bounded queues with visible drops, never
   back-pressure that prevents command completion. A transport-failed or ambiguous command
   invalidates the session; recovery establishes a new epoch, not continuity.
2. **Wire and measurement primitives:** extract small pure request builders and
   strict reply/event decoders into installed Python modules (for example
   `mt76_measurements`) and focused C headers/sources. Add callable counter/thermal
   operations and explicit experimental stream/one-shot controls. Existing research
   CLIs should call these helpers once promoted, so their wire layouts cannot drift.
   Do not expose arbitrary MCU/register writes as the new measurement API.
3. **Analysis stays above acquisition:** Python/Network Weather performs CSI
   analysis, clock fitting, survey aggregation, interference hypotheses and topology
   inference. C supplies the same validated raw observations, not a duplicate
   analysis toolkit. Add one small redacted Python example and a native equivalent
   showing frame capture plus interval measurements; no new analysis framework.

Use a small common measurement envelope; fields that do not apply stay absent:

- Chip/device identity, pinned firmware/profile identity, session epoch and schema
  version. Capabilities are qualified chip/firmware/mode/configuration combinations,
  not a promise inferred from a command ACK or a vendor feature bit.
- Requested channel geometry/generation and observed channel where the record
  supplies it. Preserve the session's retune-transition flag; acknowledgment alone
  does not label buffered data as captured on the new channel.
- Host monotonic start/end interval and device timestamp with its named clock
  domain when present. Batched MIB queries are not simultaneous hardware latches.
  CSI's MCU timer is not RX TSF or time of arrival.
- Raw values plus separately justified units/scale, field applicability, known
  invalid/stale markers and evidence profile. Distinguish `unsupported`,
  `not_qualified`, `unavailable`, `invalid`, and transport errors from a valid zero.
  Unknown freshness must remain unknown; unchanged values alone do not prove stale.
- Counter read/reset semantics, saturation and effective width where known;
  delta validity only within compatible epochs/configurations. Reset, retune or
  a competing read-clear owner can invalidate an interval.
- Queue/drop counters, incomplete receiver-pair status and cleanup result where
  relevant. Distinguish no event received in a window from a measured zero.

Python can use typed records/enums and C structs/enums with explicit presence
flags and caller-owned buffers. Keep integer widths, scaling and failure semantics
aligned; queue capacities and calling conventions need not be identical.
Raw CSI and frames remain opt-in sensitive data; example/fixture exports are
synthetic or redacted, with no ambient identifiers or coefficient arrays by default.

## Ordered work packages and exit gates

### 1. Reconcile the baseline and freeze the small contract

- [x] Review the continuous-acquisition branch against current main; reconcile docs,
  packaging and tests without losing either branch's evidence. Preserve one-owner,
  fail-closed sequence matching and stop/callback lifetime rules already implemented.
  Integrated on `feat/measurement-api`; 1,687 tests and full offline checks pass.
  Main merge and new hardware qualification remain separate gates.
- [ ] Define the selected measurement records and capability/profile matrix above;
  distinguish existing primitives, newly extracted APIs and experimental additions.
- [ ] Update `C_PARITY.md`: parity is per selected capability, not per script count.
  Correct historical "atomic" MIB language and separate wire/effective counter width.

Exit: reviewed session integration and agreed shared fixtures/contracts. No hardware
discovery or large type-system refactor is needed to complete this package.

### 2. Deliver the release floor in vertical slices

- [x] Named MIB sample/descriptor helpers in Python and C; resolve conversion and
  ownership gates or leave affected derived values unavailable. First slice:
  [raw named contract](MEASUREMENTS.md), with unknown conversions/accumulator
  widths retained. Live queries pass in both languages; old-chip weak RX is an
  explicit remaining RF qualification limit, not a release pass.
- [x] Query-only thermal Python/C parity, shared malformed/failure fixtures and
  short mixed-session qualification on both chips. Retain the initial failed
  run and corrected counter-parser regression in [the contract](MEASUREMENTS.md).
- [x] Implement Group5 raw-signal decoder/guard parity with shared bounds/failure
  fixtures. Live reliability gate remains open: [four cycles](MEASUREMENTS.md#experimental-raw-group5-fields)
  reproduce enabled-phase near-silence in both languages; retain experimental scope.
- [x] TX-status timing parity: strict installed parser and research reuse, shared
  malformed/format/capacity fixtures,12/12 identical live status decodes. Missing
  independent OFDM receipts remain a TX-profile gate, not parser failure.
- [ ] Each slice includes synthetic golden bytes shared across implementations,
  malformed/unknown/truncated-input and failure tests, CLI reuse, and dated live
  qualification on the applicable dongle. Compare semantics in separate runs;
  do not have Python and C steal the same hardware counters concurrently.
- [ ] A small Python/native capture-plus-measurement example proves the primitives
  compose and shows unavailable values honestly, without making topology claims.

Exit: an application can consume the floor without importing `research/` or
`scripts/`, and each advertised operation has Python and native C evidence.

### 3. Promote bounded experimental measurements

- [x] CSI pure parser/control-wire parity and short Python/C coexistence, negative
  ordering controls and explicit event overflow. [CSI contract](CSI_API.md):
  transmitter filter must precede the final receiver-count command.
- [x] Extract matching public session-bound CSI lifecycle and stage-failure/epoch
  tests; public-helper normal/overflow/cancellation runs pass in both languages.
  Longer-session acceptance remains separate; see [lifetime contract](CSI_API.md).
- [ ] Histograms next: one-shot ownership/cleanup and coverage, then Python/C parity.
  [Pure wire/record parity](HISTOGRAM_API.md) and repeated Python session windows
  are implemented; native live and reusable lifetime/fault tests remain open.
- [ ] Decide each feature independently: included with a narrow explicit experimental
  profile, or left research-only with the failing gate recorded. Do not ship a
  Python-only public feature while calling the release's selected scope C parity.
- [ ] Only then consider a small TX profile extension, provided independent RF
  controls and the existing broader-TX prerequisites pass. No open-ended rate sweep.

Exit: an explicit included/deferred matrix, not every firmware mystery resolved.

### 4. Qualify and prepare, without automatically publishing

- [ ] Full offline suite, formatting/lint/docs checks, native build/tests and
  sanitizers; repeat session race checks after changes to dispatch or lifetime.
- [ ] Build/install sdist and wheel outside the checkout; verify new Python modules,
  C sources/headers and shared fixtures are included and examples import correctly.
- [ ] Current passive smoke and independent capture-file validation for both
  reference dongles; short Python/C measurement and cancellation/reload runs for
  every included profile, with firmware hashes and not-tested cases recorded.
- [ ] One bounded two-hour passive session run per implementation/chip, with queue,
  command-timeout and memory diagnostics, using the existing probes (the two
  radios can run concurrently with independent owners). This is a release gate for advertising
  the newly merged continuous API, not a prerequisite to further chip research or
  a reason to build more monitoring infrastructure. Failure narrows/defer sessions
  and stream features; it does not erase the existing bounded capture capability.
- [ ] Offline disconnect/timeout coverage is mandatory; physical hot-unplug and
  sleep/wake remain explicitly unqualified unless exercised. No warm-adoption or
  automatic recovery claim. Restoration failure must be visible and require fresh
  bring-up, never silently return the device to a reusable state.
- [ ] Refresh `QUALITY.md`, `TESTING.md`, support/privacy tables, `C_PARITY.md` and
  Unreleased notes. Select version and prepare the publication checklist separately;
  tagging/publishing still requires direction.

Exit: release-ready evidence for the exact included subset, with no unexplained
regression in passive capture and no supported feature dependent on a known firmware
leak or stale sensor value. A failed existing TX smoke must be disclosed and its
claim narrowed or investigated, not hidden by successful MCU acknowledgments.

## Parked research and useful Linux handoff

Do not block this release on ICAP/IQ retrieval, ToA/ranging, normal-mode calibrated
CFO/SNR, DCM/upper106-tone TX, wide-packet CSI, or calibrated ED/noise/power. Resume
only with a new discriminating experiment or a healthier reference setup; repeating
already failed controls is not an integration task. Physical recovery or a known-good
independent transmitter may be needed before widening active claims.

Known hazards stay out of public polling APIs: UNI23 diagnostic tag3's command-pool
leak; synthesized link-quality busy/unsupported HWCFG getters; unqualified direct
read-clear MMIO; and the problematic UNI40 table-write handler. Capability metadata
must not turn their zero/ACK responses into measurements.

R31 can proceed as a small documentation deliverable alongside integration: start
with the counter map/ownership corrections, beacon CSI prerequisites/event format,
and reproducible diagnostic command-pool defect. Include firmware hashes, pinned
source/ROM pointers and minimal sanitized reproducers. Separate facts derived from
Linux from new observations. No claim about current upstream absence without checking
its current implementation; no outreach or driver patches implied. Maintainer
acceptance is not a release gate. R21 remains a deferred iPad test spike.
