# research

Open questions and the experiments that probed them. Fresh as of 2026-09-04.

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
| [`channel_geometry_probe.py`](channel_geometry_probe.py) | Does 80 MHz capture observe independent 20 MHz traffic on other primaries? | **partly answered** — MT7925 receives primary-matched probes but not the tested other-primary probes in the same span |
| [`mt7925_tx_probe.py`](mt7925_tx_probe.py) | Can connac3 transmit controlled probes and preserve their addresses? | **partly answered** — DIS_MAT preserves frame bytes; 5 GHz OFDM and relative attenuation measured; production API unchanged |
| [`delivery_evidence.py`](delivery_evidence.py) | Can receiver-reported receipt distinguish the two observers' visibility? | **partly answered** — shared BlockAcks expose complementary recent-data visibility; no link-loss-rate claim |
| [`tx_power_probe.py`](tx_power_probe.py) | Do per-packet power-offset codes change actual received signal? | **partly answered** — negative codes lower independently measured signal; absolute power/units uncalibrated |
| [`rx_vector_probe.py`](rx_vector_probe.py) | What does the extended receive vector contain, and is Group 5 delivered? | **partly answered** — MT7961 enable works; MT7925 duplicate RCPI and HE/EHT color/direction checked |
| [`dual_radio_probe.py`](dual_radio_probe.py) | Can shared packets align clocks, and do controlled rates reach the air? | **partly answered** — microsecond clock agreement and 60/60 OFDM TX at 5 GHz channels 36/149 |
| [`clock_retune_probe.py`](clock_retune_probe.py) | Does a clock model survive a channel excursion? | **answered for tested excursions** — both radios preserve calibration after returning; long-term stability untested |
| [`control_frames.py`](control_frames.py) | What do control exchanges say about endpoints and delivered sequences? | **helper** — bounded single-TID compressed BlockAck decoder; no loss-rate claim |
| [`ipi_probe.py`](ipi_probe.py) | Is the PHY's power histogram reachable through the USB register window? | **partly answered** — the window is mapped, the histogram is not at mt7915's address |
| [`ipi_hist_cmd.py`](ipi_hist_cmd.py) | Will `RDD_IPI_HIST_CTRL` (0xa3) return a noise floor? | **open** — transport works, the sampler stays idle |
| [`mcu_command_probe.py`](mcu_command_probe.py) | Which MCU commands does this firmware actually implement? | **answered** — the refusal reply identifies them |
| [`uni_mib_probe.py`](uni_mib_probe.py) | Does the MT7925 keep the same counters behind UNI? | **partly** — established transport and the accepted/running offset set; follow-up tools identify the useful subset |
| [`cross_measure.py`](cross_measure.py) | Do two radios agree, and do injected frames reach the air? | **answered** — they agree; this CCK-only path radiates on 2.4 GHz; see `dual_radio_probe.py` for 5 GHz OFDM |
| [`mib_offset_sweep.py`](mib_offset_sweep.py) | Which EXT MIB counter offsets does this chip accept? | **answered** — MT7921 numbering identified; MT7925 uses the separate UNI probe |
| [`mt7925_mib_characterize.py`](mt7925_mib_characterize.py) | Which MT7925 UNI counters track frames, receive duration, CCA and ED? | **answered in part** — offsets 2/11/12/13/19/20 identified behaviorally; 17 remains provisional |
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
