# Firmware exploration continuation — 2026-09-05

Tracking [PR #31](https://github.com/Network-Weather/mt76-usb-macos/pull/31).
User-authorized autonomous measurement/TX exploration; not a networking driver.
No merge, nonvolatile firmware writes, host-memory DMA, raw ambient captures, or
calibrated claims by inference. Results below extend [station testmode](STATION_TESTMODE.md).

**New GI/LDPC transmit controls:** [MT7925 fixed-rate ROM mapping](FIXED_RATE_TABLE.md)
locates GI and LDPC bits, and the second dongle independently receives HT8 with
short GI and with LDPC coding. A corrected UNI40 request also works, but exposes
post-write validation and an apparently uninitialized configuration byte; the
on-air probes retain our deterministic direct-table path.
The same mapping now produces independently received HE GI1/GI2 and LDPC.
GI-only HE requests failed; paired GI/LTF settings work. LTF was initially
unverified because full-group5 LTF metadata was unavailable.
Changing only LTF0→1 also unlocks **HE STBC**, independently received3/4 then2/4,
with HE2SS controls4/4 before/after both runs. DCM remains unreceived; no gain claim.

**Validated HE-LTF readout and a maintainer pointer:** enabling the already tested
Group5 report and following the vendor header yields LTF codes0/1/2 matching
**48/48** independently received controlled frames. The source-derived location
used by current MT7921's reassigned radiotap pointer instead mostly yields3.
[HE_LTF_RX_ORIGIN](HE_LTF_RX_ORIGIN.md) records current upstream source pointers,
the small reproducer and sanitized evidence. No Linux implementation or external
maintainer message was sent; this is the concrete documentation gift.

**New STBC transmit format:** [MT7925 HT0/STBC](PHY_TRANSMIT.md) is independently
received as NSS1/NSTS2/STBC=true, four exact frames and then one on a fresh repeat.
HT controls bracket both trials; the degraded/variable link prevents a gain claim.
The source-mapped rate is4480, not the older chip's different STBC encoding.

**New TX timing telemetry:** [MT7925 TX-status fields](TX_STATUS_TIMING.md) expose
live timestamp/front-time/delay values. Across48 no-ACK packets at five rates
and two lengths, a1µs/32µs clock model plus nominal packet airtime leaves a
per-boot offset with29–32µs spread. This is a promising delay observation, not
yet calibrated contention time or interference attribution.
Two subsequent eight-frame burst controls receive8/8 before/during/after;
every next front-time equals previous front+delay. Since all host submissions
finish in1.3–1.6ms while service spans17–22ms, these fields do not include all
earlier FIFO waiting. The evidence supports a serial service-boundary reading.

**Spatial-reuse queries:** [UNI25 capability/indicator replies](SPATIAL_REUSE.md)
work on MT7925 through unsolicited sequence-zero events. Two fresh-band controls
return stable configuration flags, but all eight counters remain zero despite
normal reception. This adds a query surface, not yet OBSS activity inference.
Following the getter into ROM subsequently unlocked three **live read-clear RMAC
counters**: direct inter-BSS-named values match decoded frame counts in five ch36
windows while the separate software accumulator stays zero. BSS attribution is
not yet qualified; the useful hardware source and its read-clear hazard are now
documented and probed without direct writes.

**Latched CN/EVM fields:** [a single MT7961 PHY register](PHY_SIGNAL_FIELDS.md)
updates during controlled two-stream HT reception in two fresh runs. Its values
then persist across CCK packets, so they must not be attached blindly to each
received frame. Units and physical interpretation remain unvalidated.

**Station radar detector:** [MT7925 UNI19 STOP/START/STOP](RADAR_DETECTOR.md)
returns success after correcting quiet-endpoint receive throttling. Three short
post-START windows yield no pulse reports. Independent ROM mapping now confirms
MT7925 mode0→5→0 and a512-byte ring at00416000, with169 normal OFDM frames
received during arming; its producer remains idle and reload restores all reads.
MT7961 CE8F stays silent on USB, but a later traced RAM-state read follows
STOP/START/STOP as0/0x101/0x100 and reload restores0, proving handler execution.
Its on-chip capture buffer is allocated. Follow-up ROM-derived reads now confirm
hardware detector mode0→5→0 and a512-byte capture ring installed. The producer
does not advance in the quiet trial; no usable pulse measurement is claimed.

**Timing/ranging frontier:** [RTT capability queries](TIMING_MEASUREMENTS.md)
are explicitly refused on both builds. MT7925 nevertheless advertises a ToA
engine in its LOCATION capability, unlike MT7961. This is a static capability
lead, not an exposed timestamp stream or a working ranging implementation.

**New MT7925 route:** [loaded plaintext code is USB-readable](MT7925_LOADED_FIRMWARE.md)
despite the encrypted container. Repeated entry reads establish RV32 startup, and
a bounded instruction-table read supports an experimental Andes-style expansion.
This does not establish a complete decoder.
Follow-up ROM startup establishes MT7925 GP `0x02212800`, corroborated by live
registration-table pointers; decryption occurs between the pre-start and running
read controls. Its 30-slot dispatcher is now identified as UNI 0x33 beamforming:
[PFMU tag and profile-data reads work](BEAMFORMING_PROFILES.md), with correctly
predicted unsolicited sequence-zero events. This is not yet usable CSI.

**CSI readout unlocked:** [MT7925 station UNI 0x4a](STATION_CSI.md) now yields
live I/Q reports after tag2/index0/value0x20 frame selection on band0. Two runs
validate 114/116 reports with 64 I and 64 Q values each, distinct payloads and
paired RX indices0/1. A firmware-specific 36-byte zero tail is explicitly checked.
No sample arrays or transmitter identities are retained, and calibration/topology
interpretation remains future work. Band1 stays silent in the current setup.

The initial [MT7925 station UNI 0x4a control lead](STATION_CSI.md)
acknowledges stop/start and maximum-chain tags with status zero. Both band
selectors were tested; no CSI sample events were seen. MT7961's legacy CE 0x4c
route returns the source-defined command-not-found event. No-ACK silence and
transfer-limited windows are explicitly separated from negative results.
Follow-up loaded-code tracing identifies both the control and report constructors.
ROM-derived MMIO controls now show that stop/start/stop really changes the selected
band's hardware at `0x820e5060` / `0x820f5060`, leaving the other band unchanged.
Reload restores the baseline. Zero USB RAM snapshots do not negate that result;
At that checkpoint CSI events were still absent; the nonzero frame selector
subsequently unlocked the readout above. No calibration capability is claimed.

**Major static-analysis correction:** [NDS32, not Xtensa](NDS32_RECON.md).
Startup exposes the EX9 table, and a GP candidate recovers meaningful string
references. A later [table-order correction](COMMAND_TABLES.md) explains the
apparent internal-tag mismatch: the old scanner read handler-then-next-CID instead
of CID-then-handler. Corrected mappings match independent CSI/BF/RDD controls.

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

**Later correction:** the initial eight-byte request below omitted an explicit
band word read by this pinned firmware. The current probe sends12 bytes and calls
the reply's third word `reported_band_u32`, not status. See the
[dispatcher trace and corrected request](FREQUENCY_OFFSET.md#complete-ce-0xc8-request-and-the-apparent-status-correction).
The historical observations below preserve the original experiment; values2/100
are now identified as invalid band arguments, not status codes.

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

Follow-up: [frequency-offset provenance](FREQUENCY_OFFSET.md) now traces word19's
signed20 assembly and integer conversion, plus word49's direct six-bit SNR export.
Two fresh boots exactly match nonzero cached-vector inputs to returned values;
a third zero-cache control establishes an important limit. Subsequent dispatcher
tracing corrected the apparent-status interpretation and incomplete request.

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

### Later static correction: legacy CE ICAP setters are absent

The public `rftest.h` names CE1 SET selectors80/81/82/83/84 as ICAP
content/mode/start/size/trigger offset, and112 as ICAP ring control. These names
do not imply implementation on this pinned MT7961 firmware. SET dispatch at
`0x00931b2c` takes the selector's low byte. Selectors80..84 (also85) follow
`0x00931c36 → 0x00931c44 → 0x00931c5e → 0x00931c6e → 0x00931c76`, then the
default EX9 jump at`0x00931c7e` directly to the return at`0x00933110`.
Selector112 similarly defaults via`0x00931d42..0x00931d52`. Neither route
applies capture configuration. No live writes were needed to establish this.
This closes the proposed legacy-setter alternative for this image, not the
separately implemented EXT04 functions11/12/17 or other firmware builds.

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

## Two-stream transmit capability and an RF-performance caveat

MT7925 transmitted independently decoded HT MCS8, VHT MCS0 and HE-SU MCS0 at
two streams/20 MHz: 6/6 each, then 4/4 each with fresh per-run payload nonces.
This establishes an HE transmit case beyond the earlier one-stream negative.
However one-stream controls are now weak/absent and MT7961 TX has no independent
decode. Normal-mode exit and forced WFSYS reset/reload did not restore that
control; alive checks alone are insufficient RF recovery evidence. See
[PHY_TRANSMIT](PHY_TRANSMIT.md#two-stream-follow-up-2026-09-05-utc) for the exact
counts and limitations. Wider-band TX tests are deferred until controls recover.
Next independent lead: whether bounded live instruction reads can expose the
MT7925's loaded code despite its encrypted firmware container.

The public-source revision remains Motorola gen4m `8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`;
no vendor implementation/header or firmware blob is included in this repository.

First checkpoint: 615 Python tests passed; targeted ruff format/lint, local
documentation/JSON checks, and whitespace checks passed. Hardware cleanup passed
for all runs above. Investigation continues; this is not a release qualification.
