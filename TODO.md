# TODO: current sprint

Sprint started 2026-09-01. Items come from [ROADMAP.md](ROADMAP.md); each names its roadmap
item. Strike through when merged. Hardware items need the reference adapter attached and at
least two APs on one SSID.

## Measure before building

- [ ] **R14/R15 hypothesis check.** Force a phone to roam between two APs while the radio is
  locked to the source AP's channel. Record which of these appear on the source channel: BTM
  request, BTM response, deauth/disassoc with reason, last data frame. Record what is missing.
  Result goes in [docs/TESTING.md](docs/TESTING.md) or [NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md).

## Build

- [ ] **R14. Survey command skeleton.** `examples/survey.py --place kitchen --ssid NAME` emits
  one redacted JSON record with per-BSSID RSSI, channel, BSS Load, and k/v/r flags, using the
  parsing `rxd.py` already has. Schema file beside it, offline test on synthetic beacons.
- [ ] **R1 remainder.** Requested-versus-actual channel per step and a `not_tested` status in
  `scripts/hardware_smoke.py`.
- [ ] **R11/R12 spike.** Write and ship the probe script that reads the CCA/MIB and noise-floor
  paths, whatever it returns. The earlier zero reading has no code in the repo to reproduce it.

## Landed this sprint

- ~~R5 drop magnitude measured: median 1 frame lost per retune, max 8, over 30 hops at 100 to
  250 frames per second; `scripts/retune_drops.py` and the `mcu_wait` counters shipped.~~
- ~~R18 decision: 0.1.0 is not released. CHANGELOG entry moved back under Unreleased; tagging
  waits on the publication checklist.~~
- ~~Roadmap regrouped into goal tracks; R14 to R21 added.~~
- ~~NEGATIVE_RESULTS.md created with the two known zeros.~~
- ~~Random-input fuzz test for the descriptor, frame, and IE parsers.~~
- ~~CLAUDE.md for agent sessions.~~
