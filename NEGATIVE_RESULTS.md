# Negative results

Experiments that did not work, recorded so they are not re-run by accident. Check this file
before proposing an experiment. An entry is not permanent: the "not ruled out" list says what
would justify a rerun, and a rerun that succeeds moves the entry to
[docs/TESTING.md](docs/TESTING.md).

Each entry states what was tried, what was observed, what the observation does not rule out,
and where the code that produced it lives. Hardware, firmware, and date come from the
[test bed in docs/TESTING.md](docs/TESTING.md#test-bed) unless stated otherwise.

## Hardware channel-busy (CCA) counters read zero

- **Tried:** reading the upstream MIB channel-busy registers after the passive bring-up, on the
  reference adapter, during initial development before the 2026-08-31 release validation.
- **Observed:** zero on every read.
- **Not ruled out:** counters that need a firmware enable, a different register select, or a
  reset/latch step before they count; a firmware build that does not expose them over USB at
  all. wifikit reports MIB and test-mode experiments on MT7921AU; those are leads, not evidence
  here.
- **Code:** none in the repository. The probe was not shipped, so the observation cannot be
  reproduced from this tree. Roadmap R11 starts by writing and committing that probe.
- **Consequence:** frame counts and BSS Load from beacons are the only utilization signals
  available. They must not be presented as channel busy time.

## Noise floor reads zero

- **Tried:** the `mt792x_phy_get_nf()` path transcribed from mt76, same conditions as above.
- **Observed:** zero.
- **Not ruled out:** a per-chain or per-channel source elsewhere in the firmware's MCU event
  set; a calibration or survey command that must run first; a firmware build that never
  reports it over USB.
- **Code:** none in the repository; same gap as above. Roadmap R12 starts by committing the
  probe.
- **Consequence:** RSSI alone is reported. It must not be presented as SNR.
