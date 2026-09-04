# Negative results

Experiments that did not work, recorded so they are not re-run by accident. Check this file
before proposing an experiment. An entry is not permanent: the "not ruled out" list says what
would justify a rerun, and a rerun that succeeds moves the entry to
[docs/TESTING.md](docs/TESTING.md).

Each entry states what was tried, what was observed, what the observation does not rule out,
and where the code that produced it lives. Hardware, firmware, and date come from the
[test bed in docs/TESTING.md](docs/TESTING.md#test-bed) unless stated otherwise.

## Hardware channel-busy (CCA) counters read zero

- **Tried:** `scripts/mib_survey.py`, reading `MT_MIB_SDR9` (CCA busy), `MT_MIB_SDR36` (TX
  airtime), `MT_MIB_SDR37` (RX airtime) and `MT_WF_RMAC_MIB_AIRTIME14` (OBSS) after passive
  bring-up on the reference MT7921U, 2.4 and 5 GHz, 5 s dwells, 2026-09-03.
- **Observed:** every duration counter reads zero, on every channel, while frames are being
  decoded (180 frames / 393 ms of decoded airtime on 2.4 GHz ch 6, 567 frames / 111 ms on
  5 GHz ch 36). One 5 GHz dwell read `cca_busy = 1729` against a 5 s window, which is 0.03%
  and not credible as occupancy.
- **The block is alive and the arming is not the problem.** `MT_MIB_SCR1` reads `0x00f8c311`
  *before* any write, so `TXDUR_EN | RXDUR_EN` (bits 8 and 9) are already set at bring-up.
  `MT_MIB_SDR3` at `+0x698` (FCS errors) moves freely between reads, so the MIB block is
  mapped, readable, and counting -- it is specifically the duration counters that do not run.
- **The airtime-enable theory was tested and is wrong.** `mt7915_mcu_init_rx_airtime()`
  (mt7915/mcu.c:2330) arms airtime accounting with `MCU_EXT_CMD_RX_AIRTIME_CTRL` (0x4a),
  which no mt7921 driver sends. Sending it here, in both the bitwise-clear and
  feature-enable forms, returns `4a000000 fe000000` -- the firmware's unsupported-command
  reply. The command is refused at dispatch despite having a slot in the image's dispatch
  table, so the capability is absent rather than merely unarmed.
- **Not ruled out:** a per-BSS or per-STA context that monitor mode never creates, which the
  duration counters may be scoped to; a different register select; the counters not being
  wired on this part at all.
- **Code:** `scripts/mib_survey.py --registers`, reproducible from this tree. This supersedes
  the earlier entry, which recorded the same zero readings from an unshipped probe.
- **Consequence, and it has changed:** the registers stay dead, but the same measurement is
  available over the MCU. `MCU_EXT_CMD_GET_MIB_INFO` offset 11 (`MIB_CNT_P_CCA_TIME`) returns
  live primary-channel CCA busy time in microseconds, and `scripts/mib_survey.py` now uses it
  by default. So channel busy time *is* available on this part -- just not through the
  register path this entry is about. See docs/FIRMWARE_RECON.md.

## MCU GET_MIB_INFO returns a zeroed echo, and PHY_STAT_INFO is a stub

- **Tried:** `scripts/mcu_stats.py` plus targeted probes on the reference MT7921U,
  2026-09-03. `MCU_EXT_CMD_GET_MIB_INFO` (0x5a) with the mt7915 and mt7916 counter offsets,
  as SET and as QUERY, in batches and singly; `MCU_EXT_CMD_PHY_STAT_INFO` (0xad) categories
  0-15.
- **Observed, GET_MIB_INFO:** the command dispatches -- an empty payload returns 24 bytes --
  but every reply is `len(request) + 24` bytes of zeros, with the `data` field of each echoed
  entry left at zero. The handler returns a zeroed copy of the request rather than filling in
  counters. Offsets 0, 1 and 6 reply; **offset 87 produces no reply at all**, repeatably,
  which suggests the handler indexes something by `offs` and 87 is out of range on this chip.
- **Observed, PHY_STAT_INFO:** all 16 categories reply with the identical 8-byte prefix
  `ad000000 fe000000` and an uninitialised tail -- the echoed ext_cid then a fixed non-zero
  byte. The five categories named upstream behave no differently from the eleven unnamed
  ones, so the request is not being read. This matches the offline prediction: cid 0xad has
  no dispatch slot in any region of the firmware image.
- **GET_MIB_INFO is dispatched, not refused.** It is the only one of these that does not
  return the 16-byte `{cid, 0xfe}` unsupported-command reply, so its handler genuinely runs
  and returns zeros. The refusal signature is calibrated in both directions: `THERMAL_CTRL`
  (1128 B, 32 C) and `EFUSE_ACCESS` (32 B, valid=1) never produce it, while `SET_RADAR_TH`
  (0x7c) and `SET_FEATURE_CTRL` (0x38), which have no dispatch slot, produce it exactly.
- **Not ruled out:** a request layout for GET_MIB_INFO that differs from
  `struct mt7915_mcu_mib`; an MT7921-specific offset numbering that neither published scheme
  covers -- offsets 0, 1 and 6 reply while 87 produces no reply at all, so some index space is
  valid and the numbering is simply not either published scheme.
- **Code:** `scripts/mcu_stats.py`, reproducible from this tree.

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
