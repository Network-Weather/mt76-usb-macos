# research

Open questions and the experiments that probed them. Updated 2026-09-05.

Everything here touches hardware, answers a question that is **not yet settled**, and is not
part of the supported surface. Scripts in [`../scripts/`](../scripts/mib_survey.py) are diagnostics that
work; scripts here are how we find out whether something *can* work. A result that graduates
moves to `scripts/` with dated evidence in [../docs/TESTING.md](../docs/TESTING.md); a result
that dies is recorded in [../NEGATIVE_RESULTS.md](../NEGATIVE_RESULTS.md) and the script stays
so the finding can be re-run rather than re-argued.

The background, the capability map and the method these follow are in
[../docs/FIRMWARE_RECON.md](../docs/FIRMWARE_RECON.md).

## What is here

The ongoing [radio observability exploration](../docs/RADIO_OBSERVABILITY.md) follows
extended receive vectors, control exchanges, and two-radio timing, with dated evidence
and explicit distinctions between hypotheses and measured capabilities.

The follow-up [receiver evidence and power experiments](../docs/RECEIVER_EVIDENCE.md)
test BlockAck/data visibility and bounded per-packet attenuation.
The [MT7925 transmit experiment](../docs/MT7925_TRANSMIT.md) tests the reverse
direction, fixed-rate table, and source-address preservation.
The [controlled channel-geometry experiment](../docs/CHANNEL_GEOMETRY.md) checks
whether a wider receive configuration observes independent narrower channels.

| script | question | state |
|---|---|---|
| [`csi_control_probe.py`](csi_control_probe.py) | Can station CSI capture yield live coefficients? | **yes on MT7925** — ROM-derived frame selection yields 64 I/64 Q reports with two receiver-chain indices; aggregate-only output; [protocol, evidence and limits](../docs/STATION_CSI.md) |
| [`csi_filter_probe.py`](csi_filter_probe.py) | Can CSI be restricted to one heard transmitter? | **yes** — tag4 ADD/REMOVE selects/restores sources independently of normal beacon reception; START clears the selection |
| [`csi_event_summary.py`](csi_event_summary.py) / [`csi_correlation.py`](csi_correlation.py) | Are CSI dimensions valid and reports pairable? | **bounded validation** — strict nested lengths and zero tail; source coincidence and TA+tag25 receiver pairing, no identifiers or arrays exported |
| [`beamforming_read_probe.py`](beamforming_read_probe.py) | Are PFMU tag/profile reads reachable? | **yes on MT7925 UNI0x33** — unsolicited sequence-zero replies; profile data is not automatically live CSI; [details](../docs/BEAMFORMING_PROFILES.md) |
| [`firmware_fields.py`](firmware_fields.py) | Which registers do the real IPI/ICAP field keys address? | **ROM-derived maps recovered** — bounded resolver and command/register controls; [details](../docs/FIRMWARE_FIELD_MAPS.md) |
| [`ipi_register_probe.py`](ipi_register_probe.py) | Does the exact firmware-derived IPI init write stick? | **negative in RF RX** — one masked volatile write reads zero, restore/reload pass; opt-in direct write only |
| [`ipi_compact_probe.py`](ipi_compact_probe.py) | Does the firmware's compact setter layout activate IPI? | **not by itself** — normal/RF RX layout controls still zero; actual dispatcher and field-access leads recovered |
| [`legacy_rx_stats_probe.py`](legacy_rx_stats_probe.py) | Does CE 0xc8 expose richer RX statistics? | **live block found; request corrected** — pinned firmware needs an explicit band word (12 bytes); reply word2 is echoed band, not status; counter-draining read effects; [ledger](../docs/OVERNIGHT_EXPLORATION.md#legacy-ce-0xc8-exposes-a-richer-live-block-with-read-side-effects) |
| [`cfo_crosscheck_probe.py`](cfo_crosscheck_probe.py) | Where do MT7961 frequency-offset/SNR values come from? | **firmware provenance and live exact matches** — three fixed cached-vector reads reproduce nonzero statistics in two boots; no calibrated units or freshness claim; [findings](../docs/FREQUENCY_OFFSET.md) |
| [`rxv_log_probe.py`](rxv_log_probe.py) | Can separate receive-vector measurements be retrieved? | **working finite log** — count/query readout, actual176-byte stride and five-record cap traced; separate CFO/SNR/RCPI values under eight bounded synthetic probes; [findings](../docs/RX_VECTOR_LOG.md) |
| [`phy_stats_probe.py`](phy_stats_probe.py) | Can PHY detection, header-error and receive-ready counts be separated? | **working GET41 snapshot** — ten firmware-mapped16-bit counters, controlled HT/HE response and stopped repeat-read/reset validation; [findings](../docs/PHY_RX_COUNTERS.md) |
| [`normal_phy_counter_probe.py`](normal_phy_counter_probe.py) | Can these PHY counters run alongside normal packet capture? | **working enable/freeze primitive** — exact firmware-backed mask changes enable accumulation; independent baseline/enabled/restored receipt controls; no RF-test entry |
| [`legacy_noise_hist_probe.py`](legacy_noise_hist_probe.py) | Is there another live PHY histogram engine? | **working eleven-bin acquisition** — firmware-traced reset/enable/stop, repeated time scaling in normal mode; currently bin0-only, no calibrated noise claim; [findings](../docs/LEGACY_PHY_HISTOGRAM.md) |
| [`edcca_query_probe.py`](edcca_query_probe.py) | Can actual EDCCA configuration be read? | **MT7925 query readout works** — enable and band-dependent three-byte thresholds; explicit query framing, no threshold SET; [findings](../docs/BAND_CONFIG_MEASUREMENTS.md) |
| [`rxv_report_probe.py`](rxv_report_probe.py) | Does UNI band-config RX-vector reporting expose another stream? | **accepted but no new records** — passive off/on/off controls on both chips, good-FCS reception continues with unchanged group masks |
| [`icap_capture_probe.py`](icap_capture_probe.py) | Can bounded on-chip ICAP collect samples? | **in progress** — start changes status but candidate node 0 did not complete; [continuation ledger](../docs/OVERNIGHT_EXPLORATION.md) |
| [`icap_status_probe.py`](icap_status_probe.py) | Does station mode entry unlock ICAP status? | **yes after mode 2** — matched 68-byte status event; no IQ capture or spectrum measurement yet |
| [`station_testmode_probe.py`](station_testmode_probe.py) | Are station-specific test queries reachable? | **yes on MT7961 after idle RF-test mode entry**; [details and limits](../docs/STATION_TESTMODE.md) |
| [`testmode_tx_probe.py`](testmode_tx_probe.py) | Does the MT7961 factory packet generator honor a finite count? | **counter control works** — requested4 yields TXED/TXOK4 and stays4 after STOP; independent over-air delivery still absent; explicit TX opt-in |
| [`testmode_receiver_probe.py`](testmode_receiver_probe.py) | Can the RF-test receiver sample live activity? | **yes with explicit RX path** — changing counters/signal words; stop freezes them; [controlled comparisons](../docs/STATION_TESTMODE.md#rx-path-activation-follow-up); signal units and probe-specific effects unvalidated |
| [`phy_tx_probe.py`](phy_tx_probe.py) | Can either chip transmit HT/VHT/HE with the existing injection path? | **new measured capabilities** — HT/VHT both directions, HE-SU from MT7961 and two-stream HE from MT7925; current RF-performance caveat remains; [evidence](../docs/PHY_TRANSMIT.md) |
| [`rx_stat_query.py`](rx_stat_query.py) | Does the station firmware accept the AP-driver EXT 0xa4 receive-stat queries? | **negative on MT7961** — all five tested categories refused; station testmode is a separate lead |
| [`channel_geometry_probe.py`](channel_geometry_probe.py) | Does 80 MHz capture observe independent 20 MHz traffic on other primaries? | **partly answered** — both radios receive primary-matched probes but not the tested other-primary probes in the same span |
| [`mt7925_tx_probe.py`](mt7925_tx_probe.py) | Can connac3 transmit controlled probes and preserve their addresses? | **partly answered** — DIS_MAT preserves frame bytes; 5 GHz OFDM and relative attenuation measured; production API unchanged |
| [`delivery_evidence.py`](delivery_evidence.py) | Can receiver-reported receipt distinguish the two observers' visibility? | **partly answered** — shared BlockAcks expose complementary recent-data visibility; no link-loss-rate claim |
| [`tx_power_probe.py`](tx_power_probe.py) | Do per-packet power-offset codes change actual received signal? | **partly answered** — negative codes lower independently measured signal; absolute power/units uncalibrated |
| [`rx_vector_probe.py`](rx_vector_probe.py) | What does the extended receive vector contain, and is Group 5 delivered? | **partly answered** — MT7961 enable works; MT7925 duplicate RCPI and HE/EHT color/direction checked |
| [`dual_radio_probe.py`](dual_radio_probe.py) | Can shared packets align clocks, and do controlled rates reach the air? | **partly answered** — microsecond clock agreement and 60/60 OFDM TX at 5 GHz channels 36/149 |
| [`clock_retune_probe.py`](clock_retune_probe.py) | Does a clock model survive a channel excursion? | **answered for tested excursions** — both radios preserve calibration after returning; long-term stability untested |
| [`control_frames.py`](control_frames.py) | What do control exchanges say about endpoints and delivered sequences? | **helper** — bounded single-TID compressed BlockAck decoder; no loss-rate claim |
| [`ipi_probe.py`](ipi_probe.py) | Is the PHY's power histogram reachable through the USB register window? | **historical negative at sibling addresses** — a different, firmware-traced bank now works; see `legacy_noise_hist_probe.py` |
| [`ipi_hist_cmd.py`](ipi_hist_cmd.py) | Will `RDD_IPI_HIST_CTRL` (0xa3) return a noise floor? | **open** — transport works, the sampler stays idle |
| [`mcu_command_probe.py`](mcu_command_probe.py) | Which MCU commands does this firmware actually implement? | **answered** — the refusal reply identifies them |
| [`uni_mib_probe.py`](uni_mib_probe.py) | Does the MT7925 keep the same counters behind UNI? | **partly** — established transport and the accepted/running offset set; follow-up tools identify the useful subset |
| [`cross_measure.py`](cross_measure.py) | Do two radios agree, and do injected frames reach the air? | **answered** — they agree; this CCK-only path radiates on 2.4 GHz; see `dual_radio_probe.py` for 5 GHz OFDM |
| [`mib_offset_sweep.py`](mib_offset_sweep.py) | Which EXT MIB counter offsets does this chip accept? | **answered** — MT7921 numbering identified; MT7925 uses the separate UNI probe |
| [`mt7925_mib_characterize.py`](mt7925_mib_characterize.py) | Which MT7925 UNI counters track frames, receive duration, CCA and ED? | **answered in part** — source/ROM follow-up corrects17 to primary CCA,19 to CCA+NAV+TX; units and configured sources remain qualified |
| [`mt7925_mib_crosscheck.py`](mt7925_mib_crosscheck.py) | Does the MT7925 CCA candidate agree with the identified MT7921 counter? | **answered** — offset 19 agrees closely on quiet 6 GHz; receiver differences dominate busy channels |
| [`mt7925_mib_perturb.py`](mt7925_mib_perturb.py) | Does valid Wi-Fi traffic separate the MT7925 busy and ED candidates? | **answered in part** — valid Wi-Fi raises offset 20, disproving a non-Wi-Fi-only interpretation |

## Running these

They need an attached adapter and the project venv, and they pin the USB id because two
adapters are usually attached here:

```bash
MT76_USB_ID=0e8d:7961 ./.venv/bin/python research/mib_offset_sweep.py
MT76_USB_ID=0e8d:7961 ./.venv/bin/python research/mcu_command_probe.py
MT76_USB_ID=0846:9072 ./.venv/bin/python research/uni_mib_probe.py --max 48
MT76_USB_ID=0e8d:7961 ./.venv/bin/python research/ipi_hist_cmd.py
MT76_USB_ID=0e8d:7961 ./.venv/bin/python research/ipi_probe.py --band 5GHz --channel 36
./.venv/bin/python research/cross_measure.py --band 5GHz --channel 36 --seconds 8
./.venv/bin/python research/mt7925_mib_characterize.py 2.4GHz:1 5GHz:36 6GHz:37 --seconds 6
./.venv/bin/python research/mt7925_mib_crosscheck.py 5GHz:36 6GHz:37 --seconds 5
```

`cross_measure.py` and `mt7925_mib_crosscheck.py` open both adapters themselves and take no
`MT76_USB_ID`. `mt7925_mib_perturb.py` transmits and is intentionally omitted from the passive
command list; its docstring records the explicit acknowledgement and frame ceiling.

## Rules

- **Passive receive only, unless the script says otherwise in its docstring and the user has
  agreed.** `ipi_hist_cmd.py` and `mcu_command_probe.py` send SET commands; both say so.
- Nothing here is imported by `scripts/` or by the driver. The dependency runs one way.
- A script that stops answering a live question belongs in git history, not in this directory,
  but delete it only once its finding is written down somewhere durable.
- No SSIDs, BSSIDs, or capture payloads in output, same as everywhere else in this repository.
