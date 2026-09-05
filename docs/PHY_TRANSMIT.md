# Fixed PHY-rate transmit exploration

Measured 2026-09-04 Pacific (2026-09-05 UTC), macOS 26.6.1, Python 3.14.7,
MT7961 ALFA `0e8d:7961` and MT7925 A9000 `0846:9072`. Research-only additions;
neither production injection APIs nor C parity claims change. Firmware hashes and
redacted observations are in [evidence](../research/evidence/phy-transmit-2026-09-04.json).

## New on-air capabilities

The second dongle matched each received probe's complete bytes, with valid FCS,
and reported its PHY independently. Channel 36, 20 MHz, one stream:

| Transmitter / variant | OFDM before | HT MCS 0 | HT MCS 7 | VHT MCS 0 | HE-SU MCS 0 | OFDM after |
|---|---:|---:|---:|---:|---:|---:|
| MT7925 initial, 5 per phase | 5 | 5 | 5 | 5 | 0 | 5 |
| MT7961, 10 per phase | 10 | 10 | 10 | 9 | 10 | 10 |
| MT7925 explicit fixed-20-MHz flag, 10 per phase | 9 | 10 | 10 | 10 | 0 | 10 |

Receiver rates: OFDM 6, HT0/VHT0 6.5, HT7 65, HE0 8.6 Mbps. These are
descriptor-derived PHY rates, not throughput. All observed candidate packets used
one stream, 20 MHz, GI code 0, and no LDPC. No claim about ACK, association,
aggregation, sustained operation, interoperability of these management frames,
other widths, or more distant links.

MT7925 reported successful no-ACK TX status for the initial HE packets even though
MT7961 decoded none. Setting connac3 `MT_TXD6_FIXED_BW` did not resolve this.
This is **no independent decode**, not proof that HE cannot transmit or that no
energy was emitted. PHY construction, receiver acceptance, and hidden table fields
remain candidates. Both radios answered afterward and transmitter firmware reload
succeeded on all three runs.

## Protocol pointers and reproduction

### 2.4GHz follow-up: usable forward direction, reverse still unverified

`--suite lowband --channel 1 --per-phase 4` uses six bounded phases at20MHz:
OFDM6, HT0/1SS, HT8/2SS, HE0/1SS, HE0/2SS, OFDM6. It excludes VHT and all
wider bandwidths; the existing60-packet ceiling,50ms spacing, no-ACK policy,
fresh private nonce and independent whole-frame/FCS/PHY checks remain. Only
channels1/6/11 accept this suite and the later CCK/preamble suites; the other
suites still require36/149.

Two fresh MT7925-transmitter runs at12:00:43 and12:01:34 UTC on2026-09-05
each submitted24 frames. The MT7961 receiver independently reported:

| Setting | Run1 exact receipts | Run2 exact receipts | Verified receive PHY |
|---|---:|---:|---|
| OFDM before | 4/4 | 4/4 | OFDM6,1SS,20MHz |
| HT0 | 4/4 | 4/4 | HT MCS0,1SS,20MHz |
| HT8 | 4/4 | 4/4 | HT MCS8,2SS,20MHz |
| HE0,1SS | 1/4 | 0/4 | One HE-SU MCS0,1SS receipt only |
| HE0,2SS | 4/4 | 4/4 | HE-SU MCS0,2SS,20MHz |
| OFDM after | 4/4 | 4/4 | OFDM6,1SS,20MHz |

This establishes a reproducible **2.4GHz forward probing path** for OFDM,
HT1/2SS and HE2SS. HE1SS remains unreliable. Raw receiver signal values were
roughly−94..−92, so these successes do not establish restored RF power or a
healthy long-range link. No throughput/interoperability claim is made.

A reciprocal MT7961-transmitter run at12:01:06 UTC submitted24 frames but the
MT7925 independently received none. Both radios remained alive after all three
runs, and each transmitter's normal firmware reload succeeded. The reverse RF
problem remains unresolved; no additional power, antenna, factory calibration
or nonvolatile writes were attempted. The receiver stayed in normal monitor
mode; the cleanup evidence specifically covers the transmitter reload, not a
claimed second receiver reload inside this older probe.
[Lowband evidence](../research/evidence/lowband-transmit-2026-09-05.json).

### CCK rates and selectable preambles

`--suite cck` and `--suite preamble` use only channels1/6/11,20MHz, with the
same60-frame limit,50ms spacing, synthetic no-ACK probes, nonce matching and
independent good-FCS receive evidence. Protocol values come from pinned mt76
`mt76.h` `CCK_RATE`, `mac80211.c` `mt76_rates` / `mt76_get_rate`: mode0,
indices0/1/2/3 mean1/2/5.5/11Mbps; bit2 selects short preamble. The preamble
suite compares codes1/5 and3/7. No short-preamble1Mbps variant is attempted.

MT7925 forward TX, four frames per phase on2026-09-05:

| Run | OFDM before | Four CCK phases | OFDM after |
|---|---:|---|---:|
| ch1 CCK rates | 4/4 | 1/2/5.5/11Mbps long:4/4 each | 0/4 |
| ch1 preambles | 4/4 | 2-long/2-short/11-long/11-short:4/4 each | 1/4 |
| ch6 preambles | 0/4 | 2-long/2-short/11-long/11-short:4/4 each | 0/4 |

Receiver mode was CCK and rate/index matched each requested value, including
raw indices5/7 for short preambles. These are independently received PHY
controls, not inferred from successful TX status. All three fresh-nonce runs
submitted24 frames and passed both alive checks and transmitter normal reload.
No control used a power change. The weak/missing OFDM controls and roughly
−101..−100 raw signal on ch1 mean **RF recovery and general mode-switch health
are not established**. Successful CCK reception does not qualify throughput,
range, or calibrated airtime; the existing analytical airtime estimate still
uses a fixed long-CCK preamble and is not a preamble-duration measurement.

A source-defined CCK-only hypothesis for the failed reverse direction was also
tested: MT7961 submitted24 ch1 frames with OFDM controls and1/2/5.5/11Mbps CCK,
but MT7925 independently received none. Both alive checks and transmitter reload
passed. CCK did not restore the reverse path; no further power/calibration sweep
was performed.

[Sanitized CCK evidence](../research/evidence/cck-transmit-2026-09-05.json).

### Two-stream follow-up (2026-09-05 UTC)

**MT7925 two-stream HT, VHT and HE-SU reached the other dongle**, with exact
complete-frame matches, valid FCS and independent PHY metadata on channel 36,
20 MHz. The first run received 6/6 of each; a second run used a fresh per-run
vendor-IE nonce and received 4/4 of each, ruling out old buffered probes matching.

| Requested setting | Rate code | Independent MT7961 PHY report |
|---|---|---|
| HT MCS 8, 2 streams | 0x488 | HT, MCS 8, NSS 2, 20 MHz, GI 0, no LDPC |
| VHT MCS 0, 2 streams | 0x500 | VHT, MCS 0, NSS 2, 20 MHz, GI 0, no LDPC |
| HE-SU MCS 0, 2 streams | 0x600 | HE-SU, MCS 0, NSS 2, 20 MHz, GI 0, no LDPC |

Source: `mt7915_mac_write_txwi_tm` at c5a3bd91 derives HT NSS from MCS/8 and
encodes NSS-1 in the rate field; the shared connac headers define the bit ranges.
The MT7925 fixed-rate-table mechanism is unchanged. Run `phy_tx_probe.py` with
`--suite streams`; the six phases and 60-packet ceiling remain bounded.

**Controls are currently poor, so this is capability evidence, not a link-quality
or throughput result.** The fresh-nonce run received only 1/4 OFDM before, 1/4
HT0 and 0/4 OFDM after. Its reported signal values were around -103 to -98.5,
far weaker than earlier experiments (units remain device-reported, uncalibrated).
Both directions' one-stream controls failed on channel 149 in this follow-up.
MT7961 TX was not independently received in the initial and repeated stream runs.
MT7925 still received 173–288 ambient frames during the later MT7961 TX runs, so
its receiver was not simply silent. No ambient frames/identifiers were retained.

An explicit MT7961 test-mode exit and a forced whole-WFSYS reset were tried;
both reloaded successfully, but neither restored the reverse-direction control.
The forced reset changed firmware state from 3 to 0 before successful reload.
The cause of this RF-performance change is unresolved; **alive/reload success
does not prove restored RF performance**. Wider-band tests are deferred while
the baseline link is unreliable. No physical power-cycle or antenna adjustment
was performed. [Sanitized runs](../research/evidence/spatial-stream-transmit-2026-09-05.json).

### Spatial-path and firmware-table controls (2026-09-05 UTC)

`--suite spatial --transmitter mt7961` changes only Connac2 TXD word 7 bits
15:11, leaving the existing word-6 selector bit 10 zero. Five OFDM6 phases use
SPE indices `0,1,0,24,0`; power, 20-MHz channel 36, no-ACK and the private
per-run frame nonce are unchanged. The vendor gen4m source at `8fddb9d7`
(`wlanAntPathFavorSelect`, `wlan_def.h`, `nic_connac2x_tx.h`) names indices 0/1
as WF0/WF1 and 24 as duplicated one-stream selection. Upstream mt7915 test
descriptors likewise set the DW7 index without setting DW6 bit 10. These names
are source intent, not independently verified physical antenna routing here.

All 30 submissions produced TX statuses (raw power 44, OFDM6, no ACK-error bits),
but **zero exact frames arrived in any phase**. MT7925 received 202 unrelated
frames during this run; those frames were discarded, not saved. Both alive
checks and transmitter reload passed. Spatial index changes did not restore
the reverse-direction baseline; a silent RF path and ineffective descriptor
selection remain distinguishable possibilities, not resolved causes.

A separate **no-transmission** MT7925 test tried the upstream `UNI 0x40` fixed
rate-table command: tag 0, length 16, slot 18, OFDM6, WTBL selection, no
LDPC/beamforming/dynamic BW. Both zero GI/LTF and exact upstream GI/LTF=1/1
returned command-result **0xc0000001** with matched sequence. This is a
rejected request, not proof the entire command family is absent. The working
direct ITDR table-programming route is unchanged. Each trial reloaded normally.

[Sanitized evidence](../research/evidence/spatial-path-controls-2026-09-05.json)
contains all three trials. No power increase, calibration writes, association,
profile writes or beamforming/sounding transmission occurred.

### Initial one-stream method

All rate/descriptor facts come from mt76 baseline `c5a3bd91`:

- `mt76.h`, `enum mt76_phy_type`: HT=2, VHT=4, HE-SU=8.
- `mt76_connac2_mac.h` / `mt76_connac3_mac.h`: rate mode bits 9:6,
  index bits 5:0; tested codes `0x80`, `0x87`, `0x100`, `0x200`.
- Connac2 puts the code directly in TXD word 6 bits 29:16.
- Connac3 puts **table slot 18**, not the PHY code, in TXD word 6;
  `mt7925_mac_set_fixed_rate_table` writes the PHY code through ITDR0/ITDR1/ITCR.
  `DIS_MAT` preserves the synthetic frame. Optional `FIXED_BW` is word-6 bit 25.

With `MT76_FW_DIR` pointing at the pinned firmware directory, use the project venv:

```sh
python research/phy_tx_probe.py --transmitter mt7925 --acknowledge-experimental-transmit
python research/phy_tx_probe.py --transmitter mt7961 --per-phase 10 --acknowledge-experimental-transmit
python research/phy_tx_probe.py --transmitter mt7925 --per-phase 10 --fixed-bw --acknowledge-experimental-transmit
```

The tool ceilings are 60 packets total, 50 ms spacing, no ACK, channel 36 or 149;
tests above used 36 only. Firmware reload in `finally` removes table changes.
Only exact synthetic-frame metadata and TX statuses are emitted, never ambient
frame bytes or identifiers. Offline fixtures cover rate encoding, fixed-BW isolation,
allowlists, exact matching, duplicate counting, and FCS rejection.

## Receive-stat lead: AP interface is refused, station interface remains open

**Follow-up:** the [station testmode experiment](STATION_TESTMODE.md) unlocked
MT7961's CE queries after idle mode entry. A subsequent explicit RX-path write
activated live counters and signal words; their units and probe-specific effects
remain unvalidated.

`research/rx_stat_query.py --usb-id 0e8d:7961` tested EXT `0xa4` QUERY,
four-byte payloads `00 00 00 00`, `03 00 00 00`, `04 00 00 00`,
`05 00 00 00`, `06 00 00 00`. All five yielded the existing calibrated
16-byte dispatch refusal signature. Full firmware reload and alive check passed
after each request. No matching `{handler,cid}` slot was found in any extracted
MT7961 firmware region. Request shapes are independently constructed from protocol
facts in the reference-only vendor header described in [RELATED_WORK](../RELATED_WORK.md#mediatek-mt_wifi-driver-headers).
This is not an enum/code transcription and is not a claim about MT7925 UNI.

More promising next measurement route: station-specific CE `TEST_CTRL` (`0x01`)
on MT7961, and UNI `TESTMODE_CTRL` (`0x46`)/`TESTMODE_RX_STAT` (`0x32`) on
MT7925. Upstream `mt7921/testmode.c`, `mt7925/testmode.c`, and their `mcu.h`
provide wrappers, but not the complete statistics selectors. MT7925 testmode
requires special UNI option bytes 0x02 (query) / 0x06 (set); the current generic
Python UNI helper does not implement that special case. Do not mistake a generic
ACK or a malformed request for a working statistics interface.

## Die-temperature control after the RF change

Three read-only observations after fresh normal boots returned **28 C on MT7961**
and **42 C on MT7925**, each stable across the three queries. These observations
do not point to current extreme die heating, but do not establish the earlier
one-stream/TX performance change's cause or exclude past/localized thermal issues.
No TX was performed; reload/alive checks passed on both devices.
[Evidence](../research/evidence/die-temperature-control-2026-09-05.json).

Queries match `mt7921_mcu_get_temperature` / `mt7925_mcu_get_temperature` in
mt76 `c5a3bd91`: MT7961 EXT 0x2c with eight zero bytes; MT7925 UNI 0x35 QUERY
with reserved4 + tag0/length8 + zero4. MT7925 returned EID 0x35 with matching
sequences, a 16-byte body, tag0/length12, category0, temperature u32 at body+12.
The production MT7925 temperature method remains explicitly unported; this is
a research validation of the upstream request, not a claim of API parity.
