# TODO: current sprint

Sprint started 2026-09-01; refocused 2026-09-03 after 0.2.0. Items come from [ROADMAP.md](ROADMAP.md); each names its roadmap
item. Strike through when merged. Hardware items need the reference adapter attached and at
least two APs on one SSID.

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

- [ ] **R14/R15 hypothesis check, second attempt.** This is the next thing to do and it needs
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
- [ ] **R11/R12 spike.** Write and ship the probe script that reads the CCA/MIB and noise-floor
  paths, whatever it returns. The earlier zero reading has no code in the repo to reproduce it.

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
