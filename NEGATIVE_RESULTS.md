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

## The IPI histogram is not at the mt7915 register address on MT7921

- **Tried:** `research/ipi_probe.py` on the reference MT7921U, 5 GHz channel 36, 2026-09-03.
  Read-only survey of `MT_WF_IRPI_BASE` (`0x83000000`), `MT_WF_PHY_BASE` (`0x83080000`) and
  1024 words at `MT_WF_IRPI_NSS(0, 0)` (`0x83006000`), plus both chains' 11 bins.
- **Observed:** the address space is reachable -- 64 words at each base read without error,
  48 and 12 distinct values respectively -- so the USB register window does reach
  `0x83xxxxxx`. The IRPI window itself reads a single value, `0x00000000`, across all 1024
  words, and every bin on both chains is zero. `0x83000000`'s live words are dominated by
  `0x35353535` (ASCII `5555`), which is not register-shaped; `0x83080000` is
  (`0x1000`, `0x3800`, `0xfffcfffc`).
- **Not ruled out:** the histogram living at a different offset on this part; the sampler
  being off, since `RDD_IPI_HIST_CTRL` reports all-zero bins *and* a stopped free-running
  counter over the MCU, which is consistent with nothing sampling anywhere rather than with
  the wrong address; a write to `MT_WF_PHY_RX_CTRL1_IPI_EN` starting it.
- **Code:** `research/ipi_probe.py`, reproducible from this tree; exits 2 when no histogram
  is found.

## The MT7925 answers no EXT command; its counters are behind UNI, and unidentified

- **Tried:** `research/mib_offset_sweep.py --max 32` and `research/mcu_command_probe.py`
  against the reference MT7925U (Netgear A9000, `0846:9072`), 2026-09-03, then the UNI form of
  the same query, 2026-09-04.
- **Observed, EXT:** every `GET_MIB_INFO` offset from 0 to 31 returns no reply, and the command
  probe then failed to calibrate and refused to report -- all four of its controls went silent,
  including `THERMAL_CTRL` and `EFUSE_ACCESS`, which work on the MT7921. The MT7925 answers
  **no** EXT command tried.
- **Why:** connac3 does not use the EXT command space. `mt7925u.py` drives capability and efuse
  through UNI commands with tag/length TLVs. Asking it EXT commands is asking in the wrong
  language, and the EXT silence says nothing about whether the counters exist.
- **Observed, UNI:** `MCU_UNI_CMD_GET_MIB_INFO` (0x22), framed as `mt7996_mcu_get_chan_mib_info`
  does -- a `{u8 band, u8 rsv[3]}` header then `{le16 tag, le16 len, le32 offs}` entries -- **is
  answered**.

  ```bash
  MT76_USB_ID=0846:9072 ./.venv/bin/python research/uni_mib_probe.py --max 48
  ```

  Acceptance: an offset counts as present only if the firmware echoes it back in the reply, and
  as running only if it advances between two reads bracketing a *timed* window. The probe
  discovers which offsets answer before opening that window, because an offset that never
  replies costs a full timeout and a baseline taken during discovery is separated from its
  second sample by the whole sweep.

  On 2.4 GHz channel 6 over a 6.3 s measured span, 40 of 48 offsets echo and 11 advance.
  **Offset 18 advances at exactly 100.00% of the interval**, which makes it a free-running
  microsecond clock -- and that in turn establishes the unit for the rest, since a counter
  ticking 1:1 with wall clock has to be microseconds. Against it, offsets 17, 19 and 20 each
  ran at 36-37% of the window and offset 12 at 7.7%; offset 7 advances by exactly 65535, the
  same signature the MT7921's `CHANNEL_IDLE` shows.
- **Not identified.** Which counter is which has *not* been established. The MT7921's names were
  earned by behaviour across channels and bandwidths and then corroborated against a vendor enum
  whose gaps matched the hardware's; none of that has been done here, and the mt7996 UNI
  offsets (`OBSS_AIRTIME` 26, `NON_WIFI_TIME` 27, `TX_TIME` 28, `RX_TIME` 29) echo back but read
  zero, so they are not this chip's numbering either.
- **Not ruled out:** that the zero-reading offsets need an enable. `UNI_VOW_RX_AT_AIRTIME_EN`
  exists in the same UNI space and has not been tried.
- **Consequence:** occupancy is an MT7921U capability *in this tree* because that is the chip
  whose counters are identified. It is not a chip limitation, and `mib_survey.py` reporting
  `null` on an MT7925 reflects missing identification rather than missing hardware.
- **Code:** `research/mib_offset_sweep.py` and `research/mcu_command_probe.py` for the EXT
  silence, `research/uni_mib_probe.py` for the UNI result. Each is runnable from this tree.

## The IPI sampler does not start, by four routes

- **Tried, all on the reference MT7921U:** `RDD_IPI_HIST_CTRL` (0xa3) `CR_INIT`,
  `HIST_RESET` and `SET_IDLE_PWR`; `RDD_ON_OFF_CTRL` (0x3a) `RDD_START` on a DFS and a non-DFS
  channel; `EDCCA_CTRL` (0x70) enable; and writing mt7915's `MT_WF_PHY_RX_CTRL1_IPI_EN` field
  plus the `RXTD12` clear bits directly, 2026-09-03 and 09-04.
- **Observed:** the MCU command is accepted and, under the QUERY bit, returns exactly the
  documented 56-byte event with the index echoed -- so transport and reply layout are solved.
  Every bin reads zero, and so does the free-running counter that should tick once per 8 µs
  regardless of what the radio hears. `RDD_ON_OFF_CTRL` is silent, `EDCCA_CTRL` is refused.
- **The PHY register writes take.** `0x83082004` read `0x00000000` and read back `0x00000005`
  after the write; `0x83088230` read `0x8000c2c2` and read back `0xa004c2c2`, both requested
  bits set. So that block is writable as well as readable, and the histogram still did not
  start. Neither mt7915's IRPI layout (`0x83006000`) nor mt7916's (`0x83001000`) accumulated,
  and of 2048 words swept across `0x83000000`-`0x83010000` only four grew, all at rates that
  look like clocks rather than bin counts.
- **Note what that write was:** mt7921's PHY register map is not published, so setting a field
  at mt7915's offset is a guess about what lives there. It is recorded as an attempt with an
  unknown effect, not as a correct enable that failed.
- **Not ruled out:** an mt7921-specific PHY offset for the enable; the sampler requiring RF-test
  mode, which `WIFI_SPECTRUM` also appears to need; a firmware build without it.
- **Code:** `research/ipi_hist_cmd.py`, `research/ipi_probe.py`.


## Injection does not radiate on 5 GHz

- **Tried:** `research/cross_measure.py --band 5GHz --channel 149 --transmit 300
  --acknowledge-experimental-transmit`, twice, 2026-09-03. The MT7921U injected spaced Probe
  Requests from a synthetic source address while the MT7925U decoded on the same channel.
- **Observed:** every frame accepted by the USB endpoint, the chip alive afterwards, and **zero**
  decoded by the observing radio. The same procedure on 2.4 GHz channel 1 decodes 60 of 60, so
  the receiver and the address matching both work.
- **Consistent with the C driver**, which fails closed and submits zero frames above 2.4 GHz.
  This is that restriction observed from the air rather than read from the code.
- **Not ruled out:** a 5 GHz TX path needing rate or power configuration the injector does not
  set; regulatory gating in firmware. Nothing here distinguishes those.
- **Code:** `research/cross_measure.py`.

## A transmit burst does not separate offset 14 from offset 11

- **Tried:** `research/cross_measure.py --transmit` on 2.4 GHz channel 1 with 3, 60 and 300
  frames, reading `P_CCA_TIME` and `CCA_NAV_TX_TIME` around each burst, against a zero-transmit
  control of the same shape from `scripts/mib_survey.py`, 2026-09-03 and 09-04.
- **Observed:** the difference between the two counters grows with the burst *window*, not with
  the number of frames. The control over a 10 s dwell on the same channel gives 970,366 µs of
  difference, 9.7% of the dwell — a higher rate than the 60-frame burst's 8.9%.
- **What was wrong with the reasoning:** comparing 3 frames against 300 changed the frame count
  and the burst duration together, the window growing 63× between them. The resulting "98× for
  100× the frames" measured duration and attributed it to frames, and a per-frame figure that
  agreed to 1.7% across those two points disagrees by 4× once a third spacing is tried.
- **Not ruled out:** that `CCA_NAV_TX_TIME` includes a TX term, which its name says. The
  experiment cannot see it because the NAV component — other stations' duration fields — is far
  larger on a busy channel. A quiet channel where NAV is near zero would isolate it; channel 1
  is not that channel.
- **Code:** `research/cross_measure.py`, `scripts/mib_survey.py` for the control.
