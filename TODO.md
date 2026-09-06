# TODO: next sprint and prior backlog

## Active sprint: measurement API integration (R32)

Planning checkpoint 2026-09-06: PR #31 is merged at `7eb35d1`; no new release
was cut. The [next-release plan](docs/NEXT_RELEASE.md) is the selected sequence for
remaining research, Python/C integration and acceptance gates.

Execution order: sessions and raw named counters first (implemented below), then
thermal, normal Group5 signal/TX-status timing, CSI, histograms, and final release
qualification. Current next research/integration slice is raw histograms. Group5
raw decoding/guard is implemented; live enabled-phase reliability remains gated.
CSI wire/parser and public session-bound lifetime parity are implemented, with
stage-fault tests and short native/Python coexistence/overflow/cancellation evidence.
Longer acceptance remains open; CSI is narrow and explicitly experimental.

- [x] Reconcile the already implemented `feat/continuous-acquisition` branch on
  `feat/measurement-api` (not main); baseline offline checks pass.
- [x] Implement [named raw-counter records](docs/MEASUREMENTS.md) in Python/C,
  shared wire/failure tests and session probe reuse. Conversion/accumulator widths
  stay unknown; weak MT7921 reception remains an RF qualification limit.
- [x] Deliver query-only thermal primitives in both libraries, including MT7925 raw
  ADC, research helper reuse, failure fixtures and short mixed-session evidence.
- [x] Deliver Group5 signal and TX-status timing primitives in
  both libraries, with research helpers consuming the promoted implementations.
  Group5 remains experimental with a failed live-reliability gate;12/12 live
  TX-status timing records match, but weak RF controls still prohibit new TX claims.
- [ ] Target bounded beacon CSI, then raw histograms, behind separate experimental
  gates; defer either if its validity/cleanup/parity gate is not met.
- [ ] Requalify healthy independent RF controls before any expanded TX profile.
- [ ] Complete packaging, regression and bounded live/session qualification, then
  update release/support/parity docs. No automatic version bump, tag or publication.

## Continuous acquisition sprint (R5)

Integrated from `feat/continuous-acquisition` into `feat/measurement-api`, not main. See
[the session contract](docs/CONTINUOUS_ACQUISITION.md).

- [x] Python single-owner worker, bounded packet/event/command queues, failure latch.
- [x] Native C worker, copied packet queues, ownership guards, safe callback lifetime.
- [x] Shared routing replay, overflow/sequence/cancellation tests, ASan/UBSan and TSan.
- [x] Initial passive MIB/retune hardware checks in both languages on both reference adapters.
- [x] Five-minute native stress, Python/C cancellation, clean reinitialization and
  [durable evidence](docs/TESTING.md#continuous-acquisition-sessions-2026-09-04).
- [ ] Multi-hour passive soak; keep hot-unplug and warm adoption explicitly unqualified.
- [ ] Review and merge after evidence gates, retaining honest retune/queue-loss limits.

## Completed C parity sprint record

Sprint selected and implemented 2026-09-04: C acquisition parity (R30). Items come from
[ROADMAP.md](ROADMAP.md); check off only against the stated evidence. This is the
completion record for the work merged into `main`, not a new release.
[Dated acceptance evidence](docs/TESTING.md#native-c-acquisition-parity-2026-09-04)
records 554 offline tests, live checks on both dongles, and the explicit limits.

## C parity sprint (R30)

Subsequent firmware/chip measurement and transmit exploration merged in PR #31.
[Autonomous continuation findings and next leads](docs/OVERNIGHT_EXPLORATION.md)
and [PHY transmit findings](docs/PHY_TRANSMIT.md) retain the experiments and limits.
Continuous acquisition remains on its pushed branch; its longer soak is still
outstanding. The R32 proposal above supersedes this checkpoint's priority, not its
historical acceptance evidence.

Reference: Python driver and research tooling on `main` at `6081908`. The chipset
primitives below are implemented, tested, and pushed in incremental commits.
Existing CLI behavior and passive defaults are preserved. Generic analysis is
outside this parity contract; see [C_PARITY.md](docs/C_PARITY.md).

- [x] **1. Define the parity contract and shared fixtures.** Inventory each in-scope
  Python helper, intended C entry point, input/output units, chip support, and evidence
  status. Add sanitized synthetic byte fixtures consumed by Python and C for RX groups,
  MCU requests/replies, TX descriptors, and TX status. Separate implemented,
  offline-tested, hardware-confirmed, and not-tested states. No real network identifiers,
  raw ambient captures, or firmware in fixtures.
- [x] **2. RX timestamps and extended vectors.** Export Group-2 hardware timestamps
  with presence flags and documented wrap/clock semantics, plus bounded Group-3/5 data
  for both chips, matching `research/rx_vector_probe.py` and the Python decoders.
  Preserve chip-specific group lengths and descriptor-declared DMA bounds. Keep raw
  words and exploratory interpretations clearly separate; absence is not a zero
  measurement. Do not manufacture a 64-bit TSFT or label candidates as calibrated SNR.
  *Acceptance:* shared fixtures cover missing/truncated groups, G5 without G3, timestamp
  wrap values, both descriptor layouts, and unchanged frame slicing/radiotap behavior.
- [x] **3. MCU channel-occupancy acquisition.** Port the MT7921 EXT MIB path and MT7925
  atomic UNI batches, with pure request/reply helpers and explicit offset/value output.
  Validate lengths, echoed offsets, duplicate/missing entries, wrong-sequence replies,
  timeouts, and counter reset/wrap handling. Report the actual counter sampling window
  and MCU-induced frame drops; don't silently compare different time/bandwidth scopes.
  *Acceptance:* offline malformed/stale-reply tests and repeated C reads on both chips,
  with primary-20-MHz scope. Offset 20 remains ED-active, never non-Wi-Fi time.
- [x] **4. Reversible experimental receive reporting.** Provide explicit opt-in MT7921
  Group-5 enable/restore with readback, saved prior bit state, and restoration on normal
  and error exits. Do not change the default: upstream disables this feature for hardware
  issues. *Acceptance:* fault-injection coverage plus baseline/enabled/restored captures;
  short success does not establish soak safety, and buffered transition records are allowed.
- [x] **5. Controlled TX and per-chip TX status.** Port the measured connac2 OFDM path,
  connac3 descriptor geometry and fixed-rate table setup, DIS_MAT source preservation,
  candidate attenuation controls, and both TX-status record layouts. Keep the old API's
  behavior explicit; do not silently enable MT7925 injection through an existing call.
  Constrain new CLI operations to the measured frame/rate/channel/power-code combinations,
  bounded counts, pacing, timeouts, explicit TX acknowledgement, and firmware cleanup.
  *Acceptance:* byte-level golden tests, invalid-input rejection before USB writes,
  bounded table polling, format-aware TX-status parsing, and independent receive from
  the other dongle. USB completion or no-ACK TX status alone is not delivery evidence.
  Raw signed power fields are not calibrated dBm; no new band or rate claims by inference.
- [x] **6. Hardware qualification and handoff.** Run existing offline gates and C
  sanitizer tests, then C passive capture regressions on both reference adapters.
  Cross-check new C telemetry against the reference semantics and independently validate
  transmitted rate/frame contents with the other receiver, including restoration and
  alive checks. Record commands, firmware hashes, counts, failures, and untested cases
  in `docs/TESTING.md`. Update `c/README.md` with an honest parity matrix and usage.
  Do not mark the sprint done based only on existing C tests passing.

### Sprint boundaries

- C owns chipset acquisition, transport, bounded binary decoding, and controlled radio
  primitives. Generic IE/MLO parsing, clock fitting, BlockAck delivery analysis, experiment
  orchestration, and topology inference may stay in Python/downstream consumers. The C
  output must expose the metadata needed by them; copying every script is not parity.
- Keep working behavior intact and use additive, explicit experimental APIs. A passive
  command must never begin transmitting as a consequence of this port.
- R21 is a deferred iPad survey spike, not work to execute now. Proper networking-driver
  and baseline-connectivity work are durable non-goals.
- R31 is a possible documentation/pointers package for Linux maintainers after this
  sprint, not an upstream implementation obligation or permission to send messages.
- The older open items below are retained backlog, not competing sprint priorities.
  A human-driven roaming test is not a prerequisite for these C ports.

## Prior sprint record and carried backlog

The following record started 2026-09-01 and was refocused 2026-09-03 after 0.2.0.
Historical PR/review instructions below describe that earlier workflow; they are not
the active merge gate for R30. Items requiring a forced roam still need an operator
and a multi-AP environment. They are not silently marked complete by this replan.

## Fix the occupancy comparison before PR #25 lands

Found by review pass three on `spike/firmware-recon`. The occupancy counter is sound; the
quantity it is compared against is not. Each step below is checkable, and the numbers already
published in `docs/TESTING.md` are wrong until step 4 replaces them.

- [x] ~~**1. Count aggregated airtime once, not per subframe.** `scripts/mib_survey.py` sums
  `rxd.airtime_us` per frame, charging every A-MPDU subframe a full preamble. Forty 100-byte
  HE subframes at 100 Mbps come to 2400 µs that way against 384.8 µs through `rxd.Aggregate`.
  Use `rxd.AggregationTracker`, feeding `(decoded, len(frame), addr2)` and summing
  `Aggregate.airtime_us()` over what `feed()` returns plus a final `flush()`.
  *Done when:* a test drives the dwell loop with a synthetic A-MPDU and shows the summed
  airtime matching the aggregate rather than the per-frame total.~~ Done. Note the measured
  captures contain no A-MPDU subframes at all, so this fixed a latent defect rather than the
  numbers: it was **not** the cause of the negative 5 GHz residual, contrary to what the pass
  three write-up assumed.
- [x] ~~**2. Measure the counter over the interval the denominator describes.** The offset-11
  baseline is currently read before two further MCU queries and its final value after three,
  while frames are counted only between `started` and the loop exit, so occupancy during five
  round trips lands in the numerator but not the denominator. Read the CCA counter last before
  the dwell and first after it, and take `elapsed_us` across those two reads.
  *Done when:* a test asserts the dwell window encloses the frame loop, and `busy_fraction`
  cannot exceed 1 for that reason.~~ Done.
- [x] ~~**3. Stop counting ordinary receive timeouts as transport errors.**
  `usb.core.USBTimeoutError` subclasses `USBError`, so every routine 250 ms `rx_read` timeout
  on a quiet channel increments `usb_errors`; a silent one-second dwell reports about four.
  `scripts/retune_drops.py` already separates them. *Done when:* a test feeds a timeout and a
  real transport error and only the second is counted.~~ Done.
- [x] ~~**4. Re-measure, then rewrite the numbers.** Every occupancy figure in
  `docs/TESTING.md` and `docs/FIRMWARE_RECON.md` was produced with the inflated decoded
  airtime and must be replaced, not annotated. Delete the explanation of the negative 5 GHz
  value in both the docs and `mib_survey.py`: it attributes the sign to accumulated per-frame
  rounding, which was asserted without testing and is wrong. The cause was this defect.
  *Done when:* the docs carry fresh figures from a dated run and no retracted text survives.~~
  Done, and the explanation replaced rather than corrected in place: the 5 GHz residual is
  noise around zero, −9,607 µs on one dwell and +18,331 µs on the next, not a systematic
  negative needing a cause.
- [ ] **5. Review, then land.** One `codex-review` pass over the result. PR #25 stays a draft
  until steps 1-4 are done.

## Known limits of the two-adapter capture

- [ ] **The radios do not share one capture clock.** Each thread starts its own window once
  its own firmware is up, and the chips do not take the same time: measured on the
  reference pair over three runs, the MT7925 is ready at 1.83 s and the MT7921 at 2.81 s,
  a gap of 0.98 s reproducible to 0.01 s. The same offset applies at the stop. The result
  now reports the interval when every radio was listening (`shared_window`), so a run no
  longer implies coverage it did not have, and the offset sits at the start of a run,
  before an operator has triggered anything. Fixing it properly means a barrier after tune
  with one shared deadline, which needs a timeout and a broken-barrier path so a radio that
  never comes up cannot hang the other. Do that with R15, where a lost second actually
  costs a measurement.

## Measure before building

- [ ] **R14/R15 hypothesis check, second attempt.** This is deferred from the C sprint and needs
  a person: nothing else on this list is blocked. The first attempt (2026-09-02) locked one
  radio to one channel and saw none of five roams of an MLO client; the network's own
  management log did. Both named causes are fixed: ~~Multi-Link element parsing, so every link
  address of the client matches~~ and ~~watching at the access point's own width~~. A second
  radio can now hold the target channel (`scripts/dual_capture.py`). What remains is the run:
  force a roam of a known client with the controller log as the reference, one radio on the
  source channel and one on the target. Fix the shared capture clock first, since a roam is
  short enough for a one-second offset to hide half of it.
- ~~**roam_watch --width.** The watcher takes 20/40/80/160 MHz, resolves the center channel from
  the control channel, and refuses a width the attached chip has no evidence for.~~

## Build

- [ ] **R14. Survey record primitive.** `examples/survey.py --ssid NAME` emits one redacted JSON
  record with per-BSSID RSSI, channel, advertised width, BSS Load, and k/v/r flags, using the
  parsing `rxd.py` already has. Schema file beside it, offline test on synthetic beacons.
- [ ] **R1 remainder.** Requested-versus-actual channel per step and a `not_tested` status in
  `scripts/hardware_smoke.py`.
- [x] **R11 CCA/MIB.** MCU paths now expose primary CCA on both chips: identified MT7921 EXT
  offset11 and source/ROM-identified MT7925 UNI offset17 (offset19 is CCA+NAV+TX), with reproducible probes and dated
  evidence.
- [ ] **R12 noise floor.** The available paths remain zero or idle; continue the documented IPI
  and PHY investigation without presenting RSSI as SNR.

## Landed this sprint

- ~~R16 plumbing: `scripts/dual_capture.py` runs both adapters at once, each on its own band,
  channel, and width, into one event log; 80620 frames over five minutes with no USB error.
  Adapters are picked by USB id or by the port they occupy, so two of the same model are
  separable without a serial number.~~
- ~~802.11be Multi-Link element decode and `rxd.station_addresses`, so a watcher follows a
  client across links that each use a different address; fixtures cross-checked against tshark,
  and 293 / 391 live beacons decoded on the two chips.~~
- ~~`roam_watch --width` at 20/40/80/160 MHz, with `mt7921u.center_channel` and per-chip
  `MAX_WIDTH_MHZ`, so a width that would tune a silent radio is refused instead.~~
- ~~Radiotap VHT field corrected from 10 bytes to 12. Every VHT frame this driver wrote was
  rejected by Wireshark as malformed; 19 of 19 before, 0 of 14 after.~~
- ~~R26 C driver MT7925: device table, class-based interface selection, chip profiles, UNI
  commands, connac3 decoder; `c/mt7921_smoke --plan all` passes on the A9000.~~
- ~~R27 EHT radiotap: U-SIG and EHT TLVs in both writers; 973 live EHT frames dissected by
  tshark at 160 MHz; 0.3.0.~~
- ~~R22 / R2: MT7925U port. The Nighthawk A9000 boots, receives on 2.4 / 5 / 6 GHz, decodes to
  radiotap pcap, and captures 160 MHz HE data from a known transmitter; 0.2.0.~~
- ~~A9000 day one: descriptors recorded with pyusb, chip id `0x7925` read, no Bluetooth
  interface present; R2 descriptor discovery and `scripts/usb_descriptors.py` shipped.~~
- ~~R5 drop magnitude measured: median 1 frame lost per retune, max 8, over 30 hops at 100 to
  250 frames per second; `scripts/retune_drops.py` and the `mcu_wait` counters shipped.~~
- ~~R18 decision: 0.1.0 is not released. CHANGELOG entry moved back under Unreleased; tagging
  waits on the publication checklist.~~
- ~~Roadmap regrouped into goal tracks; R14 to R21 added.~~
- ~~NEGATIVE_RESULTS.md created with the two known zeros.~~
- ~~Random-input fuzz test for the descriptor, frame, and IE parsers.~~
- ~~CLAUDE.md for agent sessions.~~
