# MT7925 ICS capture path

**Both RMAC and TMAC ICS open working type12 USB diagnostic streams**.
See [MAC receive aggregates](#mac-receive-aggregates) and
[own-transmit diagnostic fields](#own-transmit-diagnostic-fields).
UNI0x49 also reaches a distinct PHY sniffer state machine on the pinned firmware.
This is a concrete capture lead, **not yet a working raw-PHY capture result**.
The later [bounded activation checks](#bounded-activation-checks) program the
ring and triggers but produce no capture events. The initial read-only
[`ics_trace_probe.py`](../research/ics_trace_probe.py) verifies fixed loaded-code,
instruction-table and ROM hashes, exact field metadata, and idle controls.
Normal monitor setup is the only mode change; normal firmware reload follows.
[Sanitized live verification](../research/evidence/ics-capture-trace-2026-09-05.json)
matches all six windows and17 metadata words. Both trigger bits, write-head,
registered flag, enable state and retained cursors are zero before/after monitor
setup; reset bit10 is set. Alive and cleanup checks pass. The probe uses1507
aligned reads:1470 hash words,17 metadata words and two ten-word snapshots.

## Request and response provenance

Pinned Motorola gen4m revision
`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec` supplies the
[UNI structures](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h)
and [host translation](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_uni_cmd_event.c).
UNI49/tag0 uses four reserved bytes, then an88-byte TLV: its84-byte data has
version/action/u16 command length, module/filter/operation/padding, seven u16
conditions, and62 padding bytes. Total payload92 bytes. The host zeroes version
and command length. The command parser's PHY partition check is not a recipe
for selecting arbitrary capture sources or programming partition values.

Live table record `0221c07c` points to `e00353cc`. It copies84 bytes from
buffer+0x38; action is+0x39, operation+0x3e, condition0+0x40, condition1+0x42.
Action0/1 dispatches condition0:0 TMAC,1 RMAC,2 both,3 PHY. PHY action1 starts
mode0 of `e0073f60`, while action0 enters mode1 (stop). Action2 changes MAC
filters and is outside the proposed first test. After PHY control returns the
handler still queries TMAC/RMAC state and calls the shared MAC control helper;
that side effect must not be omitted from the safety analysis.

The PHY callback constructs EID0x30/tag2, TLV length0x428, with function index
**0x15**. This differs from the source enum's0x14, so do not reject this firmware
variant solely on the older enum. The predicted body is1068 bytes, declared
DMA1112 with the44-byte header. Fields are function index, packet number,
timestamp, data-word count, reserved words, and up to256 u32 data words.
These are predicted from construction, not observed events. Raw word format is
not established as I/Q, nor is it a calibrated spectrum measurement.

## State and capture controls

Configuration lives at `0225f33c`, state at `0225f380`, timer at `0225f3d0`,
context at `0225f3ec` (through pointer `0222e120`). A fresh request clears68/80
configuration/state bytes. Condition1 populates band/index fields, conditions2–5
feed partition configuration, and condition6 supplies the timer delay. Source
selector1–8 chooses a PHY register bank; condition3 selects which of eight
words to write and conditions4/5 form the32-bit value. Arbitrary condition
values are therefore **register programming**, not passive filter labels.

Start clears context counters, enables state and—if the shared prerequisite is
nonzero—calls `e0073ed4` to configure capture. It registers callback `e00741de`
and arms the timer. Stop clears state/configuration, calls the hardware stop
branch under the same prerequisite, and stops the timer. Internal mode2 polls
and rearms; mode4 can invoke a callback directly. These internal modes are not
additional host actions to guess.

The callback polls both capture indices. When ready it disables capture, then
allocates and emits up to sixteen chunks in a loop before rearming. This is
**repeating acquisition**, not a one-shot operation. Hardware stop also runs
configuration/reset helpers; it is not proof every clock/filter mask is restored.
A future experiment requires bounded host polling, explicit stop and normal
reload, plus before/after controls for every modified mask that can be traced.

The ROM field mapper resolves the relevant keys without sending any field writes:

| Key | Hardware field | Interpretation from caller |
| --- | --- | --- |
| `200003` | `81031000` bit27 | Shared ICS / spatial-reuse prerequisite |
| `6d0008` / `6e0008` | `82023090` / `82024090` bit10 | Reset helper writes complement of argument |
| `6d000b` / `6e000b` | `82023090` / `82024090` bit1 | Trigger written by start, read by status |

Domain32 uses mapper `0082f882`, table `0084ce80`, hardware base `81031000`.
First entry points to `0084d1f4`; field3 has inclusive bit pair27/27.
Domains0x6d/0x6e share descriptor `022105ec`, mapper `00836cdc`, table
`0084f0f8`; their hardware bases differ by0x1000. Entry0 is offset0x90 with13
fields, pair pointer `0084f178`. Fields8 and11 have pairs10/10 and1/1.
Status `00836ee0` reads the trigger key; the higher wrapper computes one minus
the AND across indices0/1 (unless a selector-specific branch bypasses reads).

The prerequisite reads `8c600013`, **bit27 set**, both after normal bring-up and
after monitor/channel6 setup. This rules out a closed prerequisite in this
observed state; it does not explain the earlier zero spatial-reuse counters or
establish that capture completes. Do not flip a broadly shared gate to force it.

## Device SRAM export, not caller-supplied host DMA

Mode2 enable writes capture-engine registers `88009004=ff000000`,
`8800900c=0`, `88009024=02000000`, `88009028=400`; disable clears `88009004`.
These come from leaf `e00b42c4`, not guessed addresses. Additional source-tap
and PHY clock operations at `e00b438e` / `e00b427e` / `e00b429a` remain relevant
to setup and cleanup. They are not issued by the read-only verifier.

Raw reader `e00b44d6` reads write-head `820230b4`, retains it at `02230450`, and
advances cursor `02230454`, copying at most256 words per chunk. Mapper
`e00b436c` accepts cursor up to0xffc and derives device SRAM addresses from
`((0x20c + (cursor >> 11)) << 13) + ((cursor << 1) & 0xff8)`. Each group reads
two adjacent words from each of two banks separated by0x1000, then reverses
the four-word order. No caller-provided host pointer appears in this path.
The mapper returns zero beyond its bound: write-head/cursor validity must be
checked before relying on this capture loop. The verifier reads the head only,
never SRAM samples. A capture test must retain only sanitized shape/status
statistics, not ambient payloads, raw words, or purported I/Q traces.

These are static control-flow inferences corroborated by selected live hashes
and metadata, not a full execution trace. Experimental Andes decoding caveats
still apply. Firmware RAM SHA-256 is
`23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`.

## Bounded activation checks

[`ics_control_probe.py`](../research/ics_control_probe.py) uses the exact92-byte
request, PHY module3, action1/0, condition0=3, band0, conditions2–5 zero.
Zero source selector takes the traced no-partition-write branch; it is **not**
a qualified capture-source selection. Condition6 is5000 for the short check,
or500 for a750ms observation window. No TX, raw sample reads, filter sweep,
host-memory pointer, or NVM operation. Event collection retains lengths only.

Both fresh-boot runs program the predicted registers:

| Control | Before | During | After firmware stop |
| --- | --- | --- | --- |
| `82023090` | `400` | `403` | `401` |
| `82024090` | `400` | `403` | **`403`** |
| Ring start, both (`…3098` / `…4098`) | `100000` | `0` | `0` |
| Ring end, both (`…309c` / `…409c`) | `11fffc` | `ffc` | `ffc` |
| Count, both (`…30a4` / `…40a4`) | `13fffc` | `0` | `0` |
| Write head, both (`…30b4` / `…40b4`) | `0` | `0` | `0` |

Host start-to-stop intervals are121ms and769ms. Neither sees an EID30 event.
The first misses a start ACK in its short collection but sees the expected
hardware transition and stop ACK; the longer run receives both ACKs, status0.
Triggers remain set and heads remain zero: **armed/programmed is not complete**.
The longer window is designed to cross one500-unit timer period by analogy
with the working histogram timer, but no event proves callback execution here.

The stop asymmetry is real, not just a disassembly concern: band0's stop branch
clears index0 only, while start configures/triggers both. The probe therefore
clears bit1 at both control addresses after issuing stop, then disables/restores
the engine and thirteen traced PHY/MAC/engine masks. Every readback passes in
both runs. Remaining mode bit0 and a software classification flag survive this
partial restoration; **normal reload is mandatory**, and returns all observed
state/trigger/cursor fields to baseline in both runs. Do not describe firmware
stop alone as cleanup or promote this into a production acquisition API.

Follow-up static details corroborate the setup: `e00b4082` supplies start0 for
mode2; `e00b40dc→e00b40d4` supplies end0x1000−4. ROM setters use field keys
`6d0020`/`6d0040` (plus index domain stride), while count setter uses`6d0080`.
Mode setter `00836de2` writes key`6d000c`; setup also writes`6d0002`,
`6d0006` and`6d00e6`. `e00b42be` always returns class0, whose fixed jump
entry`0221b770→e00b1cb8` performs no extra class-specific setter.
The shared MAC helper `0083238c` toggles bit24 of`820e705c` (band1`820f705c`).
These facts narrow the missing capture-source/completion question without
claiming a working sampler. [Two-run evidence](../research/evidence/ics-control-2026-09-05.json).

## MAC receive aggregates

The separate RMAC branch **does work**. Two fresh-boot off/on/off controls each
use400ms collection windows, no TX, and no filter-setting action. During enable,
the USB packet endpoint0x84 produces respectively20 and21 **type12 aggregates**;
all41 have declared length384 and header frame-count3. All four off windows have
zero ICS aggregates, while ordinary type2 receive packets remain visible in
every phase. There are no invalid aggregate lengths. Start/stop ACKs all report
CID49/status0, and both controls read back enabled only in the middle phase.
This qualifies a new diagnostic transport, **not yet decoded extra measurements**.

[`rmac_ics_probe.py`](../research/rmac_ics_probe.py) sends the same92-byte UNI49
layout with module2, action1/0, condition0=1 (RMAC only), band0, all other
conditions zero. It verifies the existing dispatcher/ICS hashes plus the two
specific MAC ROM windows before activation. No PHY ring is started.

Setter `0082b670` and getter `0082b69c` use **`820e50d0` bit0**; their band1
branch uses`820f50d0`. Shared helper `0083238c` uses **`820e705c` bit24** after
combining TMAC/RMAC enable states. The two masks are initially zero, change to
1/0x1000000 during enable, and return to zero through the stop command. Explicit
masked restoration and normal reload also pass in both runs. Unlike the PHY
stop caveat, these two observed MAC controls turn off through the command.

The source [RX header and packet types](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic/nic_rx.h)
define ICS12 / PHY ICS13 and the eight-byte aggregate header: u16 byte count,
five-bit frame count, six reserved bits, five-bit packet type, reserved u16,
and PSE FID. The [host RX implementation](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_rx.c)
wraps and logs that buffer; it does not decode the inner diagnostic records.
Do not infer a128-byte inner-record stride merely from384/3: the aggregate
header and any padding/record headers still need mapping.

The collector exports only endpoint/type counts and length/frame-count shapes,
never FIDs, inner words, identifiers or traffic payloads. Counts describe the
leading packet in each USB read, not a claim to enumerate every possible packed
DMA block. No packet-completeness, calibrated RSSI, chain, timestamp or topology
interpretation yet. [Sanitized two-run evidence](../research/evidence/rmac-ics-2026-09-05.json).

## Own-transmit diagnostic fields

TMAC-only ICS also works, with a different aggregate shape: **one288-byte,
frame-count2 aggregate per controlled transmission while enabled**. Four
fresh-boot off/on/off tests send four synthetic CCK1 packets in each phase,
alternating65/193-byte MAC frames. All sixteen enabled-phase submissions produce
an aggregate; eight off windows produce none. The second radio independently
receives43/48 exact good-FCS packets overall (14/16 in enabled phases), and
all48 have matched successful TX statuses. Ordinary receive packets continue.
These controls establish coexistence, not lossless RX or a throughput estimate.

[`tmac_ics_probe.py`](../research/tmac_ics_probe.py) uses module2/condition0=0,
action1/0, band0, all other conditions zero. TMAC setter/getter
`0082e282`/`0082e29c` use field key`1a0760`, whose table entry`0084c26c`
points to`0084c810`, offset0x120, field0 bit pair0/0. Thus enable is
**`820e4120` bit0**, combined with the already-traced`820e705c` bit24. Both
read back enabled only in the middle phase; stop, masked restoration and both
normal firmware reloads pass in every run. No PHY ring or MAC filter action.

The opaque records are **not exact copies of our complete frame or64-byte TXD**:
neither signature occurs in any aggregate. A local-only differential reducer
instead checks four isolated submissions, one temporally paired ICS record and
one correlated TX status each. It emits candidate offsets only, never record
words. Three runs use enabled-phase sequence ranges12–15,4–7,12–15 and find:

| Aggregate-relative byte offset | Candidate field | Observation |
| --- | --- | --- |
| 124 | u32 bits31:20 | Exact submitted12-bit sequence,12/12 pairs |
| 272 | u32 bits11:0 | Exact submitted12-bit sequence,12/12 pairs |
| 48 | u32 bits15:0 | Frame bytes+4:69/197,12/12 pairs |
| 96 | u32 bits15:0 | Frame bytes+4:69/197,12/12 pairs |
| 20 | u32 relative clock | Same inter-record deltas as TXS timestamp |
| 84 | u32 relative clock | Same inter-record deltas as TXS timestamp |

The length result is consistent with including a four-byte FCS. It is not a
generic definition for every record class. Timing analysis was added for the
last two runs: both candidate words have **zero residual against TXS timestamp
differences** across four packets per run (three nonzero intervals each).
No candidate absolute value fell within±10000 raw ticks of the TXS timestamp.
Thus equal rate/deltas do not establish a shared epoch, clock identity, units,
PPDU boundary, ranging, or a new independent clock. A clock value may simply be
repeated in multiple diagnostic headers. The earlier TXS timing qualification
remains separate; do not attach unearned ToA/ToF semantics here.

Temporal pairing was the discovery method; sequence/length agreement strengthens
it but does not replace an inner-record format specification. The full header,
subrecord boundaries, validity/version fields and rate/power fields are still
open. In particular,288/2 is not a proven144-byte subrecord stride. This is a
concrete starting map for further own-frame experiments and maintainer notes,
not a general decoder for ambient traffic.

An intermediate sequence-base32 attempt failed the existing packet builder's
0–19 bound before any packet or ICS command was sent; both reloads passed.
The CLI now permits bases0/8 only. This was a host-side test-planning error,
not a dongle failure. [Four successful runs plus bounded setup failure](../research/evidence/tmac-ics-2026-09-05.json).

## Power and rate differentials

Four additional fresh-boot twelve-packet controls separate power, rate, length
and sequence. All retain four288-byte/frame-count2 aggregates while enabled,
none in off phases; all control restorations and both-radio reloads pass.
Sequence/length candidates persist. Both relative-clock candidates again have
zero residual against TXS inter-packet deltas in each enabled phase.

Two power runs change only source-defined TXD2 bits31:26 between0/−4, using
the phase pattern0,0,−4,−4 while length independently alternates65/193. TXS
power follows36,36,32,32. **Aggregate offset24 bits23:16** matches those values
for all eight enabled-phase packets across sequence ranges4–7 and12–15.
Independent good-FCS reception is23/24 overall,8/8 enabled. This is a candidate
raw hardware power field, not calibrated transmit power, received signal or a
new power-control mechanism. No positive offsets or calibration-table writes.

Two rate runs use only the already-qualified fixed-table CCK codes0/1 (1/2Mbps),
first0,0,1,1 then0,1,0,1. Known table writes occur before isolated submissions;
there are no MCU queries consuming the ICS stream between packets. The second
radio receives24/24 exact good-FCS packets and confirms CCK MCS0/1, one stream,
20MHz matching TX statuses. **Aggregate offset88 low14 bits** matches the rate
code for all eight enabled-phase packets in both arrangements.

The alternating run also creates apparent rate matches at offsets48/96 shifted
by7: those are the previously identified lengths69/197, whose bit7 happens to
follow the chosen rate pattern. They fail the grouped-rate control and are
**not rate fields**. Keeping both arrangements prevents that false mapping.
Widths8/14 are candidate extraction masks tested here, not proof all encodings
or high bits have the same meaning for OFDM/HT/HE, retries or other record types.

[Sanitized power/rate controls](../research/evidence/tmac-ics-power-rate-2026-09-05.json).
Next: trace the category controls and inner record boundaries, then test richer
PHY formats with the same own-frame correlation and no ambient record export.
