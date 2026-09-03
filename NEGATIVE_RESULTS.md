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

## 160 MHz sniffer configuration on MT7921U returns nothing (MT7925U does not share this)

- **Tried:** `set_chan_info` with `CMD_CBW_160MHZ` and `config_sniffer` with `SNIFFER_BW_160`
  on 6 GHz primary channel 53, center 47, on 2026-09-02 with the reference adapter, while an
  AP on that channel was beaconing at 160 MHz.
- **Observed:** zero USB transfers in 6 seconds. The same channel at 20 MHz and 80 MHz (center 55)
  returned about 350 management frames in the same interval.
- **Not ruled out:** a different center-channel encoding for 160 MHz in the sniffer TLV; a
  firmware that accepts the command and never delivers. The README already lists 160 MHz as
  unsupported for this part; upstream advertises it unconditionally for the MT7925
  (`mt7925/init.c:290-292` at `c5a3bd91`), which is why that chip is the port target.
- **Code:** `scripts/width_probe.py`; the run is recorded in [docs/TESTING.md](docs/TESTING.md#channel-width-and-6-ghz-access-points-2026-09-02).
- **Consequence:** data frames from clients on a 160 MHz AP are invisible to the MT7921U, and
  only their 20 MHz management frames can be observed. The MT7925U (Nighthawk A9000) receives
  and decodes them under the same configuration: 1736 frames at 160 MHz in 10 s, including HE
  data from a known transmitter ([docs/TESTING.md](docs/TESTING.md#160-mhz-capture-with-a-controlled-transmitter-same-day)),
  so this entry is a per-chip limit, not a driver one.
