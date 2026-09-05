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

## Follow-up: boot phase, ROM GP and a live dispatch table

[Follow-up evidence](../research/evidence/mt7925-startup-controls-2026-09-05.json).
The entire header-defined r0 executable region (77,200 bytes, not a full image)
was subsequently read locally: SHA-256
`fb289b9ae215c5977e1879bbbed286e3e8ffd75bdbfece13bfc4b8fee5dc405e`.

**Decryption timing control:** temporarily wrapping the host's `start_firmware`
call allowed 256-byte reads immediately after download and before start. Entry
and r1-start bytes exactly matched the ciphertext container then (`FW_STATE=1`).
After normal start (`FW_STATE=3`), entry reverted to the repeatedly observed
plaintext hash. The normal start call was always issued, the wrapper removed,
and normal firmware reloaded afterward. This establishes a phase-dependent
change, not recovery of a key or a general-purpose decryption API.

The candidate startup string addresses did **not** contain ASCII strings. Their
role remains data/argument pointers, not established format strings. Several
other candidate data windows were zero/structured/non-text; no broad data dump
or application/ambient-frame capture was made.

The callback chain does cross-check:

| RAM-startup callback slot | ROM jump stub | Stub target |
|---|---|---|
| `0x00828478` | `0x0084904c` | `0x0080eb9e` |
| `0x0082847c` | `0x00849050` | `0x0080ebc0` |
| `0x00828480` | `0x00849054` | `0x0080ebe2` |

**GP is grounded in ROM, not guessed:** ROM entry `0x0080000c` calls
`0x0080cb54`. After zeroing registers, it executes `auipc gp,0x1a06` at
`0x0080cb90` and `addi gp,gp,-0x390` at `0x0080cb94`, setting **`0x02212800`**.
The preceding guesses `0x02200000`, `0x02212630`, and `0x02210000` did not produce
the expected table layout and are rejected, not alternative supported mappings.

RAM helper `0x0090d00a` copies data backward from GP+464 to GP+776, ending at
GP+113200, a **+312 / `0x138` relocation**. It clears the source gap and BSS up to
`0x02268ea4`. Do not apply this offset blindly to all pointers or regions.

The routine at `0x0091719e` reads a 16-bit key at buffer+`0x34`, searches 30
eight-byte entries beginning at GP+536, and calls a non-null matched handler.
The miss path at `0x009171da` constructs `0xc00000bb`. The registration routine
at `0x009170b2` clears 240 bytes and installs the same key/handler pairs seen in
live RAM at **`0x02212a18`**:

| Key | Handler |
|---:|---|
| `0x05` | `0x009169b0` |
| `0x06` | `0x00916944` |
| `0x07` | `0x0091689c` |
| `0x08` | `0x0091681e` |
| `0x12` | `0x0091678a` |
| `0x13` | `0x0091670a` |
| `0x14` | null |
| `0x16` | `0x0091679a` |

Remaining entries were zero. Independent ROM callback operand reads at
GP−41124 yielded `64,4,128`, coherent nonzero values where an earlier GP guess
returned zeros. Registration stores plus live pointers are the stronger GP check.

**This does not identify the rejected UNI 0x32/0x46 path.** The table's keys are
not established wire CIDs or TLV tags. Its key-8 handler expects a much larger
request, copying 268 bytes from buffer+`0x40`; it is not justified to relabel it
as the public eight-byte RX-statistics query. No new requests were sent from
these inferences. Next: trace this module's caller/registration context and the
actual measurement handlers, retaining the distinction between internal keys
and host commands.
