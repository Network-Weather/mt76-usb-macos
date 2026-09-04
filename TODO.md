# TODO: current sprint

Sprint started 2026-09-01; refocused 2026-09-03 after 0.2.0. Items come from [ROADMAP.md](ROADMAP.md); each names its roadmap
item. Strike through when merged. Hardware items need the reference adapter attached and at
least two APs on one SSID.

## Build next (R26, R27)

- ~~R26 C driver MT7925: device table, class-based interface selection, chip profiles, UNI
  commands, connac3 decoder; `c/mt7921_smoke --plan all` passes on the A9000.~~
- ~~R27 EHT radiotap: U-SIG and EHT TLVs in both writers; 973 live EHT frames dissected by
  tshark at 160 MHz; 0.3.0.~~

## Measure before building

- [ ] **R14/R15 hypothesis check, second attempt.** The first attempt (2026-09-02) locked one
  radio to one channel and saw none of five roams of an MLO client; the network's own
  management log did. Both named causes are fixed: ~~Multi-Link element parsing, so every link
  address of the client matches~~ and ~~watching at the access point's own width~~. A second
  radio can now hold the target channel (`scripts/dual_capture.py`). What remains is the run:
  force a roam of a known client with the controller log as the reference, one radio on the
  source channel and one on the target.
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
