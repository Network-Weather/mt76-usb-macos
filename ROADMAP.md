# Roadmap

This roadmap is ordered by user value and risk reduction, not by novelty. The project should
first become a trustworthy, composable macOS capture source for the exact tested MT7921U
hardware. It should not recreate the broad adapter support or attack engines already offered
by [wifikit and wifit3](RELATED_WORK.md).

The evidence behind the current baseline is in [docs/TESTING.md](docs/TESTING.md): the exact
`0e8d:7961` reference device captures on 2.4, 5, and 6 GHz and writes radiotap pcap. Wider
claims require wider evidence.

## Decision rules

- Prefer passive capture correctness, observability, and interoperability over new active
  operations.
- Treat firmware output and 802.11 frames as untrusted binary input: bounds checks, timeouts,
  cleanup, and negative tests are release requirements.
- Add a USB ID, bandwidth, band, or chip family only after recording dated hardware evidence.
- Keep protocol knowledge reusable: documented structures, small pure functions, and sanitized
  test vectors are more valuable to peers than another monolithic command-line tool.
- A failed experiment can complete a roadmap item if the limits and evidence are documented.

## 0.1.x — Trustworthy reference implementation

### R1. Repeatable passive hardware smoke command

Create one non-interactive command that boots firmware, tunes a redacted channel set, captures
frames, and emits a machine-readable result suitable for local release checks.

Done when it:

- reports USB identity, firmware hashes, macOS/Python versions, requested and actual channel,
  transfer/frame counts, timeouts, decode failures, and optional independent pcap validation;
- redacts SSIDs, BSSIDs, client addresses, and payloads by default;
- distinguishes `pass`, `fail`, `unsupported`, and `not tested`; and
- has a checked-in schema plus one redacted result from the reference adapter.

### R2. Descriptor discovery and explicit device support

Replace the hard-coded interface 3 and endpoint layout with descriptor inspection and an
explicit supported-device table. Do not infer that every `0e8d:7961` enclosure has the same
layout.

Done when descriptor selection is unit-tested with synthetic layouts, ambiguous layouts fail
closed with useful diagnostics, and each claimed adapter has a dated smoke result.

### R3. Failure handling and soak evidence

Make disconnects, USB stalls, bad firmware responses, partial transfers, Ctrl-C, and retune
failures predictable.

Done when offline fault-injection tests cover cleanup and timeout paths, a repeated retune test
and a multi-hour passive capture complete without leaked interfaces, and drop/error counters
appear in the result. Hot-unplug remains explicitly untested until exercised on hardware.

### R4. Maintainable Python boundary

Replace runtime monkey-patching and heterogeneous dictionaries with typed result objects and a
small transport interface. This unlocks fake-USB tests and useful static type checking.

Done when the public capture path passes an agreed mypy or pyright configuration without broad
module ignores, USB behavior can be tested through a fake transport, and the compatibility
policy for public Python APIs is documented.

## 0.2 — Usable capture source

### R5. Long-lived capture session

Boot once, retain ownership of the initialized device, retune safely, and stream until stopped.
This removes the firmware upload cost from each capture.

Done when startup, stop, retune, and device-loss behavior have explicit states; cancellation
does not corrupt output; and queue depth, dropped frames, USB errors, and current channel are
observable.

### R6. Wireshark extcap

Add an extcap adapter that exposes supported channels and emits radiotap capture data on stdout.
This is the highest-impact end-user integration and should consume the stable session API rather
than duplicate driver logic.

Done when Wireshark can enumerate the adapter, select a supported band/channel, start and stop a
capture, and open the result without malformed packets. The workflow must be hardware-tested on
a clean macOS account and documented with its permissions and firmware requirements.

### R7. Capture format, metadata, and privacy

Move from the minimal pcap writer toward pcapng where it adds useful interface, channel,
firmware, and drop metadata. Add bounded file rotation and explicit payload handling.

Done when Wireshark independently accepts all emitted formats, timestamps and snap length are
specified, rotation cannot silently overwrite unrelated files, and documentation explains that
802.11 captures may contain personal or sensitive data.

## 0.3 — Capture fidelity

### R8. Rich, verified radiotap

Export only metadata the hardware actually supplies: channel/bandwidth, RSSI per available
chain, rate/MCS, aggregation flags, FCS state, and timestamps where trustworthy.

Done when each field has a source citation to mt76 or the hardware message format, golden tests
cover legacy/HT/VHT/HE samples, and Wireshark agrees on a sanitized hardware corpus. Unknown
values must be omitted rather than synthesized.

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

## 0.4 — RF measurement experiments

### R11. Hardware CCA/channel-busy counters

The upstream registers currently read as zero in this userspace bring-up. Determine whether the
missing step is firmware configuration, counter selection, reset/latch behavior, or an actual
firmware limitation.

Done when counters correlate with controlled traffic across repeated trials, including idle and
busy channels, or when a documented negative result explains why they are unavailable. Frame
counts must not be relabeled as channel utilization.

### R12. Noise floor

The current `mt792x_phy_get_nf()` path returns zero. Find and validate a real per-channel or
per-chain noise-floor source, or document that this firmware path does not expose one.

Done when values respond plausibly to controlled RF conditions and are compared with an
independent instrument/reference adapter, or the negative result is recorded. RSSI alone must
not be presented as SNR.

## Later — More hardware, only with evidence

### R13. Additional MT7921U layouts and sibling chips

After descriptor discovery and the smoke schema are stable, qualify rebadged adapters and then
consider MT7922 or other connac2/connac3 devices. Shared upstream code is a starting hypothesis,
not proof of compatibility.

Each newly claimed model needs captured descriptors, an explicit capability record, firmware
provenance, offline fixtures, and tri-band/bandwidth hardware results appropriate to that model.

## Gated optional track — Transmit

Injection remains a research demo: a few spaced probe requests have worked, but sustained
transmit can panic the MCU and the current publication evidence does not re-test injection.
Passive milestones do not depend on this track.

Before any broader transmit API or claim:

- supported frame types, rates, channels, and regulatory assumptions must fail closed;
- tests must run in an isolated RF environment with a watchdog and recovery procedure;
- acknowledgements, firmware failures, queue depth, and rate limiting must be observable; and
- sustained and malformed-input tests must demonstrate bounded behavior.

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
  suite.
- One radio cannot capture multiple channels simultaneously.
- MT7921U 160/320 MHz capture is not promised; firmware/hardware capability is a real boundary.
- CI cannot establish RF correctness because hosted macOS runners do not have the adapter.
- CoreWLAN and NetworkExtension integration are not goals unless they can consume a userspace
  capture source without pretending this device is a system Wi-Fi interface.
