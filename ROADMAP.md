# Roadmap

The project serves three goals, and the roadmap is organized as one track per goal:

- **Track A, roaming and steering instrument.** A Mac-attached passive radio that answers,
  for one location at a time, which APs are audible, whether they advertise 802.11k/v/r,
  whether they steer clients, and whether clients accept the steer. Survey orchestration and
  site analysis are the consumer's job, not this repository's.
- **Track B, community capture source.** A Wireshark extcap and a distributable install so
  other people's adapters and tools can use the driver without reading it.
- **Track C, researcher reference.** A small, readable, evidence-gated reference for MT7921U
  bring-up that a wireless researcher, or an AI assistant helping one, can find and trust.

Items carry stable `R` numbers because other documents cite them; numbers do not imply order.
Within a track, items are stack-ranked top to bottom. Strike an item through when it merges.
The evidence behind the current baseline is in [docs/TESTING.md](docs/TESTING.md): the
`0e8d:7961` (MT7921U) and `0846:9072` (MT7925U) reference devices capture on 2.4, 5, and 6 GHz
and write radiotap pcap; the MT7925U also captures 160 MHz. Wider
claims require wider evidence. The current sprint is in [TODO.md](TODO.md); measured
negatives are in [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md).

## Priority decision, 2026-09-04

The selected sprint is **R30: C acquisition parity with the Python research baseline**,
now implemented and qualified on `feat/c-acquisition-parity` (not yet merged).
This is an instrument for network interrogation and bounded radio experiments, not
baseline connectivity. A proper networking driver is a durable non-goal, not a
deferred implementation project. R21 is a deferred iPad survey test spike; no iPad
implementation is part of this sprint. R31 is a prospective documentation handoff
to Linux maintainers, not a commitment to write their implementation or contact them.

## Decision rules

- Prefer passive capture correctness, observability, and interoperability over new active
  operations.
- Treat firmware output and 802.11 frames as untrusted binary input: bounds checks, timeouts,
  cleanup, and negative tests are release requirements.
- Add a USB ID, bandwidth, band, or chip family only after recording dated hardware evidence.
- Keep protocol knowledge reusable: documented structures, small pure functions, and sanitized
  test vectors are more valuable to peers than another monolithic command-line tool.
- A failed experiment can complete a roadmap item if the limits and evidence are documented in
  [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md). Check that file before proposing an experiment.
- Treat the cross-project findings in
  [RELATED_WORK.md](RELATED_WORK.md#what-this-project-can-learn-from-the-ecosystem) as an
  investigation queue, not inherited capability. Reimplement independently, preserve license
  boundaries, and require local evidence.
- The Python code stays the reference implementation; the native C acquisition implementation
  lives in [`c/`](c/README.md) in this repository. Keep the chipset primitives in parity, not
  every Python analysis script. Other implementations prove themselves against the protocol
  document (R19), recorded USB corpus (R20), and conformance suite (R23) as those land.
  A future standalone app-embedding package may live in a sibling repository. Wireshark needs
  no native code: extcap is a separate process (R6).

## Track A: roaming and steering instrument

The decoder already classifies the whole roaming vocabulary: BTM query, request, and response
with named status codes, neighbor reports, FT authentication and reassociation, the Extended
Capabilities BSS-transition bit, and BSS Load. `rxd.management_event` normalizes all of it and
nothing outside `tests/` consumes it yet. This track builds the consumer.

One radio cannot watch both channels of a roam. The BTM exchange, the deauth or disassoc with its
reason code, and the client's last data frame occur on the current AP's channel; only
authentication and reassociation occur on the target. That split is standard 802.11 behavior and
is the working hypothesis behind R15, but it has not been confirmed against a phone on this
hardware. R14's first measurement is to confirm it.

### R14. Survey record primitive

Add a passive command that sweeps the channels of one SSID (or all bands) once and emits a
single JSON record for wherever the radio is: audible BSSIDs of that SSID with RSSI, channel,
advertised operating width, BSS Load, and the 802.11k/v/r flags each AP advertises. A caller
supplies any label it wants; this repository does not know about places, walks, or reports.
Use the redacted-JSON pattern from `scripts/hardware_smoke.py`; identifiers are opt-in.

Done when the record is schema-checked, each field cites the frame and IE it came from, and
the command has been run on the reference adapter in a multi-AP environment.

### R5. Long-lived capture session with a single RX reader

Boot once, retain ownership of the initialized device, retune safely, and stream until stopped.
This removes the firmware upload cost from each capture and closes a measured, small fidelity
gap: MCU replies and 802.11 frames share endpoint `0x84` once EP4 routing is on, and `mcu_wait`
discards every frame it reads while hunting for its reply. Measured with `scripts/retune_drops.py`
on 2026-09-02 ([docs/TESTING.md](docs/TESTING.md#retune-frame-loss-2026-09-02)): a retune is two
commands totalling about 16 ms, and with the caller draining continuously it drops a median of one
frame per hop and at most eight, at 100 to 250 frames per second. That is a 16 ms blind window per
hop, not bulk loss. The device object now carries the drop counters, so any caller can attribute
lost frames to the command that lost them; R5 turns that into a queue that loses nothing.

Done when one reader drains the endpoint and demultiplexes into an MCU-reply queue and a frame
queue; startup, stop, retune, and device-loss behavior have explicit states; cancellation does
not corrupt output; and queue depth, frames dropped (including frames dropped during a retune),
USB errors, and current channel are observable. Cold boot, warm reattach, and recovery must be
distinct transitions; a warm path must drain or classify buffered RX without accidentally
accepting a stale MCU response.

### R15. Channel lock, follow mode, and the roaming event log

Lock the radio to one client's current AP channel, log every steering and roaming event from
`rxd.management_event` with a timestamp, and follow the client on reassociation or to a BTM
target channel. Emit a classified per-session log: AP never steered; AP steered and the client
refused with status X; the client roamed on its own with reason Y; the roam completed on the
target channel or was not observed there.

Done when a forced roam of a known client on the reference adapter yields the expected event
sequence on the source channel, the arrival on the target channel is either captured or reported
as unobserved (never inferred), the per-hop blind interval is measured and reported, and the
event log is schema-checked and redacted by default.

An MLO client (Wi-Fi 7) associates on several links with per-link addresses; a management view shows
only the MLD address. A watcher matching one address misses the client on every other link, which
is what happened on 2026-09-02 ([docs/TESTING.md](docs/TESTING.md#single-radio-roaming-observation-same-day)).
The decoder now reads those addresses: `rxd.parse_multi_link` returns the MLD address and each
Per-STA Profile's link address, and `rxd.station_addresses` scopes them to the frame's
transmitter so an AP cannot join a client's identity. `roam_watch --client` and
`scripts/dual_capture.py` grow their address set from the client's own frames. What is still
unproven is the part that needs a client: no per-STA profile has been captured on air, because a
beacon does not carry one and no association has been observed, so that path rests on synthetic
fixtures cross-checked against tshark.

Both prerequisites the 2026-09-02 attempt failed on are now in place, and a second radio can hold
the target channel. What remains is the run itself: force a roam of a known client with the
network's own log as the reference, one radio on the source channel and one on the target.

### R3. Failure handling and soak evidence

Make disconnects, USB stalls, bad firmware responses, partial transfers, Ctrl-C, and retune
failures predictable.

Done when offline fault-injection tests cover cleanup and timeout paths, a repeated retune test
and a multi-hour passive capture complete without leaked interfaces, and drop/error counters
appear in the result. Tests must include a short bulk write, a stale or wrong-sequence MCU reply,
an unsolicited event, and a stalled endpoint. Hot-unplug remains explicitly untested until
exercised on hardware.

### R16. Multiple adapters (partly done)

On 2026-09-02 a client moved through five APs on three bands in ten minutes while a single
locked radio observed none of the transitions ([docs/TESTING.md](docs/TESTING.md)).
After R2, open more than one adapter in one process so a second radio can sit on the roam
target channel while the first stays on the source. Two adapters of the same USB ID must be
distinguished without relying on serial numbers appearing in output.

Done when two reference adapters capture concurrently with per-device counters, a forced roam
is observed on both source and target channels in one run, and the single-adapter path is
unchanged.

~~Concurrent capture with per-radio counters~~ (`scripts/dual_capture.py`, 2026-09-03): both
adapters run in one process, each locked to its own band, channel, and width, merged into one
event log on one clock, with a client's link addresses learned on either radio matched on both.
An adapter is picked by USB id or by the port it is attached to, so two of the same model are
separable without a serial number ([docs/TESTING.md](docs/TESTING.md#two-adapters-capturing-at-once-2026-09-03)).

Remaining: a forced roam observed on both the source and the target channel in one run. That
needs a client driven across a boundary, so it belongs with R15 rather than with the plumbing.
The radios also start about a second apart, since each boots its own firmware; the result reports
the interval when both were listening, and one shared deadline is work for R15.

### ~~R22. MT7925U port for 160 MHz and Wi-Fi 7~~ (landed 2026-09-03)

Every 6 GHz AP in the reference house runs 160 MHz and the MT7921 returns nothing when
configured for it, so client data on 6 GHz is invisible to this adapter
([NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md)). The MT7925 (Netgear A9000) decodes 160 MHz.
[docs/MT7925.md](docs/MT7925.md) records what the upstream driver says the port involves,
checked line by line against the pinned mt76 source: the USB bring-up and firmware download are
shared, the sniffer command is byte-identical, and the work is the WFSYS reset, the MCU reply
header, four commands moving to UNI encoding, and a connac3 RX descriptor decoder.

Done when the A9000 boots, tunes, and captures on 20, 80, and 160 MHz through the existing
redacted smoke schema, with descriptor discovery (R2) rather than a hard-coded interface, a
connac3 decoder with synthetic fixtures, and a dated evidence section in docs/TESTING.md.

Done: `mt7925u.py`, `rxd_connac3.py`, and the 2026-09-03 evidence in docs/TESTING.md. Two
follow-ups fall out of it:

### R11 and R12, run as a parallel spike: channel-busy counters and noise floor

R11 is now answered through MCU queries rather than the dead register path: MT7921 EXT offset 11
and MT7925 UNI offset 19 provide primary CCA time. R12 remains open: the noise-floor helper reads
zero and the IPI sampler remains idle. The reproducible probes and negative paths are in
[docs/FIRMWARE_RECON.md](docs/FIRMWARE_RECON.md) and [docs/MT7925_MIB.md](docs/MT7925_MIB.md).

- **R11. Hardware CCA/channel-busy counters.** Determine whether the missing step is firmware
  configuration, counter selection, reset/latch behavior, or a firmware limitation. wifikit
  reports MT7921AU MIB/test-mode experiments, but those are leads only; record the exact
  registers and reset/latch sequence independently against the pinned mt76 source. Done when
  counters correlate with controlled traffic across repeated trials, including idle and busy
  channels, or when a documented negative result explains why they are unavailable. Frame counts
  must not be relabeled as channel utilization.
  **Done 2026-09-04:** live counters correlate with decoded airtime, controlled traffic, primary
  rotation, and an independent receiver. They measure the primary 20 MHz, not an entire wide
  channel.
- **R12. Noise floor.** The `mt792x_phy_get_nf()` path returns zero. Find and validate a real
  per-channel or per-chain source, or document that this firmware path does not expose one.
  Done when values respond plausibly to controlled RF conditions and are compared with an
  independent instrument, or the negative result is recorded. RSSI alone must not be presented
  as SNR.

## Track B: community capture source

### ~~R27. EHT radiotap~~ (landed 2026-09-03)

Done: both writers emit U-SIG and EHT TLVs; live EHT frames from an 802.11be client on the
160 MHz 6 GHz channel dissect in tshark with rate, MCS, streams, and bandwidth.

`rxd_connac3` decodes EHT-SU/TRIG/MU frames (mode, MCS up to 13, NSS, width) but the pcap writer
emits only Flags/Channel/dBm for them, so Wireshark shows no rate. Add the radiotap EHT and
U-SIG fields. Done when an EHT frame captured on the MT7925 shows its MCS and width in Wireshark.

### ~~R2. Descriptor discovery and explicit device support~~ (landed 2026-09-03)

Replace the hard-coded interface 3 and endpoint layout with descriptor inspection and an
explicit supported-device table. This is the first thing that fails for anyone whose adapter is
not the reference unit, so it precedes extcap. Do not infer that every `0e8d:7961` enclosure
has the same layout.

Done when descriptor selection is unit-tested with synthetic layouts, ambiguous layouts fail
closed with useful diagnostics, and each claimed adapter has a dated smoke result.

### R6. Wireshark extcap, bundled with rate, MCS, and width in radiotap

Add an extcap adapter that exposes supported channels and emits radiotap capture data on stdout,
consuming the R5 session API rather than duplicating driver logic. Ship it with the subset of R8
that the decoder already produces: rate, MCS, and channel width. A first Wireshark-visible
experience without PHY rate is a half-feature.

Done when Wireshark can enumerate the adapter, select a supported band/channel, start and stop a
capture, and open the result without malformed packets and with rate columns populated. The
workflow must be hardware-tested on a clean macOS account and documented with its permissions
and firmware requirements.

### R17. Distribution

An extcap must be an executable Wireshark can find. A venv, Homebrew libusb, and a firmware
fetch script are too much friction for adoption. Choose and document one install path (a pipx
console script, a Homebrew formula, or a zipapp) that places the extcap where Wireshark looks
and fetches firmware with the same pinned hashes as `setup.sh`.

Done when a fresh macOS account goes from nothing to a Wireshark 6 GHz capture by following one
page, and [docs/PUBLISHING.md](docs/PUBLISHING.md) records the chosen path and why PyPI is or is
not part of it.

### R8. Rich, verified radiotap

Export only metadata the hardware actually supplies: channel/bandwidth, RSSI per available
chain, rate/MCS, aggregation flags, FCS state, and timestamps where trustworthy. Today the pcap
writer emits flags, channel, and one signal value; the decoder already produces more, and the
hardware timestamp is decoded but unused.

Done when each field has a source citation to mt76 or the hardware message format, golden tests
cover legacy/HT/VHT/HE samples, and Wireshark agrees on a sanitized hardware corpus. Unknown
values must be omitted rather than synthesized.

### R7. Capture format, metadata, and privacy

Move from the minimal pcap writer toward pcapng where it adds useful interface, channel,
firmware, and drop metadata. Add bounded file rotation and explicit payload handling.

Done when Wireshark independently accepts all emitted formats, timestamps and snap length are
specified, rotation cannot silently overwrite unrelated files, and documentation explains that
802.11 captures may contain personal or sensitive data.

### R9. Qualify bandwidth and control-channel combinations

Test 20/40/80 MHz and valid primary/center-channel combinations on each applicable band.
Do not claim 160 or 320 MHz on MT7921U merely because adjacent chips support them.

Done when a table records pass/fail/not-tested for every claimed combination, invalid requests
fail before USB I/O, and captures are independently decoded. Regulatory restrictions remain
the operating system/user's responsibility and must be stated.

### R10. A-MSDU de-encapsulation

Split validated A-MSDU payloads into their inner frames while preserving the original MPDU and
aggregation metadata for callers that need it.

Done when malformed length/padding cases cannot overrun input, golden and property-based tests
cover multi-subframe inputs, and the capture output behavior is documented.

## Track C: researcher reference and discoverability

### R30. C acquisition parity (implemented and qualified; awaiting merge)

Completed 2026-09-04 on `feat/c-acquisition-parity`: [port contract](docs/C_PARITY.md),
[acceptance evidence](docs/TESTING.md#native-c-acquisition-parity-2026-09-04).
Keep this item unstruck until merged; completion covers the instrument primitives,
not every Python analysis script or all possible RF configurations.

Port the measured chipset primitives from the Python research baseline on `main`
(`6081908`) into the existing C implementation. The old capture baseline and passing
C tests do not imply parity with the 2026-09-04 experiments.

Scope: bounded RX timestamp and extended-vector extraction; MT7921 EXT and MT7925
UNI MIB queries; explicit, reversible experimental Group-5 reporting on MT7921;
controlled transmit descriptors, MT7925 rate-table setup, and per-chip TX-status
decoding. Preserve the narrow, opt-in transmit envelope and do not promote unknown
vector fields to calibrated SNR, noise, or absolute transmit power.

Done when the [sprint acceptance checklist](TODO.md#c-parity-sprint-r30) passes:
shared synthetic byte fixtures, malformed-input and timeout tests, existing capture
regression checks, and dated C hardware evidence on both reference dongles. Each
capability must distinguish implemented, offline-tested, hardware-confirmed, and
not-tested status. No firmware or ambient traffic is committed.

Generic IE parsing, clock fitting, BlockAck delivery analysis, and survey/topology
inference remain Python/downstream concerns. C supplies the acquisition primitives
those analyses need, not a second implementation of the whole research toolkit.

### R31. Linux maintainer evidence handoff (proposed, after R30)

Prepare a short, useful documentation package, not an unsolicited driver rewrite.
Lead with the MCU survey-counter findings in [MT7925_MIB.md](docs/MT7925_MIB.md)
and the MT7921 path in [FIRMWARE_RECON.md](docs/FIRMWARE_RECON.md). Include exact
command layouts, offset semantics and confidence, firmware hashes, pinned mt76
files/symbols, minimal reproduction commands, and links to redacted evidence.

Secondary pointers: [RX vectors and clocks](docs/RADIO_OBSERVABILITY.md),
[controlled MT7925 transmission](docs/MT7925_TRANSMIT.md), and
[primary-channel capture limits](docs/CHANNEL_GEOMETRY.md). Clearly distinguish
mechanisms already derived from Linux from observations made with this instrument.
Do not claim that current Linux lacks a feature without checking the current path.
Retain the upstream Group-5 hardware-issue warning and all measurement caveats.

Done when a maintainer can identify the relevant source path and reproduce a
specific observation without reading our full research history. List remaining
Linux-side validation questions; implementing a patch, obtaining adoption, and
doing outreach are not completion requirements. Sending the package is a separate
decision, not authorized by this roadmap entry.

### ~~R26. C driver: MT7925 support~~ (landed 2026-09-03)

`c/` still matches only `0e8d:7961` on interface 3 and decodes connac2. Port the Python port:
descriptor-driven interface selection, the `mt7925u.py` MCU geometry and UNI commands, and a
connac3 `mt7921_rxd_decode` sibling, checked against the same synthetic fixtures. Done when
`c/mt7921_smoke` passes on the A9000 with the evidence format used for the Python driver.

### ~~R29. Publish 0.3.0~~ (tagged 2026-09-03)

C driver MT7925U support and EHT radiotap, released after the 43-channel C and Python smoke
sweeps passed on the release commit with the A9000.

### ~~R28. Publish 0.2.0~~ (tagged 2026-09-03)

MT7925U support and 160 MHz capture, released after the 43-channel smoke sweep passed on the
release commit with the A9000; the redacted result is attached to the GitHub release.

### ~~R18. Publish 0.1.0~~ (tagged 2026-09-02)

Done: `0.1.0`, `0.2.0`, and `0.3.0` are published with matching changelog sections and release
metadata. Future releases follow the [publication checklist](docs/PUBLISHING.md).

### R20. Recorded-USB corpus and fake transport

The language-neutral contract. Record sanitized USB transfers from the reference adapter (firmware download, MCU exchanges,
retunes, and a short capture on each band) and replay them through a fake transport in tests.
Every implementation, in any language, is tested against the same bytes; it is also what lets
R3's fault-injection tests exist, and it must be captured from both the MT7921 and the MT7925.

Done when the offline suite boots the driver end to end against the corpus with no adapter,
the corpus contains no SSIDs, MAC addresses, serials, or payloads, and a documented tool
regenerates it from hardware.

### R19. Protocol document: the contract for every implementation

Write `docs/PROTOCOL.md`: the bring-up sequence, every MCU message used with its byte layout and
offsets, the RX descriptor layouts for connac2 (MT7921) and connac3 (MT7925), the width and band
tables, and the five measured findings, each with an mt76 file and line citation at the pinned
baseline and the error seen when the step is missing. It is what a C or Swift author reads instead
of the Python, and what a researcher's assistant retrieves. Publish an indexed write-up with the
same terms, mint a DOI against `CITATION.cff`, and request links from where researchers look: the
mt76 issue tracker, the adapter threads, the Wireshark extcap wiki, the peer READMEs.

Done when every statement in the document cites source or a dated measurement, a second
implementation could be written from it without reading `mt7921u.py`, the DOI exists, and at
least one external inbound link is live.

### R23. Conformance suite over the corpus

Define the replay format (NDJSON or similar: direction, endpoint, bytes, timestamp) and a suite
of checks any implementation can run: boots to `N9_RDY` with the recorded exchanges, decodes each
recorded transfer to the recorded frame and metadata, tunes with the recorded commands. "Supports
MT7921U" then means passing the suite, whichever language.

Done when the Python reference passes it from the corpus alone, the format and checks are
documented for another language to implement, and a sibling implementation has run it.

### R1. Repeatable passive hardware smoke command (mostly done)

~~Create one non-interactive command that boots firmware, tunes a redacted channel set, captures
frames, and emits a machine-readable result~~ (`scripts/hardware_smoke.py`, with a checked-in
schema, a redacted reference result, and an offline test). ~~Redacts SSIDs, BSSIDs, client
addresses, and payloads by default.~~ ~~Reports USB identity, firmware hashes, macOS/Python
versions, transfer/frame counts, timeouts, and decode failures.~~

Remaining: report requested and actual channel per step, distinguish `not tested` from
`inconclusive`, and add optional independent pcap validation through tshark.

### R4. Maintainable Python boundary

Replace runtime method attachment and heterogeneous dictionaries with typed result objects and a
small transport interface. Do this after R5 fixes the session API shape; typing an interface
that R5 then reshapes is rework. Readability of the two flat modules is a feature of this
track, not a cost to be optimized away.

Done when the public capture path passes an agreed mypy or pyright configuration without broad
module ignores, USB behavior can be tested through the R20 fake transport, and the compatibility
policy for public Python APIs is documented.

## Deferred

### R13. Additional MT7921U layouts and sibling chips

After descriptor discovery and the smoke schema are stable, qualify rebadged adapters and then
consider MT7922 or other connac2/connac3 devices. Shared upstream code is a starting hypothesis,
not proof of compatibility.

Each newly claimed model needs captured descriptors, an explicit capability record, firmware
provenance, offline fixtures, and tri-band/bandwidth hardware results appropriate to that model.

### R21. iPad survey test spike (deferred; not this sprint)

Third-party USB drivers exist on iPadOS 16 and later for M-series iPads through DriverKit
([WWDC22 session 110373](https://developer.apple.com/videos/play/wwdc2022/110373/)), distributed
through the App Store and enabled by the user in Settings. A future spike would replace
the macOS IOKit transport with a C++ USBDriverKit extension, reusing portable C protocol
and decoder code where practical. It is not a from-scratch rewrite of our chipset knowledge
and does not require a system networking interface. No supported direct raw-USB path for
these stock dongles in an ordinary iPhone app was found.

Bound the first test to one M-series iPad and one reference dongle: establish entitlement
and installation feasibility, claim the USB interface, boot pinned firmware, tune one
channel, deliver capture metadata to a foreground app, and stop/reconnect cleanly. Record
power/hub requirements, capture/drop rates, battery/thermal behavior, and the practicality
of a short walk. Unsupported or entitlement-blocked results are valid spike outcomes.

Entitlements, hardware availability, and USB power remain unverified. Schedule explicitly
after C acquisition parity; no iPad code, entitlement application, purchase, or hardware
test is being started by this roadmap decision. This is a survey spike, not connectivity
or an iPhone workaround project.

### Gated optional track: transmit

Injection remains a research demo: 60 spaced probe requests have worked with the chip alive
after, sustained or high-rate transmit is untested, and the current publication evidence does
not re-test injection. The Linux "injection kills the chip" reports are a host-driver bug
(upstream `d367ee6d`), not evidence about this path.
Passive milestones do not depend on this track.

Before any broader transmit API or claim:

- supported frame types, rates, channels, and regulatory assumptions must fail closed;
- regulatory-domain and per-band TX-power programming must be implemented and independently
  reviewed before transmitting outside an isolated test setup;
- sequence control, endpoint selection, basic-rate choice, hardware retry state, and ACK
  behavior must have golden descriptor tests and hardware evidence;
- tests must run in an isolated RF environment with a watchdog and recovery procedure;
- acknowledgements, firmware failures, queue depth, and rate limiting must be observable; and
- sustained and malformed-input tests must demonstrate bounded behavior.

Linux mt76 issue [#839](https://github.com/openwrt/mt76/issues/839) and upstream commit
[`9de65849`](https://github.com/openwrt/mt76/commit/9de658490af758f89c083605bd412310511fff17)
show why the generic "active monitor" capability must not be assumed for MT792x. A peer's
spoofed-address auto-ACK experiment is a hypothesis to reproduce, not evidence for this driver.

The project does not plan to reproduce wifikit/wifit3 attack suites. If transmit becomes stable,
the useful output is a narrow, documented primitive that those projects could evaluate.

## Continuing release requirements

Every release that changes hardware behavior should include:

- macOS-only offline CI for supported Python versions, formatting, linting, tests, and package
  construction;
- dated evidence for the exact attached hardware and firmware hashes;
- independent validation of capture files (for example, Wireshark/tshark malformed checks);
- updated support and not-tested tables, security/privacy notes, and upstream citations; and
- release notes that separate implementation, hardware-confirmed behavior, and hypotheses.

## Durable non-goals and physical limits

- This is not a macOS Wi-Fi client, replacement system driver, AP, or general-purpose security
  suite. A proper networking driver (including an Ethernet-style DriverKit facade), managed
  association/authentication, routing/NAT, and baseline Internet connectivity are explicitly
  out of scope, not deferred roadmap work. Instrument-only USBDriverKit transport for R21
  does not change that boundary.
- One radio cannot capture multiple channels simultaneously.
- MT7921U 160/320 MHz capture is not promised; firmware/hardware capability is a real boundary.
- CI cannot establish RF correctness because hosted macOS runners do not have the adapter.
- CoreWLAN and NetworkExtension integration are not goals unless they can consume a userspace
  capture source without pretending this device is a system Wi-Fi interface.
