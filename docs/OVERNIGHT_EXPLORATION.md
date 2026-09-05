# Firmware exploration continuation — 2026-09-05

Tracking [PR #31](https://github.com/Network-Weather/mt76-usb-macos/pull/31).
User-authorized autonomous measurement/TX exploration; not a networking driver.
No merge, nonvolatile firmware writes, host-memory DMA, raw ambient captures, or
calibrated claims by inference. Results below extend [station testmode](STATION_TESTMODE.md).

**Major static-analysis correction:** [NDS32, not Xtensa](NDS32_RECON.md).
Startup exposes the EX9 table, and a GP candidate recovers meaningful string
references. Internal dispatch tags also must not be equated directly to wire IDs.

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

## Individual RX masks identify signal-word byte positions

The existing paired-radio receiver probe was repeated with masks 1 and 2. Each
run submitted 12 monitor controls and 36 synthetic no-ACK probes at 50 ms spacing;
monitor controls decoded 11/12 and 12/12 respectively. RX counters changed with
either single-chain mask and froze after stop. Both radios reloaded/alive afterward.

| RX mask | Selector 46 byte 0, signed | Selector 46 byte 1, signed | Selector 50 |
|---|---|---|---|
| 1 | changes: -94,-93,-92 | constant -109 | changes |
| 2 | constant -109 | changes: -95,-96,-89 | fixed 0x80804040 |

This supports selector 46's low two bytes being chain-0 and chain-1 signal
readouts, respectively, with -109 a disabled-chain value in these runs. It does
not calibrate their RF units or prove -109 is a universal sentinel. Selector 50
does **not** behave like a whole-radio signal readout: it remains at the same word
with only chain 1 active. Treat it as chain-dependent until firmware decoding
establishes more. The aggregate signal does not show a reliable 0/-16/0 probe
attenuation pattern; ambient traffic still dominates last-sample observations.

[Sanitized chain-isolation evidence](../research/evidence/testmode-rx-chains-2026-09-05.json).

## ICAP: firmware-backed event-gate and node follow-up

Corrected disassembly identifies the actual ICAP dispatcher at 0x00933d86:
mode checks, action 1, functions 11/12/17 and the expected request length agree
with the working command. Start routes through 0x00964d5c → 0x0095c678 →
0x0095c630. In the chip routine at 0x0096c562, event -1 clears register bit 19
instead of enabling an event selector. Thus the earlier label “free-run” for
event 0 was not established by the firmware. The tool now labels the alternative
`--no-event-gate`, not “working free-run.”

Two further bounded 64-requested-sample, on-chip-only runs with explicit channel
preparation used event 0xffffffff: first node 0, then node 0x49. The latter is the
pinned QA mapping for node 8, also selected by the original
[MtkICAPtool](https://github.com/MtkWifiRev/MtkICAPtool/tree/d829596a88e66382b3afe0f6be1de0c15ff88037)
on a different chip; it remains a candidate here. Both runs again gave pre-start
done=1, then 0/0/0. No data retrieval was requested and reset/alive checks passed.
[Evidence](../research/evidence/icap-trigger-node-2026-09-05.json).

The start/status path calls through ROM-table words at 0x00823000 and 0x00823014.
Their actual targets are a new read-only lead. Sample length remains a requested
software parameter, not proof of a hardware-enforced ADC sample ceiling; captures
are additionally bounded by ring-off, on-chip storage and short stop/reset windows.

The bounded USB read check succeeded: 0x00915000 returns 0x15090046 and
0x0096c7bc returns 0x00000c46, matching known image bytes. ROM-table words
0x00823000 and 0x00823014 return **0x008322da** and **0x00832344**, respectively.
Both targets lie in the expected ROM range. Only four words were read; firmware
reload/alive checks passed. This establishes a viable targeted-ROM-inspection
route, not permission or need to dump unrelated memory. Checkpoint: 620 tests pass.

## Histogram compact setter: corrected layout is not enough

The actual IPI dispatcher is 0x009616d0, not the same-numbered internal table
tag previously used as a shortcut. Its SET path passes the payload start to
`rdmSetIpiHist` at 0x00961618. That function consumes bytes 0/1 as type/value,
with PHY and band zero, then calls 0x0096bd20. The earlier AP-shaped request
placed value in byte 2. Thus an important request-layout assumption was wrong.

`research/ipi_compact_probe.py` compares the old and compact layouts across fresh
boots, with type 0/value 1 and three 0.5-second-spaced ALL queries. Both normal
monitor mode and the activated RF receiver were tested. All bins and free-run
values remained zero for both layouts. RF-mode SET replies echoed CID 0xa3 and
status 0, so no dispatch refusal was observed there. All cleanup checks passed.
This corrects the layout without claiming a working histogram or noise floor.
[Sanitized evidence](../research/evidence/ipi-compact-2026-09-05.json).

The low-level routine uses abstract register-field access callbacks with selector
keys 0x260000/1/2; the read path uses keys based on 0x13004 shifted by five.
Resolving those callbacks is a better next step than repeating initialization.

## Runtime data relocation and shared field access

The 256-byte ICAP ROM window (local-only SHA-256
`b109e321be83821b4bd7fe0bb4a5c183250b3ce727ed1f7468324f38dfa006ae`)
decodes as NDS32. Start at 0x008322da writes field key 0x5a0013 through a
GP-relative callback; status at 0x00832344 reads the same field. Both use the
same field-access family as IPI. No ROM bytes are included in the repository.

The first attempt to read the callbacks used the file-layout GP surrogate and
returned all ones. A CE 0xc0 QUERY control at known code address 0x00915000
raised McuError; cleanup passed, and that route was not used to infer memory.
USB reads of known data words instead exposed **runtime relocation by +0x44c**.
Startup disassembly and four live table/string-word controls agree. All extracted
regions still exactly match the pinned image; see [NDS32_RECON](NDS32_RECON.md).

Corrected **runtime GP 0x02003000** resolves the callbacks:

| GP offset | Live slot | Target |
|---|---|---|
| 0x10800 | 0x02013800 | 0x00826c7e |
| 0x10808 | 0x02013808 | 0x00826ca2 |
| 0x1080c | 0x0201380c | 0x00826b70 |

[Sanitized relocation/pointer evidence](../research/evidence/firmware-relocation-2026-09-05.json).
These are pointer reads, not host function calls. Both device checks and full
reload cleanup passed. Next: decode this narrowly scoped ROM accessor family
to resolve the field keys to actual register locations.

## Concrete IPI and ICAP hardware field maps recovered

Following the shared ROM accessors resolves the actual registers and bit ranges;
see [FIRMWARE_FIELD_MAPS](FIRMWARE_FIELD_MAPS.md). The IPI GET path reads twelve
23-bit values at 0x830af0a8 through 0x830af0d4, not the older sibling-chip address.
ICAP active is bit 1 of 0x80021090. Field keys index a ROM description; their low
five bits are not bit positions. An independent bounded table resolver and unit
tests reproduce the mappings without redistributing ROM bytes.

Separate live register checks preserve the previous outcomes but narrow them:
IPI initialization still leaves its resolved control and counters reading zero,
with both request layouts in normal/RF RX. ICAP control changes 0x400 → 0x4f3
on start and 0x4f3 → 0x4f1 on stop, exactly matching its active/status semantics.
Three short post-start polls remain incomplete. All firmware reloads pass.
[Command/register evidence](../research/evidence/field-register-controls-2026-09-05.json).
Next: trace capture setup and IPI access gating from these concrete locations.

Follow-up controls confirm the PHY USB window changes as predicted, while one
exact reversible IPI initialization write still reads back zero. A packed ICAP
node predicts both mux and stop-count changes correctly but still does not finish.
Starting RX after ICAP mode does not resolve that in this run. Details and dated
evidence are in [the field-map activation section](FIRMWARE_FIELD_MAPS.md#activation-controls-and-remaining-limits).
These narrow the hardware questions without promoting idle registers to working
measurements. Next bounded surface: spatial-stream and bandwidth transmit controls
with independent second-radio decoding; keep capture-clock/legacy-route leads open.

The public-source revision remains Motorola gen4m `8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`;
no vendor implementation/header or firmware blob is included in this repository.

First checkpoint: 615 Python tests passed; targeted ruff format/lint, local
documentation/JSON checks, and whitespace checks passed. Hardware cleanup passed
for all runs above. Investigation continues; this is not a release qualification.
