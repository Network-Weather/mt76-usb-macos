# Changelog

This project follows [Semantic Versioning](https://semver.org/). Hardware claims remain
separately evidence-gated in [docs/TESTING.md](docs/TESTING.md).

## [0.1.0] — 2026-08-31

Initial research release.

### Added

- Userspace firmware boot, MCU commands, channel control, monitor/sniffer setup, and passive
  receive for the exact MediaTek `0e8d:7961` composite USB layout on macOS.
- 20 MHz passive capture across 2.4, 5, and 6 GHz on the attached ALFA AWUS036AXML reference
  adapter, with radiotap pcap output for Wireshark.
- RX descriptor, 802.11 management, PHY-rate, and aggregation parsing.
- A redacted JSON hardware smoke test covering all 43 default tri-band scan channels.
- 44 offline tests, Ruff formatting/security linting, shell checks, macOS-only CI, and PEP 517
  source/wheel construction.
- Pinned linux-firmware provenance and SHA-256 verification, security/contribution policies,
  related-project comparison, integration analysis, and an acceptance-criteria roadmap.

### Experimental

- Low-rate Probe Request injection is included for driver research but was not requalified for
  this release. Sustained transmit can panic the MCU.

### Known limitations

- Only USB `0e8d:7961` with Wi-Fi interface 3 is supported.
- The project is a passive userspace capture source, not a macOS network interface.
- 40/80 MHz code paths, injection, hot-unplug, sleep/wake, multi-adapter use, long soaks, CCA,
  and noise floor are not release-qualified. See the complete
  [evidence and untested list](docs/TESTING.md#explicitly-untested-or-unsupported).

[0.1.0]: https://github.com/Network-Weather/mt7921u-macos/releases/tag/v0.1.0
