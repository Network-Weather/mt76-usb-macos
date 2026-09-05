# Spatial-reuse query surface

MT7925 accepts read-only station UNI `0x25` capability and indicator queries.
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
Reset/read-clear behavior, wrap handling, eligibility and association prerequisites
remain unverified. A zero reply must not be interpreted as no neighboring BSS.

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
