# MT7925 loaded code is readable — 2026-09-05

The encrypted on-disk container is **not a barrier to all MT7925 firmware
inspection**: bounded USB `MT_VEND_READ_EXT` reads (`dev.rr`) return stable,
structured code after the normal firmware loader runs. No decryption key was
recovered, no firmware was modified, and no full-image dump is claimed.

Device: Netgear A9000 `0846:9072`, chip `0x7925`. RAM build `20260813113118`,
SHA-256 `23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`.
[Sanitized read evidence](../research/evidence/mt7925-loaded-code-2026-09-05.json)
contains addresses, sizes, hashes and reload/alive checks, not firmware bytes.
Raw windows remain local. No RF test mode or TX was used for these reads.

## Entry and instruction-table setup

Two fresh boots returned the same 256-byte window at `0x0090d000`:
`dba5416070800168e618fc3b3258dd2b13332587a97fa779f2864d0afafcb26f`.
It differs from the corresponding encrypted container bytes. RISC-V RV32
decoding gives `auipc t0,0; addi t0,t0,0x772; c.jr t0`, targeting `0x0090d772`.
The following helper at `0x0090d00a` contains a coherent backward word-copy loop.
This is a different ISA from the MT7961's NDS32; do not reuse its decoder or GP.

A bounded startup window at `0x0090d770` contains a load of `0x009171e8` and a
write to CSR `0x800` at `0x0090d77e`. Andes identifies that CSR as its instruction
table base in its [QEMU CoDense proposal](https://lists.gnu.org/archive/html/qemu-riscv/2021-10/msg00553.html).
A 4096-byte read at that address contains plausible full-width instructions.
Its hash is `d24962d144ffa01a10c0a19b5192e4afa1fccdccc179dfbe126274b2a68cb153`.

## A useful, still experimental compressed-instruction interpretation

The observed `0xa002` compressed family overlaps stock `c.fsdsp` decoding.
It is **not** either upstream Andes opcode (`0x8000` / `0x9000`). However, using
the ten-bit index permutation documented for NEXEC.IT expands several startup
sites into mutually consistent register setup:

| Site | Candidate table index | Expanded operation | Following use |
|---|---:|---|---|
| `0x90d782` | 674 | `lui s6,0x828` | callback load at `s6+0x480` |
| `0x90d788` | 432 | `lui s1,0x20` | later argument `s1+0xe` |
| `0x90d78c`, `0x90d794` | 900 | `lui a5,0x828` | callback loads at `+0x478`, `+0x47c` |
| `0x90d7a8`, `0x90d7be` | 176 | `lui a1,0x2270` | candidate string arguments `+0x110`, `+0xd4` |

These are local corroborating controls, not an architectural proof for every
opcode. Halfword `0x93c4` at the entry target remains unresolved; treating it as
upstream NEXEC.IT produces an implausible startup operation. Bit 12 and wider
table variants are also unresolved. Do not infer full control flow or invoke
commands solely from this candidate decoder.

Opcode/operand facts come from the vendor-maintained
[Andes binutils headers](https://github.com/andestech/binutils/tree/dd22be9a0ef80fde64e65e57d25f988a1ea1460f/include/opcode),
not copied implementation. Index bits low-to-high come from instruction bits
`4,10,11,2,5,6,9,3,7,8`. A table entry is four little-endian bytes. EXEC.IT JAL
uses PC upper-bit concatenation, not an ordinary PC-relative JAL displacement;
AUIPC remains call-site-dependent. Our annotation is not decompiler semantics.

## Reproduce offline from locally retained windows

Import startup as raw binary at `0x0090d770`, language `RISCV:LE:32:default`,
without analysis. `research/ghidra/InstructionWindow.java` gives bounded stock
decoding, with an explicit custom-ISA warning. The experimental
`Mt7925AndesInspect.java` accepts start address, byte count (2..4096), and a
local file containing exactly the 4096 table bytes. Both are read-only.

Example post-script arguments: `Mt7925AndesInspect.java 0x0090d774 160 /tmp/table.bin`.
Start at `0x90d774` explicitly to skip, not explain, the unresolved entry halfword.
The inspector expands only the observed low-index candidate family, annotates
ADDIGP/LWGP operands, and stops at undecodable or unsupported high-index forms.
Other stock-decoded custom overlaps may remain: this is a research aid.

Next: validate the candidate string/callback addresses with bounded reads, resolve
startup/GP relocation, and follow actual MT7925 measurement dispatch paths. The
encrypted container alone no longer justifies calling those paths inaccessible.
