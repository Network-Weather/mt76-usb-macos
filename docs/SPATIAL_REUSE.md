# Spatial-reuse query surface

MT7925 accepts station UNI `0x25` capability and indicator queries without
configuration writes. **The indicator GET itself drains a shared accumulator.**
This is a working configuration/statistics transport, **not yet a working OBSS
activity measurement**: all eight reported counters stayed zero in the passive
controls below, despite normally decoded traffic.

Protocol facts follow Motorola gen4m
[`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/tree/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec),
`include/nic_uni_cmd_event.h` (`WH_SR_CAP`, `WH_SR_IND`, SR command/event tags),
`nic/nic_uni_cmd_event.c` (`nicUniCmdSR`), and `os/linux/gl_wext_priv.c`
(`priv_driver_get_sr_cap`, `priv_driver_get_sr_ind`). No vendor implementation
or firmware bytes are redistributed. Firmware pin and experimental instruction
decoder limitations are in [MT7925_LOADED_FIRMWARE](MT7925_LOADED_FIRMWARE.md).

## Wire contract and bounded probe

`research/spatial_reuse_query_probe.py --channel 1` (or `36`) boots normal
20 MHz monitor reception, sends CAP/IND/IND/CAP, then reloads normal firmware.
Each collection is capped at 0.5 seconds and 128 transfers. No SR configuration,
reset, RF-test mode, direct register write, or transmit command is issued.

| Query | Command tag | Reply tag | Fields after TLV header |
|---|---:|---:|---|
| Hardware capability/configuration | `0xc0` | `0xc0` | 20 one-byte flags |
| Hardware indicators | `0xcb` | `0xc9` | six unsigned16, two unsigned32 |

Both requests use exact QUERY_ACK option `3`, band0/reserved4 and
`<HHI>(tag, 8, 0)`. **Do not send command `0xc9`: it is NRT_RESET**, not the
indicator query. The request and event tag enumerations differ.

Replies are unsolicited EID `0x25`, sequence0, with exactly28 body bytes:
band0/reserved4 and a24-byte TLV. The probe bounds parsing by RX descriptor
length, excluding any USB transfer tail. Waiting only for the request sequence
would miss the useful reply. The firmware event constructor at `0xe0076332`
selects EID25, explicitly stores sequence0 at `0xe0076338`, calls the common
header builder `0xe002eed4`, then sends through `0xe00850e6`.

The capability field names represent **firmware-reported flags**, not a hardware
cross-check or a promise that the corresponding receive classification is active.
The indicator fields are non-SRG/SRG valid counts, intra/inter-BSS PPDU counts,
non-SRG/SRG valid PPDU counts, SR AMPDU MPDU and acknowledged MPDU counts.
The getter's copy-and-clear behavior is traced below; wrap handling, eligibility
and association prerequisites remain unverified. A zero reply must not be
interpreted as no neighboring BSS.

## Firmware cache and accumulator semantics

CAP handler `0xe0076354` builds tagC0/length24 and calls `0xe0076eaa`.
That helper copies20 bytes from `0x0225faf0 + band*20`; it does **not** read
hardware registers. A live40-byte control at this address contains two identical
boolean-flag blocks, matching the band0 query exactly.

IND handler `0xe007637e` loads the pointer at GP+112952 (`0x0222e138`), adds
`band*20`, copies20 bytes into the event at `0xe007639e`, then zero-fills those
same20 bytes at `0xe00763ae` before sending. The live pointer is `0x0225f828`.
This is a **read-and-clear software accumulator**, not a fresh direct hardware
snapshot. Exclusive ownership is needed: another reader could consume counts.
The observation run found zero in RAM before and after, and zero in the reply;
it therefore cross-checks the address/value, not nonzero read-clear behavior.
Both query collection windows in that extra run hit the128-transfer ceiling;
the valid replies still arrived, but those are shortened receive controls.

[Sanitized state cross-check](../research/evidence/spatial-reuse-state-2026-09-05.json).

An accumulator updater at `0xe0076f5a..0xe0076fc6` adds six16-bit and two32-bit
values into `0x0225f828 + band*20`, after a successful call to `0xe0064956`.
Those additions use ordinary halfword/word stores, not saturation: software
accumulation wraps at16/32 bits. Hardware counter width/read behavior and the
updater's scheduling prerequisites still need tracing.

## MT7961 legacy getters also work

`research/legacy_spatial_reuse_query_probe.py --channel 1` (or `36`) uses the
source-defined EXT `0xa8` **SET-framed GET** subcommands15 and18. This follows
the non-unified `priv_driver_get_sr_cap` / `priv_driver_get_sr_ind` calls;
do not substitute a generic QUERY bit or transplant MT7925's UNI framing.
Requests are zero-filled20-byte CAP and32-byte IND structures, band0. Only
those two getter subcommands are allowed. No SR setter/reset is sent; getters
may consume shared statistics, so this is not promised side-effect-free.

Replies are EID `0xed`, EXT EID `0xa8`, matching request sequence, followed by
a separate EXT command result `[0xa8, 0]`. The8-byte SR event header contains
subevent1 for CAP or4 for IND, with the remaining bytes zero in these controls.
CAP returns **20 boolean bytes**, not the older legacy header's12. They equal
the MT7925 flag sequence, but the probe leaves indices raw rather than wrongly
labeling the old header's AGG/MIB offsets8..11. IND matches the legacy24-byte
layout: two RCPI bytes, six16-bit counters, two padding bytes, two32-bit counters.
All RCPI/counter values were zero; no signal-unit claim follows from that.

Fresh ch1/ch36 runs each returned CAP/IND/IND/CAP and eight success statuses
in total. Channel1 received437 good-FCS frames; its two CAP windows hit the
transfer ceiling. Channel36 received only4 good-FCS frames, including two
empty query windows, so it is a weak RF control. All reload/alive checks passed.
[Sanitized legacy evidence](../research/evidence/legacy-spatial-reuse-2026-09-05.json).

## Live controls — 2026-09-05 UTC

Fresh normal boots on channels36 and1 each returned all four expected events.
Capability flags were identical before/after and across channels; notably SR and
non-SRG reported1, SRG reported0. Every indicator was zero in all four indicator
replies. Good-FCS traffic remained present in every query window:147 total frames
on channel36 and153 on channel1. Neither transfer ceiling was reached. Both
alive and full normal reload checks passed.

[Sanitized evidence](../research/evidence/spatial-reuse-queries-2026-09-05.json)
contains only firmware configuration/counters and aggregate frame counts, not
ambient identities or frames. The next lead is the actual counter source and
its prerequisites, not an arbitrary SR enable/reset sweep.
