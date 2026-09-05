# Firmware exploration continuation — 2026-09-05

Tracking [PR #31](https://github.com/Network-Weather/mt76-usb-macos/pull/31).
User-authorized autonomous measurement/TX exploration; not a networking driver.
No merge, nonvolatile firmware writes, host-memory DMA, raw ambient captures, or
calibrated claims by inference. Results below extend [station testmode](STATION_TESTMODE.md).

## ICAP: capture start changes state, node-0 completion not observed

`research/icap_capture_probe.py` sends a bounded EXT 0x04 SET with action 1,
function 11, and the 80-byte capture union documented in the pinned station
`wlan_oid.h` / `wlan_oid.c` references in STATION_TESTMODE. Explicit settings:

- Trigger 1, ring 0, free-run event 0, candidate node 0.
- Capture length and stop cycles each 64 or 256, never the zero/default size.
- Architecture 0 (on-chip), PHY/band/BW 0, all source/EMI addresses zero.
- No capture-to-host-memory/EMI configuration and no transmitter command.
- Stop uses the same request with trigger 0, then full firmware reload.

**Node 0 is only a candidate**, from the QA legacy default; its meaning on MT7961
is not established. The phone-driver helper normally chooses architecture 1;
that streaming setup is deliberately not transplanted onto a USB device.

Three runs, all MT7961 on the existing pinned firmware:

| Setup | Requested samples | Status before | Three post-start status replies | Recovery |
|---|---:|---:|---|---|
| ICAP mode only | 256 | done=1 | done=0, 0, 0 | reset/alive pass |
| Known RX-path activation before ICAP entry | 256 | done=1 | done=0, 0, 0 | reset/alive pass |
| Explicit ICAP channel preparation after entry | 64 | done=1 | done=0, 0, 0 | reset/alive pass |

Explicit channel preparation is band 0, RX mask `3 << 16`, frequency 5180000 kHz,
20 MHz and CE test function 1/value 13 (`CH_SWITCH_FOR_ICAP`). This is not TX-start.
Each status collection is 0.3 seconds; these runs establish lack of completion in
the tested short window, not permanent inability to complete. No samples were
retrieved. Requested retrieval was skipped unless completion was observed.

The retrieval builder is offline-tested only: function 17, address 0, increment 4,
bank 1, explicit one-KiB bank size, chain/IQ selector 0. That bounded shape must be
validated against an actual completed capture before claiming usable IQ. Summaries
emit only count/range/cardinality, never sample arrays. Raw IQ is not saved.

[Sanitized evidence](../research/evidence/icap-capture-2026-09-05.json).

```sh
python research/icap_capture_probe.py
python research/icap_capture_probe.py --prepare-rx --retrieve
python research/icap_capture_probe.py --samples 64 --icap-channel --retrieve
```

## MT7925 engineering queries: separate interface, same nonzero status

UNI 0x46 tag 0, length 92, GET_AT_ENG action 4, selectors 0/46/50 each returned
a 32-byte command-result reply echoing CID 0x46 with status `0xc00000bb` after
an idle test-mode entry attempt. No version/RSSI scalar was returned. Each query
used special UNI option 0x02 and fresh firmware boot/reset. All cleanup checks passed.

This follows the pinned vendor bridge's GET_AT=2 to GET_AT_ENG=4 mapping; it is
not a repeat of UNI 0x32 receive statistics. Mode entry itself was not established
on MT7925. No conclusion about different firmware images or all possible commands.
[Evidence](../research/evidence/mt7925-engineering-2026-09-05.json).

```sh
python research/station_testmode_probe.py --chip mt7925 --test-mode --engineering --selector 0 --selector 46 --selector 50
```

## Active next leads

- ICAP: establish capture node/clock prerequisites or a different supported on-chip
  request path; do not keep repeating the same incomplete node-0 request.
- Legacy CE `ACCESS_RX_STAT` 0xc8: source identifies its separate eight-byte query
  and event 0x45. Investigate richer RX error/signal statistics with the live sampler.
- Isolate RX-chain signal-word packing and compare controlled traffic/attenuation
  while preserving aggregate-vs-packet distinctions.
- Continue bounded independently observed transmit capabilities where source-backed
  descriptor fields offer a useful new measurement control.

## Legacy CE 0xc8 exposes a richer live block, with read side effects

`research/legacy_rx_stats_probe.py` queries CE 0xc8 with two little-endian u32s:
sequence 1..5 and count 72. Normal mode and activated RF RX both return matched
EID 0x45 / 300-byte bodies. Normal-mode statistics stay zero; live RX changes
many fields. Three fresh-boot runs established the reply shape; the final run
added RX-stop controls. All reload/alive checks passed. No transmission was used.

The pinned public header expects eight header bytes and big-endian statistics.
**That interpretation does not fit this firmware.** Observed replies fit a
12-byte header followed by 72 little-endian u32 words. Header words 0/1 echo
sequence/count; word 2 is initially 100 in normal mode and 2 in RF RX, then 0.
Its meaning is not established (`candidate_status_u32` in evidence). Initial
responses contain no statistics; later RF RX responses populate the block.

Interpreting the subsequent words with source-derived field positions yields
coherent counters and sign-extended signal values. Strong cross-checks:

| Candidate index / source name | First stopped query | Second stopped query |
|---|---:|---:|
| 0 / MAC_FCS_Err | 16 | 0 |
| 1 / MAC_Mdrdy | 125 | 0 |
| 3 / FCSErr_OFDM | 59 | 59 |
| 5 / OFDM_PD | 526 | 526 |
| 15 / PhyMdrdyOFDM | 461 | 461 |
| 16 / DriverRxCount | 353 | 353 |
| 17,18 / RCPI | 30,27 | 30,27 |
| 20,21 / RSSI signed candidates | -93,-95 | -93,-95 |
| 49 / SNR0 | 17 | 17 |

Index 16 exactly matches scalar selector 34's stopped value (353). Index 0
matches scalar selector 35 immediately before the first stopped query (16);
selector 35 reads 0 after the richer queries. Thus **the richer query drains at
least some counters**, while other fields are cumulative or last-sample values.
Do not mix this command into acquisition without accounting for its read effects.
No calibrated RSSI/SNR/frequency-offset units, non-Wi-Fi discrimination, packet
attribution, or validity of every source-derived field name is claimed.

[Sanitized evidence](../research/evidence/legacy-rx-stats-2026-09-05.json) retains
the candidate 66-word prefix and control observations. The tool retains both
layout hypotheses; the candidate interpretation does not silently replace the
reference format. Validation checkpoint: 618 Python tests passed.

The public-source revision remains Motorola gen4m `8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`;
no vendor implementation/header or firmware blob is included in this repository.

First checkpoint: 615 Python tests passed; targeted ruff format/lint, local
documentation/JSON checks, and whitespace checks passed. Hardware cleanup passed
for all runs above. Investigation continues; this is not a release qualification.
