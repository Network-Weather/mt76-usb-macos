# Windows single-MT7961 qualification

Scope: one ALFA AWUS036AXML (`0e8d:7961`, revision `0x8a10`), Windows 11 Pro
build 26200, Wi-Fi interface 3 bound to WinUSB. This is an isolated research
experiment with the two-register alias wrapper. It is not production Windows
support or parity with every macOS research capability.

Sources: [initial hardware evidence](evidence-2026-09-22.json),
[expanded run records and aggregate results](qualification-2026-09-22.json),
and [reproducible matrix](qualify.py). The expanded record includes arguments,
exit codes, durations, source/log hashes, failures and recovery runs. Raw captures,
ambient identifiers and unsanitized logs remain local under ignored `build/`.
The local date is September 22; the expanded runs occurred September 23 UTC.

The expanded record contains 69 invocations across 39 Python entrypoints: 45
zero-exit experiments, 12 nonzero attempts and 12 successful recovery runs.
Six nonzero attempts were USB timeouts; three were CLI-option refusals and three
were warning/negative diagnostic exits. The CLI inventory covers 101 existing
entrypoints in `research/`, `scripts/` and `examples/`.

## Capture and transport

| Capability | Observation | Boundary |
| --- | --- | --- |
| Tri-band smoke | 43 channels attempted; 915 frames; zero USB errors | Frames on 3/3 low-band, 16/25 5-GHz and 9/15 6-GHz channels; silent channels are not failures or proof of reception |
| 20 MHz | Frames on channels 6, 36 and 53 | Short ambient observations |
| 40/80 MHz | Width probe decoded actual 40/80-MHz frames on 5 and 6 GHz | 2.4-GHz/40 configuration received only 20-MHz frames; 160 MHz exceeds MT7961's supported driver limit |
| PCAP export | Initial 2.4/5-GHz 20-MHz and additional 5/6-GHz 80-MHz captures independently decoded with Scapy | Counts, expected frequencies and hashes recorded; no throughput guarantee |
| Retuning | Twenty 2.4/6-GHz transitions; 1,291 dwell frames; zero USB errors | 23 queued frames discarded during transitions; retunes are not lossless |
| 2.4/5-GHz retuning | Ten transitions; 196 dwell frames; zero USB errors | Three queued frames discarded; some short 5-GHz dwells were empty |
| Sustained receive | 60 seconds on 5-GHz channel 36; 2,274 NORMAL transfers; zero USB errors | Six read timeouts; no hours-long soak, suspend/resume or cable-removal test |
| User tools | Channel scan, bounded roam watcher and single-adapter inventory completed | No controlled roaming client or simultaneous two-radio capture |
| Reset/recovery | Warm firmware reloads and post-diagnostic capture succeeded | Intermittent NIC power-control bulk-write timeouts; retry/recovery is still required |

The native SDK probe independently reproduces WinUSB error 87 on the unmodified
UHW endpoint-control read. Ordinary access to the same register succeeds. The
wrapper changes only the two documented aliases and preserves UHW reset encoding;
these observations do not identify which Windows component rejects the request.

## Research capabilities

| Family | Windows result | Interpretation |
| --- | --- | --- |
| Group-5 vectors | Off/on/restore completed on all three bands; extended masks observed; register restored | Queued extended vectors can remain after disabling; not a new PHY calibration |
| MIB/PHY queries | All 19 default MIB offsets answered; seven moved in the sampled interval | Published PHY categories were refused; MMIO survey views were zero; not calibrated occupancy |
| RMAC ICS | 5-GHz activation yielded 13 valid type-12 records, with nine header matches in memory | 15 records also arrived in the off-after window; no proof of immediate disable. The 2.4-GHz Group-5 run yielded none |
| RX-vector report switch | Off/on/off acknowledged with status 0; normal frames continued | No additional diagnostic record stream observed |
| CN/EVM, signal fields, CFO | Existing register/formula cross-check scripts completed, including RF receive mode | No controlled stimulus, freshness guarantee, calibration or physical-unit claim |
| PHY counters | Normal/RF queries and reversible normal-mode counter bits exercised | Independent stimulus and counter meaning remain unqualified |
| Noise histogram | Legacy bounded histogram accumulated in bin 0 | IPI command/compact/direct-register variants remained zero; no usable noise-floor estimate established |
| Spatial reuse | Register reads and legacy query transport completed | Query acceptance is not evidence that spatial reuse is active |
| Radar detector | STOP and bounded START/STOP state/register controls completed; reload cleared state | No radar stimulus, detection accuracy or DFS compliance test |
| Station test mode | Normal and RF query plans completed | Engineering transport is MT7925-only; no factory TX burst attempted |
| CSI / RTT / EXT RX stats | MT7961 CSI and RTT returned command-not-found; EXT RX-stat categories refused | Negative results; MT7925 CSI research is not portable evidence for this chip |
| ICAP | Status answered and capture controls changed; cleanup/reload succeeded | Requested capture did not complete; retrieval skipped |
| Temperature / efuse | 32 C reported; valid 16-byte efuse read | No efuse contents exported and no nonvolatile writes |
| Power / noise query | Power reports echoed channels 6, 36 and 53 | Noise helper rejected unexpected events on every band; power tables are not measured RF output |
| Clocks | LPON advanced across three reads; TSF snapshot returned zero throughout | No shared epoch, calibrated timing or multi-radio alignment claim |
| TX submission / status | Three synthetic channel-6 probes submitted; three firmware TX-status records; receive/reload worked afterward | Firmware evidence only; independent receiver qualification remains blocked |

The existing injection example submitted three additional channel-6 probes and
received 294 frames afterward, but saw no directed Probe Response. Total TX was
six wildcard Probe Requests. The final firmware reload received 443 NORMAL
transfers over three seconds with zero USB errors or timeouts.

The per-run record distinguishes nonzero warning/negative exits from transport
failures. Initial invocations of RXV reporting, station engineering and CSI used
MT7925-only options and were refused before hardware access. Applicable MT7961
variants were rerun; engineering mode remains untested. Failed bring-ups are
retained alongside successful retries. A successful script exit is never taken
as proof that its queried feature produced useful output.

## Coverage that needs more hardware

The JSON inventory names each existing CLI and records whether it was executed,
exercised only through a helper, or excluded. Applicable single-radio paths were
sampled; this is not a combinatorial run of every CLI flag, channel, width and rate.

- A second independently receiving radio is required for controlled PHY TX
  formats, power/airtime calibration, delivery/BlockAck correlation, error-frame
  visibility, controlled diagnostic stimuli and cross-radio clock/retune tests.
- An MT7925 is required for its UNI command space, CSI selection/filtering,
  PHY/TMAC/RMAC ICS variants, subchannel MIB ownership, power tables, thermal,
  beamforming, EDCCA and band-timeout research. The MT7961 alias wrapper must not
  silently be applied to it.
- The production C driver uses macOS IOKit. Its builds and tests run in macOS CI;
  only the separate SDK WinUSB probe is native Windows code. No Windows C
  acquisition parity or installer qualification is claimed.
- Long soaks, multiple adapters, suspend/resume, reconnect automation, install/
  uninstall and independent host/USB-controller testing remain open.

These boundaries follow the research [index](../README.md),
[findings ledger](../../docs/OVERNIGHT_EXPLORATION.md) and
[C parity contract](../../docs/C_PARITY.md).

## Software validation

Windows Python 3.14.2 in UTF-8 mode: **1,495 passed, 139 skipped**. Ruff formatting,
lint and documentation checks pass. MSVC builds the WinUSB probe with
`/W4 /WX /std:c17`. The Windows CI job checks those same offline surfaces; four
macOS jobs cover Python 3.10/3.14, distributable builds and the native C tests.
CI success does not substitute for hardware results or remove the limitations above.
