# Changelog

This project follows [Semantic Versioning](https://semver.org/). Hardware claims remain
separately evidence-gated in [docs/TESTING.md](docs/TESTING.md).

## [Unreleased]

Nothing below has been released. The first tag will be `0.1.0`, the version already declared in
`pyproject.toml` and `mt7921u.__version__`; the gate for tagging it is roadmap item R18 and the
checklist in [docs/PUBLISHING.md](docs/PUBLISHING.md).

### Added

- Userspace firmware boot, MCU commands, channel control, monitor/sniffer setup, and passive
  receive for the exact MediaTek `0e8d:7961` composite USB layout on macOS.
- 20 MHz passive capture across 2.4, 5, and 6 GHz on the attached ALFA AWUS036AXML reference
  adapter, with radiotap pcap output for Wireshark.
- RX descriptor, 802.11 management, PHY-rate, and aggregation parsing.
- A redacted JSON hardware smoke test covering all 43 default tri-band scan channels.
- 54 offline tests, Ruff formatting/security linting, shell checks, macOS-only CI, and PEP 517
  source/wheel construction.
- Pinned linux-firmware provenance and SHA-256 verification, security/contribution policies,
  related-project comparison, integration analysis, and an acceptance-criteria roadmap.
- `mcu_wait` counts the 802.11 frames, stale MCU events, and status packets it discards while
  waiting for a reply, on the device object, so callers can attribute losses to a command.
- `scripts/retune_drops.py`: measures frames lost per retune on the two busiest channels and
  reports the distribution as counts-only JSON.
- `scripts/roam_watch.py`: lists the BSSIDs of one SSID with their channels and 802.11k/v/r
  flags, or locks to one channel and prints classified roaming and steering events.

### Experimental

- Low-rate Probe Request injection is included for driver research but was not requalified for
  this release. Only 60 frames at 50 ms spacing have been sent here, with the chip alive after;
  sustained or high-rate transmit is untested.

### Known limitations

- Only USB `0e8d:7961` with Wi-Fi interface 3 is supported.
- The project is a passive userspace capture source, not a macOS network interface.
- 40/80 MHz code paths, injection, hot-unplug, sleep/wake, multi-adapter use, long soaks, CCA,
  and noise floor are not release-qualified. See the complete
  [evidence and untested list](docs/TESTING.md#explicitly-untested-or-unsupported).

### Documentation

- Renamed the repository and distribution from mt7921u-macos to mt76-usb-macos, after the upstream
  `mt76-usb` module it transcribes, with a per-chip support matrix in the README. The Python modules
  keep their kernel-module names (`mt7921u`, and `mt7925u` when it lands).
- Expanded provenance to distinguish the pinned openwrt/mt76 transcription source from the
  canonical in-tree Linux integration, retain exact upstream copyright notices, pin peer
  comparison revisions, and catalogue selected downstream/backport projects.
- Recorded independently testable lessons from mt76, wifikit, and wifit3 without treating peer
  claims as local evidence or crossing their license boundaries.
- Regrouped the roadmap into goal tracks (roaming and steering instrument, community capture source,
  researcher reference), keeping existing item numbers and adding R14 to R21. Added TODO.md for
  the current sprint, NEGATIVE_RESULTS.md for the channel-busy and noise-floor zeros, and
  CLAUDE.md for agent sessions.
- Corrected the copyright holder in the license, citation metadata, and source headers to
  Primatech Paper Co LLC d/b/a Network Weather.
- Recorded the MT7925U port plan in docs/MT7925.md with every claim checked against the pinned
  mt76 source, and the 2026-09-02 channel-width, 160 MHz, and single-radio roaming evidence in
  docs/TESTING.md and NEGATIVE_RESULTS.md. Roadmap R22 added; R15 and R16 cite the evidence.

### Tests

- Random-input fuzz test asserting the descriptor, frame, and IE parsers never raise.
- Offline test for the `mcu_wait` discard counters through a queued fake RX endpoint.
- Offline tests for the roam watcher's BSSID bookkeeping: channel from the frame, not the sweep
  target; DS Parameter Set over descriptor; strongest RSSI; k/v/r flags.

[Unreleased]: https://github.com/Network-Weather/mt76-usb-macos/commits/main
