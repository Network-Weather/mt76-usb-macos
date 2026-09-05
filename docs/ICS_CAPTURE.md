# MT7925 ICS capture path

UNI0x49 reaches a distinct MAC/PHY sniffer state machine on the pinned firmware.
This is a concrete capture lead, **not yet a working raw-PHY capture result**.
No ICS command has been sent at this checkpoint. The read-only
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
