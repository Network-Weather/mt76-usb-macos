# MT7925 live UNI dispatch table

**UNI0x32 receive statistics,0x46 engineering control and0x5d RTT have no handler
in the observed61-entry dispatcher.** Its miss path constructs `0xc00000bb`,
explaining the earlier replies on this pinned image without blaming individual
query selectors or requiring a speculative mode-entry recipe. This is specific
to the inspected firmware/dispatcher/state, not a claim every possible firmware,
legacy route or factory interface lacks those capabilities.

Pinned RAM SHA-256:
`23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`.
The read-only probe verifies the loaded instruction window and instruction table
against retained hashes, reads the exact count slot before/after the records,
and exports only command IDs, pointers and hashes. It **never calls a discovered
handler or sends a discovered command**.

## Dispatcher facts

The body at `e002ef70` reads the buffer pointer from outer+0x0c. Its option byte
is buffer+0x2b, sequence+0x27, length+0x20, CID+0x22 and routing byte+0x2a.
It requires the UNI option bit. For routing0/1 or3, it loads:

- Record count from GP+112160 = **`0222de20`**, observed61 and stable.
- Table base from GP+38716 = **`0221bf3c`**.
- Eight-byte records: u16 CID at+0, handler pointer at+4.

Loop `e002efac..e002efc6` tests the CID and non-null pointer. A matching handler
is called at `e002f076` with the original outer object. The miss path at
`e002efd8..e002efe2` constructs status `0xc00000bb` and calls response builder
`e002ef1c`, except for the SET-without-ACK case selected by the option bits.
This is static control flow supported by live code/table matching, not a runtime
branch trace. Experimental Andes annotations retain their usual limitations.

Selected records corroborate previously working interfaces:

| CID | Surface | Handler |
| --- | --- | --- |
| 0x22 | MIB | `e0053ac0` |
| 0x24 | Sniffer | `e0036b10` |
| 0x2b | Power report | `e00a1564` |
| 0x33 | Beamforming profiles | `0091719c` |
| 0x35 | Thermal | `e002dff0` |
| 0x36 | Noise histogram | `e0053786` |
| 0x40 | Fixed-rate table | `e0097a40` |
| 0x4a | CSI | `e003d3f0` |

The complete61 records are in [sanitized evidence](../research/evidence/mt7925-uni-dispatch-2026-09-05.json).
The implemented [UNI23 diagnostic tag3 leaks command-pool objects](MT7925_DIAGNOSTIC_STATS.md)
and must not be treated as a safe polling interface merely because it is registered.
Presence is not proof every tag/action is implemented or safe. Neither presence
nor a numeric resemblance authorizes exploratory requests with guessed payloads.

## Request-layout consequence for the noise histogram

The outer object retains the original command buffer. Thus the noise handler's
u16 at **buffer+0x34** is the standard48-byte UNI header plus4 reserved bytes:
the first TLV tag, not an extra offset22 bytes into the request payload. The
power dispatcher at `e00a157a` uses the same+0x34 tag location. Hexadecimal
instruction offsets must not be mistaken for decimal offsets.

This identifies the noise initializer's tag2 position. Its handler ignores the
other request fields and enters a timer-driven reset/enable path; it is **not a
read-only getter**. The subsequent [one-shot histogram test](MT7925_NOISE_HISTOGRAM.md#one-shot-firmware-event-now-works)
validates the request and two-array event on three fresh boots, with explicit
two-control activation, restoration and normal reload.

[`mt7925_uni_dispatch_probe.py`](../research/mt7925_uni_dispatch_probe.py) makes
1224 aligned reads at most:1100 code/table-hash reads plus two count reads and
122 record words. Its61-record cap ends before the next independently referenced
RAM object at `0221c124`. It refuses out-of-range/changing counts and wrong code
hashes. No TX or experimental register write; alive and normal reload pass.

## Registered HWCFG0x4e discards an unsupported readout result

Static follow-up on2026-09-06 finds another advertised-but-unimplemented path.
Registered handler`e00a19fe` loads the original command buffer at outer+0x0c.
Its body`e00a1a16..78` limits the u16 at buffer+0x3a to1200, allocates a1224-byte
response object, and calls`e007dccc` with two u16 request values from+0x38/+0x3a
and an output pointer at response-buffer+0x38. The code constructs EID0x4e
regardless of that getter's result; these offsets are internal buffer offsets,
not a validated public request recipe.

The getter's body`e007dcce` calls`e005f326`, then **overwrites a0 with0** at
`e007dcd2`. Callee`e005f326..32a` only constructs **0xc00000bb** and returns:
it does not read hardware or fill the output buffer. Thus this pinned path
suppresses the unsupported result. No output-buffer clearing is visible in
these routines, but allocator initialization was not audited, so this is **not
a demonstrated memory disclosure** or a claim about actual returned bytes.

No HWCFG query was sent. There is no reason to export a large unfilled reply
or interpret it as hardware configuration. The finding is a static maintainer
pointer, using the retained loaded image and experimental Andes annotations;
it is not runtime branch tracing or a validated parser. Unsupported two-byte
entry/exit instructions are explicitly skipped, not assigned invented semantics.

A separate [live code-only control](../research/evidence/mt7925-hwcfg-code-2026-09-06.json)
matches all three exact windows,152 bytes total, to the retained loaded image.
No HWCFG request is sent; alive and normal reload succeed. This verifies code
identity, not actual response contents or runtime branch coverage.
