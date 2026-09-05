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
| Table tag 0x56 handler 0x009214c8 | Null check, matching push/pop, bounded body through 0x00921533 |
| Table tag 0xa3 handler 0x00961422 | Reads command bytes, checks index < 2, dispatches subcommands |
| Table tag 0x5a handler 0xe02767c0 | Null/length checks, parameter accesses, matching push/pop/return |

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

## EX9 table and GP-relative references recovered

Startup routine 0x00915074 explicitly constructs **0x0096c7bc** and writes ITB.
That table is present in region 0. The independent, read-only
[`Nds32Inspect.java`](../research/ghidra/Nds32Inspect.java) expands its entries for
inspection and exposes operands omitted by stock Ghidra's `addi.gp` renderer.
EX9 J/JAL targets use address concatenation, not normal PC-relative addition;
the helper marks the corrected target separately. It does not inject decompiler
semantics or claim to repair the complete Ghidra analysis.

**GP candidate 0x02002bb4** resolves six independent `addi.gp` references to
matching format strings/function names, including `rdmCmdRddCtrl` and
`muExtCmdMuTxRxCtrl`. This is strong static inference, not a live CPU register read.
It yields direct ICAP-mode-guard and histogram string references:

- ICAP-mode guard reference: 0x00933de2.
- `rdmSetIpiHist` reference: 0x00961634.
- `rdmGetIpiHist` reference: 0x00961696.

**Important table-label correction:** tag 0xa3 at 0x00961422 resolves to
`rdmCmdRddCtrl`, while tag 0x3a at 0x0095c90e resolves to `muExtCmdMuTxRxCtrl`.
Therefore those internal dispatch tags cannot be directly equated to same-numbered
wire EXT IDs. Earlier numeric matches alone do not identify handlers. The measured
wire command responses remain valid; static table naming requires an actual
dispatch-path cross-check. In particular, do not use the initial table-tag 0xa3
disassembly to construct histogram commands.
