# Changelog

This project follows [Semantic Versioning](https://semver.org/). Hardware claims remain
separately evidence-gated in [docs/TESTING.md](docs/TESTING.md).

## [Unreleased]

### Added

- Experimental MT7925 CSI wire/parser parity in `mt76_csi` and native
  `mt76_csi.h`: version22,64 signed I/Q pairs, strict dimensions/sequence/DMA
  bounds and narrow band0 beacon/20MHz profile. Stale CCK layouts are rejected.
  Python/C session probes demonstrate capture/query coexistence and visible
  event overflow, and reproduce a new ordering requirement: add the transmitter
  filter before the final receiver-count command. Public streaming lifetime
  helpers and longer qualification remain gated; see [CSI API status](docs/CSI_API.md).
- Strict installed Python/native TX-status decoding with MT7925 raw timestamp,
  delay, bandwidth and STBC, format0-only front-time/TX count and explicit tick
  scale availability. Research readers reuse the bounded parser;12 live status
  records decode identically. Missing independent OFDM receipts remain an RF
  qualification limit. No new transmit controls, old-chip timing, synchronized
  clocks or ranging; see [the contract](docs/MEASUREMENTS.md#tx-status-timing-without-new-transmit-controls).
- Opt-in MT7921 Group5 raw in-band/wideband receiver-index decoding in Python/C,
  with complete-group/DMA bounds and explicit absence on MT7925. Python gains a
  matching saved-bit/readback/restore guard; research readers reuse the decoder.
  Live repeats reveal enabled-phase near-silence in both languages despite healthy
  restored reception: dependable streaming remains unqualified, not a passed
  release gate. See [the evidence and limitations](docs/MEASUREMENTS.md#experimental-raw-group5-fields).
- Query-only Python/C thermal measurements: reported signed Celsius on both chips
  and separately labeled MT7925 raw ADC, with bounded matching-reply validation,
  request intervals and unchanged native output on failure. Session probes can
  interleave these reads with counters, RX and retunes. No thermal protection
  overrides or ADC calibration; see [the contract](docs/MEASUREMENTS.md).
- Named raw MCU counter APIs in installed `mt76_measurements` and native
  `mt_counter_*`: four MT7921 and ten MT7925 fields, with distinct wire/hardware/
  accumulator widths, unknown duration conversions, and explicit idle-saturation
  limits. Shared fixtures and strict event bounds/sequence validation prevent
  malformed replies or USB padding from manufacturing measurements. Session probes
  now reuse these APIs and can export redacted named totals. See the
  [measurement contract](docs/MEASUREMENTS.md); current MT7921 weak-RX and remaining
  calibration/soak limits are not treated as passed hardware qualification.
- Experimental Python/C continuous acquisition sessions: one USB owner, bounded
  frame/event queues, frame-preserving MCU waits, serialized commands, explicit
  failure and shutdown states, requested-channel metadata and redacted passive probes.
  Shared routing/lifecycle replay and native thread/memory-sanitizer checks accompany
  the implementation. Fresh bring-up is required; warm adoption and automatic recovery
  are not supported. See [the contract](docs/CONTINUOUS_ACQUISITION.md).
- Native C acquisition parity with the 2026-09-04 Python research: bounded hardware
  timestamp and Group-3/5 export, MT7921 EXT and MT7925 batched UNI MIB queries,
  opt-in reversible Group-5 reporting, controlled OFDM Probe Request transmission
  and attenuation, MT7925 fixed-rate setup/DIS_MAT, and per-chip TX-status decoding.
  `c/mt76_radio_probe` provides a gated, redacted native experiment CLI;
  `scripts/c_radio_pair.py` supervises independent native receiver validation.
  See [the parity contract](docs/C_PARITY.md). These remain instrument primitives,
  not connectivity, calibrated SNR/power, or a general-purpose injector.
- Shared Python/C synthetic-wire tests, injectable MCU/register failure paths,
  CLI refusal tests, and an ASan/UBSan target with 10,000 malformed-input cases.
  C header dependencies now trigger recompilation; source distributions include
  native C sources and their parity fixtures. Embedders must rebuild for the
  expanded C structs; no stable binary ABI is promised.
- Native USB control transfers now honor explicit timeouts through IOKit's
  `DeviceRequestTO`; retries share a monotonic deadline. MCU waits use monotonic
  time, reject truncated reply buffers, and account for connac3 software frames.

- Firmware measurement research from [PR #31](https://github.com/Network-Weather/mt76-usb-macos/pull/31),
  with bounded reproducers, synthetic tests and sanitized hardware evidence.
  This research does not change the production Python/C drivers or passive
  defaults; it is not a further C-parity expansion or a supported measurement API.
- MT7925 beacon-selected CSI with receiver-index pairing and transmitter
  filtering; TMAC/RMAC ICS diagnostics on MT7925 and RMAC ICS on MT7961.
  These expose additional PHY metadata, not calibrated channel matrices or ranging.
  See [CSI](docs/STATION_CSI.md) and [ICS](docs/ICS_CAPTURE.md).
- Firmware-traced histogram, PHY-error, NAV/subchannel, thermal and power-table
  research readouts, including explicit counter-ownership, inactive-width and
  stale-value controls. MT7961 gains research access to normal-mode in-band/
  wideband signal fields and RF-mode CFO/SNR streaming; MT7925 gains raw signed
  PHY comparison inputs with documented 5-GHz freshness limits. See the
  [findings ledger](docs/OVERNIGHT_EXPLORATION.md),
  [signal fields](docs/INBAND_WIDEBAND_SIGNAL.md), and
  [PHY comparison](docs/MT7925_PHY_COMPARISON.md).
- Bounded, independently received transmit experiments for selected HT/VHT/HE
  formats, two streams, STBC, guard intervals, LDPC, HE extended range, HT40,
  and short control/Data/QoS frames. TX-status and cross-radio timing controls
  distinguish packet duration from clock offsets and service delay. Coverage is
  configuration-specific; weak reverse-direction controls, unverified DCM and
  upper106-tone modes, and lack of calibrated power/range remain explicit.
  See [PHY transmit](docs/PHY_TRANSMIT.md) and [timing](docs/CROSS_RADIO_CLOCK.md).
- Read-only loaded-firmware/ROM analysis tools and maintainer-facing provenance
  for command dispatch and register fields. Firmware/ROM bytes and ambient
  identities, packet payloads and raw IQ are not included in the new evidence.

- `rxd.parse_multi_link` decodes the 802.11be Multi-Link element: the MLD address, the Basic
  variant's Common Info subfields, and each Per-STA Profile's link id and address, reassembling
  element (242) and subelement (254) fragments first. `rxd.station_addresses` returns every
  address identifying a frame's transmitter, so a watcher can follow a multi-link client across
  links where each link uses a different address.
- `roam_watch.py --width` captures at 20, 40, 80, or 160 MHz, resolving the center channel from
  the control channel with `mt7921u.center_channel`. It refuses a 2.4 GHz width above 20 MHz, a
  channel outside every block of that width, and a width the attached chip has no evidence for
  (`MAX_WIDTH_MHZ`, 80 on the MT7921U and 160 on the MT7925U).
- `scripts/dual_capture.py` runs two adapters at once, each on its own band, channel, and width,
  merged into one event log on one clock (roadmap R16). Adapters are selected by USB id or by the
  port they are attached to, so two of the same model are separable without a serial number.
  `mt7921u.describe_supported_devices()` is the inventory behind it. The result reports the
  interval when every radio was actually listening, since each boots its own firmware and the
  chips do not take the same time to do it.
- Channel occupancy measurement. `scripts/mib_survey.py` reports primary-channel CCA busy time
  beside the airtime of the frames actually decoded, so the gap between them -- occupancy that
  never becomes a decodable frame -- is visible. Measured 9.48% busy with 149 ms per 8 s window
  unaccounted for by frames on 2.4 GHz channel 6 ([docs/TESTING.md](docs/TESTING.md)).
- `scripts/mcu_stats.py`, which reads the chip's MIB counters over `MCU_EXT_CMD_GET_MIB_INFO` and
  recognises the firmware's unsupported-command reply, so what a firmware implements is asked
  rather than assumed.
- `scripts/fw_triage.py`, offline firmware image triage: per-region classification from the
  declared header flags, RF symbol inventory, the firmware's own source-path map, an EXT command
  dispatch map, and `--extract-regions` for disassembly work.
- [docs/FIRMWARE_RECON.md](docs/FIRMWARE_RECON.md): what the firmware images contain, the
  capability map, and the method for establishing whether a given MCU command is implemented.

- `research/cross_measure.py` runs both adapters at once: two receivers on one channel to check
  they agree, and a bounded transmit burst measured against known airtime. It established that
  CCK injection radiates on 2.4 GHz — 60 of 60 frames decoded by an independent adapter.
  Its initial 5-GHz failure used CCK, not a valid general 5-GHz transmit test;
  subsequent OFDM experiments established 5-GHz transmission, with later RF-performance
  limitations retained ([docs/PHY_TRANSMIT.md](docs/PHY_TRANSMIT.md)).
- MT7925 UNI MIB characterization tools identify delivered and detected receive counts,
  CCK/OFDM-family receive duration, primary CCA and ED-active time through batched counter queries,
  controlled Wi-Fi perturbation and an independent MT7921 reference. The full counter map,
  confidence boundaries and wide-channel scope result are in
  [docs/MT7925_MIB.md](docs/MT7925_MIB.md). A single request does not establish
  simultaneous hardware latching.

### Changed

- `scripts/mib_survey.py` takes its counters from the MCU. The MIB registers read zero on this
  part however they are armed; `--registers` still reads them so that result stays reproducible
  ([NEGATIVE_RESULTS.md](NEGATIVE_RESULTS.md)).

### Documentation

- Maintainer-facing reproduction of a pinned MT7925 firmware defect: UNI23
  diagnostic tag3 retains command objects; four reports can stall subsequent
  commands until reload. The guarded research reproducer is not a polling API,
  and no firmware fix is claimed. Link-quality busy percentage and HWCFG readout
  also have traced unsupported/synthesized paths; zero/ACK is not measurement
  availability. See [diagnostic statistics](docs/MT7925_DIAGNOSTIC_STATS.md) and
  [UNI dispatch](docs/MT7925_UNI_DISPATCH.md).
- Source/ROM-backed MT7925 counter naming correction: offset17 is primary CCA,
  offset19 is CCA+NAV+TX, and offset7 counts idle slots rather than microseconds.
  Overlapping counters, width-inapplicable fields and read-clear ownership must
  not be interpreted as additive occupancy or non-Wi-Fi interference.
- MT7921U regression on the 0.3.0 code with both adapters attached: both tools refuse an ambiguous
  open, both 43-channel sweeps pass on the ALFA, thermal and efuse answer, pcaps dissect
  ([docs/TESTING.md](docs/TESTING.md)).

### Fixed

- UNI MIB parsers no longer rescan bytes inside complete counter entries as TLV
  headers. Values such as `8` could manufacture a false offset0 match, rejecting
  valid batches or misleading loose research readers; those readers now reuse
  the installed parser. Shared Python/C regression fixtures cover this case.
- Offline `scripts/fw_triage.py --command-map` now reads candidate records as
  CID-then-handler and includes the final complete record. The old reversed order
  associated handlers with the next CID. Candidate matches or absence no longer
  claim dispatch reachability or implemented/unsupported features.
- The Python pcap writer emits the radiotap VHT field at its full 12 bytes. It was writing 10,
  omitting `partial_aid`, so `it_len` under-counted what the present bitmap claimed and Wireshark
  rejected every VHT frame as malformed. User 0's coding bit now reports LDPC, matching the C
  writer. Measured on the MT7921U at 80 MHz: 19 of 19 VHT frames malformed before, 0 of 14 after
  ([docs/TESTING.md](docs/TESTING.md#vht-radiotap-length-2026-09-03)).
- C decoders convert RCPI to dBm as `rcpi / 2 - 110` with integer division, matching upstream
  `to_rssi()` and the Python decoders; the previous `(rcpi - 220) / 2` truncated toward zero and
  read odd RCPI values 1 dB high.

## [0.3.0] - 2026-09-03

The pure C driver gains MT7925U support, and both pcap writers emit radiotap EHT and U-SIG fields
so Wireshark shows rate, MCS, streams, and bandwidth for Wi-Fi 7 frames. Hardware claims are
evidence-gated in [docs/TESTING.md](docs/TESTING.md).

### Added

- C driver MT7925U support (roadmap R26): `c/mt7921_chip.c` holds the supported USB-id table and a
  per-chip profile (MCU geometry, WFSYS reset descriptor, firmware files and pins); the USB layer
  picks the interface by class `ff/ff/ff` and assigns endpoint roles positionally; the MCU layer
  builds TXDs and parses replies from the profile and encodes the MT7925 capability, efuse, and
  RX-filter commands as UNI TLVs; `mt7921_tune` tunes either chip; `c/mt7921_rxd_connac3.c`
  decodes the connac3 descriptor with EHT rates; `mt7921_smoke` reports `device.chip` and takes
  `--usb-id`. The Nighthawk A9000 passes the 43-channel sweep ([docs/TESTING.md](docs/TESTING.md)).
- Radiotap EHT and U-SIG fields (roadmap R27) in `examples/sniff_to_pcap.py` and the C pcap
  writer: EHT frames carry the TLV present bit with a U-SIG item (bandwidth) and an EHT item (GI,
  RU/MRU size, one user's MCS, NSS, and coding), the layout radiotap.org defines and Wireshark 4.6
  reads back as an 802.11be frame with its data rate. Live: 973 EHT frames in 30 s on a 160 MHz
  6 GHz channel with the Python writer and 336 in 10 s with the C writer, all dissected, zero
  malformed ([docs/TESTING.md](docs/TESTING.md)).
- `c/mt7921_smoke --channel BAND:CTRL[:CENTER[:WIDTH]]` captures one channel at 20/40/80/160 MHz
  instead of a plan.
- `tests/test_release_docs.py`: a version bump without a matching CHANGELOG section, README release
  line, PUBLISHING mention, and C version string fails CI. `tests/test_pcap.py` round-trips a
  synthetic EHT pcap through tshark when it is installed.

### Changed

- `c/mt7921_smoke` opens the adapter before loading firmware, reads `$MT76_FW_DIR` (then
  `$MT7921_FW_DIR`), and refuses `--inject`, `--temp`, and `--read-efuse` on the MT7925.

## [0.2.0] - 2026-09-03

MT7925U (Wi-Fi 7, 160 MHz) support on the Netgear Nighthawk A9000, and descriptor-driven device
selection for every supported adapter. Hardware claims are evidence-gated in
[docs/TESTING.md](docs/TESTING.md).

### Added

- Descriptor-driven device selection (roadmap R2): `SUPPORTED_DEVICES` lists the MT7921U and
  MT7925U USB ids (not the MT7927's, whose firmware is not fetched), and `open()` picks the Wi-Fi interface by class `ff/ff/ff` and endpoint
  shape, assigning endpoint roles positionally as `mt76u_set_endpoints` does. Layouts that do
  not match fail closed with a diagnostic. `MT76_USB_ID` or `usb_id=` selects one adapter when
  several are attached.
- `scripts/usb_descriptors.py`: redacted dump of each supported adapter's interfaces and
  endpoints, the roles the driver resolves, and with `--chip-id` the identity registers.
- Firmware files and their pinned SHA-256s live in `mt7921u.FIRMWARE_FILES`, loaded through
  `load_firmware(chip)`; `setup.sh` also fetches the MT7925 blobs. `MT76_FW_DIR` replaces
  `MT7921_FW_DIR`, which still works.
- First MT7925 hardware record: the Netgear Nighthawk A9000 enumerates, resolves to interface 0,
  and reads chip id `0x7925` ([docs/TESTING.md](docs/TESTING.md)).
- `mt7925u.py`: `Mt7925uDevice`, a subclass of the MT7921 device with the connac3 WFSYS reset
  descriptor, the 44-byte MCU reply header, MCU TXD without `LONG_FORMAT`, the per-command UNI
  ack option, and UNI `CHIP_CONFIG` capability and `EFUSE_CTRL` buffer-mode commands. Boots
  the MT7925 firmware on the A9000 to `N9_RDY` and parses its capability element list
  ([docs/TESTING.md](docs/TESTING.md)). `open_device()` picks the class from the USB id.
- `scripts/firmware_boot.py`: boot firmware on whichever supported adapter is attached and
  report chip id, firmware hashes, and capabilities as redacted JSON.
- The MCU reply-header geometry, TXD word 1, UNI option, and WFSYS reset registers are class
  attributes with the MT7921 values as defaults; `tests/golden_mt7921_frames.json` freezes every
  MT7921 command's on-wire bytes so those seams cannot move them.
- `tune(band, control, center=None, width_mhz=20)` on both device classes: the MT7921 sends
  `CHANNEL_SWITCH` then the sniffer CONFIG TLV, the MT7925 sends the TLV alone (it has no
  channel-switch command). Every example and script tunes through it and opens the adapter
  through `open_device()`, so they run unchanged on either chip once a decoder exists for it.
- MT7925 monitor mode: UNI `BAND_CONFIG` RX filter and `set_monitor_mode()`. The A9000 receives
  frames on 2.4, 5, and 6 GHz ([docs/TESTING.md](docs/TESTING.md)).
- `scripts/firmware_boot.py --rx SECONDS --channel BAND:CH[:CENTER[:WIDTH]]` counts receive
  transfers by RXD packet type without needing a descriptor decoder.

- `rxd_connac3.py`: the connac3 (MT7925) RX descriptor decoder, returning the same dict as
  `rxd.decode` so the 802.11 parsers, pcap writer, and scripts are chip-agnostic. 32-byte fixed
  header, group bits at RXD1 16..20, FCS error in RXD3, 16-byte groups with the 96-byte C-RXV
  stepped over only inside group 3, rate and RCPI from P-RXV words 0, 2, and 3. Synthetic
  fixtures cover every group combination; the fuzz test includes it. `decoder_for(dev)` picks
  the decoder from the device class. On the A9000: 607 of 607 frames dissected by tshark with
  zero malformed ([docs/TESTING.md](docs/TESTING.md)).
- `rxd.py` rate tables gain EHT: MCS 12 and 13 (4096-QAM) for the EHT modes only, and
  preamble entries; 320 MHz is decoded as a width but has no rate.

### Changed

- `scripts/retune_drops.py` reports one `tune_ms` per retune instead of `chan_switch_ms` and
  `sniffer_cfg_ms`, because a retune is one command on the MT7925.

### Fixed

- `chip_id()` returned the high half of `MT_HW_CHIPID`; the chip number is the low half.

## [0.1.0] - 2026-09-02

First release: a research-grade passive capture instrument for the MT7921U on macOS, with the
MT7925U port planned. Hardware claims are evidence-gated in [docs/TESTING.md](docs/TESTING.md).

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
- Reordered Track C around a language-neutral contract: R20 recorded-USB corpus first, R19 reframed
  as the protocol document, new R23 conformance suite; other-language implementations live in
  sibling repositories validated against them.
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

[Unreleased]: https://github.com/Network-Weather/mt76-usb-macos/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Network-Weather/mt76-usb-macos/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Network-Weather/mt76-usb-macos/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Network-Weather/mt76-usb-macos/releases/tag/v0.1.0
