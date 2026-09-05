# Station radar detector: MT7961 hardware arming works, pulse measurement unproven

On the pinned MT7925 firmware, **UNI0x19 STOP/START/STOP returns status0** in
normal unassociated channel36/20MHz receive mode. Three post-START one-second
windows contain301 good-FCS OFDM frames and **no candidate radar events**. This
establishes command acceptance, not hardware activation or usable pulse telemetry.
MT7961's silent CE8F route also **executes the receiver-control handler**: a later
firmware-derived state check follows STOP/START/STOP despite receiving no ACKs.
Independent ROM-mapped readback subsequently confirms detector mode and capture
gates change, with a512-byte ring installed; no producer advance is observed yet.
No transmitted test pattern, radar emulation, threshold writes, TX queue controls,
DFS-channel transmission or calibrated detection claim is involved.

## Exact station protocol

The pinned BSD-2-Clause gen4m source defines two transports:

- MT7961 candidate: CE`0x8f` SET, eight bytes containing control, detector index,
  RX selector, set-value and four reserved bytes. STOP is eight zero bytes.
- MT7925: UNI`0x19`, SET/UNI/ACK option7, reserved4 + tag0/length12 + that
  eight-byte control. STOP is `0000000000000c000000000000000000`.
- Receiver START uses control1, index0, RX selector0, **region1 (FCC detector
  profile)**: `0000000000000c000100000100000000`. This is not a TX country/power
  change. All-zero START would select region0/CE, not a neutral default.

Sources at gen4m commit`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`:
[command structures and enums](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_cmd_event.h),
[UNI layout and events](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h),
[nicUniCmdRddOnOffCtrl bridge](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_uni_cmd_event.c),
[p2pFuncStartRdd / p2pFuncStopRdd callers](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/mgmt/p2p_func.c).
The bridge is conditional on DFS-master support in that source. These protocol
facts do not establish which detector implementation the shipped image contains.

Source event candidates are UNI EID`0x11` (tags0 pulse/1 report), legacy station
EIDs`0x50` (send pulse)/`0x60` (report), or AP-style legacy EID`0xed`/extended
EID`0x3a`. The probe deliberately exports only event metadata;
no unobserved variable-length pulse structure is advertised as a working parser.
Do not confuse station CE`0x8f`, AP EXT`0x3a`, and internal dispatch-table tags.

## Live controls, 2026-09-05

`research/rdd_stop_probe.py` allows STOP only on either pinned chip.
`research/rdd_receive_probe.py --enable-passive-detector` allows the single
source-defined MT7925 START shape only after a matched successful STOP reply.
Both restore normal firmware in cleanup, including on exceptions.

| Probe | Result | Recovery |
|---|---|---|
| MT7961 CE8F, two STOPs,20ms endpoint waits | No event or decoded frame | Alive/reload pass |
| MT7925 UNI19, two STOPs,20ms waits | First ACK0; second not observed | Alive/reload pass |
| MT7925 STOP/START/STOP,20ms waits | Initial STOP ACK0; later ACKs not observed | Alive/reload pass |
| MT7925 STOP/START/STOP,1ms waits | **All three matched EID1/status0**;301 good-FCS frames after START; no pulse event | Alive/reload pass |
| MT7961 CE8F, two STOPs,1ms waits | No event or decoded frame | Alive/reload pass |

The20ms version alternated endpoints0x84/0x85 and collected about46 transfers/s
on the active endpoint. A quiet endpoint can throttle active-endpoint draining
enough to hide a later command reply. The1ms version collected77/154/70 good-FCS
frames across its post-START windows and recovered both START and final STOP
ACKs. This is evidence of a **receive-loop confound**, not evidence that the
earlier commands were refused or the firmware stopped replying. No window hit
its transfer cap (256 originally,512 after the correction). All observed frames
and replies came through endpoint0x84; none came through0x85.

The MT7961 silence in these initial windows remains ambiguous, especially with
no normal ch36 frames. No START was issued to that chip at that checkpoint. Older AP-EXT
experiments are separate and must not be counted as validation of the CE route.

[Sanitized evidence](../research/evidence/radar-detector-2026-09-05.json).
Only counts, timing, fixed command status and event shapes are retained. Raw
ambient identities, frame bodies and detector payloads are not published.

## MT7961: a silent command still changes receiver state

Following the string-identified NDS32 entry`0x00961422` (`rdmCmdRddCtrl`) gives
an independent way to test the CE route without requiring an ACK. This is **not**
the earlier numerically matched`0x0095c90e` function, which belongs to MU control.

- START/control1 calls region setter`0x00960f04`, stores enable1 at
  GP+`0x34214`, then calls`0x00960dcc` (`rdmRddStart`).
- STOP/control0 checks that enable byte, clears it, and calls`0x00960e88`
  (`rdmRddStop`). The selected region byte at GP+`0x34215` is retained by STOP.
- Runtime GP is`0x02003000`, so one fixed read at`0x02037214` covers both bytes.
- The start helper asks`0x0096bcca` for its buffer. That calls allocation lookup
  `0x0093e7f8` with selectors0/3/0. The lookup walks18 records of24 bytes at
  GP+174232=`0x0202d898`, compares fields at0/8/20, and returns base/size at12/16.
- A normal-boot read finds exactly one matching record: base`0x00401c00`,
  size1024. Thus **missing allocation is not the explanation** in this control.
  No raw buffer contents are read and no host-supplied DMA address is used.

`research/legacy_rdd_state_probe.py --enable-passive-detector` checks the exact
allocation and an inactive state before the single FCC-profile START, then sends
STOP and reloads normal firmware. On2026-09-05 at14:58 UTC:

| Phase | State word | Enable byte | Region byte |
|---|---|---:|---:|
| Normal boot / initial STOP | `0x000` | 0 | 0 |
| CE8F START | `0x101` | 1 | 1 |
| CE8F STOP / cleanup STOP | `0x100` | 0 | 1 |
| Full normal reload | `0x000` | 0 | 0 |

There are **zero USB transfers, ACKs or pulse events** in all four one-second
windows, yet the state follows the request and cleanup restores it. This
establishes the CE8F-to-RDD-handler connection, not a functioning pulse sensor:
the host-state byte is set before lower-level capture setup, whose errors are
not propagated through that byte. Hardware register readback is the next check.
[Allocation/state evidence](../research/evidence/legacy-radar-state-2026-09-05.json).

## MT7961 hardware arming and STOP residue

The guarded probe's `--registers` option adds nine fixed register reads, never
direct writes. ROM callback`0x00830504` writes field key`0x240020` to5 for enabled
and0 for disabled. The shared mapper`0x00830350` maps domain24 through table
`0x0084cb88`/base`0x83080000`, and domain27 through table`0x0084c9e4`/base
`0x830a0000`. Read-only metadata resolution validates eleven exact keys.

| Field / register | Before | START | STOP | Reload |
|---|---|---|---|---|
| Detector mode,`0x83082004` bits8:6 | 0 | **5** | 0 | 0 |
| PHY selection,`0x83080038` | 0 | `0xc` | `0xc` | 0 |
| Capture field`0x270000`, register`0x830a5000` | `0x80` | `0x81` | `0x81` | `0x80` |
| Capture field`0x270020`, register`0x830a5008` | `0xf0` | `0xf9` | `0xf8` | `0xf0` |
| Buffer begin,`0x830a500c` | 0 | `0x00401c00` | retained | 0 |
| Buffer end,`0x830a5010` | 0 | `0x00401e00` | retained | 0 |
| Producer word,`0x830a5014` | 0 | `0x00401c00` | unchanged | 0 |

The buffer-begin callback`0x008304d6` initially writes start and start+511;
the later end callback`0x008306f8` explicitly overwrites the end register with
start+512, matching live readback. The allocation is1KiB for two512-byte bands;
only band0 is tested. No host DMA address or raw capture-buffer data is supplied.

Registers`0x83080014` and`0x830a2030` stay0 and`0xa00`. The probe observes no
normal frames or pulse events in the short ch36 windows. Thus it establishes
**real hardware configuration**, not pulse sensitivity, a working sampling clock,
or usable interference measurements. The producer does not move beyond the start
address in this run. STOP disables detector mode and capture field270020 but is
**not a complete register rollback**; full normal reload restores all nine reads
exactly, and alive checks pass.

## MT7925 prerequisite and host-state check

The corrected [command table](COMMAND_TABLES.md) identifies UNI19 entry
`0xe009ea2c`, tag0 callback`0xe009f098`, START helper`0xe009ea8c`, and STOP helper
`0xe009eb62`. Tag0 sets its host-enable byte before calling the lower helper.
The latter requires byte GP+62669=`0x02221ccd` to be nonzero, then obtains and
checks an on-chip buffer. **No prerequisite byte or internal pointer is forced.**

`rdd_receive_probe.py --enable-passive-detector --state` observes the prerequisite
byte1 throughout. The band0 host-enable byte at GP+121776=`0x022303b0` follows
0→1→0, and remains0 after reload. All three command ACKs are status0; no pulse
events are observed. This rules out the first byte prerequisite being zero in
this run; it does not prove the later buffer/hardware setup completed.

The Andes inspector now annotates unsigned GP-relative byte loads/stores using
the pinned vendor [opcode/operand definitions](https://github.com/andestech/binutils/tree/dd22be9a0ef80fde64e65e57d25f988a1ea1460f/include/opcode).
These remain textual annotations, not new Ghidra pcode or a complete ISA decoder.

[Hardware mappings and both-chip readback evidence](../research/evidence/radar-hardware-2026-09-05.json).

## What would turn this into a measurement?

Complete the newer chip's hardware map, and test whether ordinary controlled
Wi-Fi reception coexists with the armed older-chip detector. No random register
sweep, threshold guessing or emulated radar is needed. Ordinary traffic and
successful command ACKs are not a positive control
for radar sensitivity. Even real pulse reports would need separate validation
before being labeled radar, non-Wi-Fi interference, or a calibrated power source.
