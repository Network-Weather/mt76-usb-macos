# MT7961 instruction-set correction — 2026-09-05

The earlier Xtensa identification in this project was wrong. The tested plaintext
MT7961 RAM image decodes coherently as **Andes NDS32**, little-endian data with
big-endian mixed 16/32-bit instructions. This correction affects disassembly and
its derived claims, not the independently tested USB protocols or table bytes.

## Independent checks

Ghidra 12.1.3, built-in `NDS32:LE:32:default`, raw region imports at their declared
addresses; no vendor processor extension. Firmware SHA-256:
`b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`.

| Site | NDS32 result |
|---|---|
| Region 0 entry 0x00915000 | Three instructions construct 0x00915b34 and jump there |
| Startup 0x00915b34 | Stack prologue, direct initialization calls and indirect calls |
| Spectrum EXT 0x56 handler 0x009214c8 | Null check, matching push/pop, bounded body through 0x00921533 |
| IPI EXT 0xa3 handler 0x00961422 | Reads command bytes, checks band < 2, dispatches subcommands |
| MIB EXT 0x5a handler 0xe02767c0 | Null/length checks, parameter accesses, matching push/pop/return |

Handler addresses were found from coherent little-endian dispatch tables before
this ISA test. Agreement across startup, separate functions and two code regions
is much stronger evidence than the earlier isolated Xtensa instruction match.
The old Xtensa import generated extensive implausible branches and register use;
its function/instruction counts and claimed vendor-TIE proportion are invalid.

This also agrees with Wegemer and Mantovani's original
[Nullcon presentation](https://nullcon.net/wp-content/uploads/2026/04/Unlock-hidden-Superpowers-in-MediaTek-WiFi-Chips.pdf)
(firmware overview, page 7). Their discussion of global-pointer-based references
is a useful lead for recovering strings that direct pointer scans missed.

## Reproduction and limits

Import extracted region 0 as raw binary at 0x00915000 and region 3 at 0xe0270000
with `NDS32:LE:32:default`. Use a new project; do not overwrite the earlier import.
Disassemble the addresses above. The ten entry bytes are
`46 00 09 15 58 00 0b 34 dd 00`; decode as `sethi`, `ori`, `jr5`, not a
three-byte Xtensa jump. The firmware container itself is not a flat code image.

Frequent `ex9.it` instructions refer to an instruction table. Stock Ghidra's
installed NDS32 implementation represents these as opaque p-code operations.
Do not infer complete call graphs, register liveness or decompiler correctness
until that table is resolved. Global-pointer-relative strings also need the real
GP value. See the upstream
[EX9 implementation discussion](https://github.com/NationalSecurityAgency/ghidra/discussions/6612).
No firmware modification, device writes or blob redistribution is involved.

The initial IPI disassembly already narrows useful work: command 1 selects a
bounded detector option (< 7) and calls an initializer, while command 0 consults
a firmware state byte before stopping. This is a lead, not proof the histogram
sampler works. Hardware validation remains necessary.
