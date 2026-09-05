# MT7961 receive frequency-offset provenance

The CE `0xc8` statistics word19 is now traced to the firmware's signed receive
frequency-offset calculation, not merely named by similarity to a public header.
A receive-only hardware cross-check reproduces a nonzero result exactly. This is
**cached RF-test metadata**, not yet an ordinary-monitor per-packet CFO API or a
calibrated oscillator fingerprint. No transmission was needed for these controls.

## Pinned implementation

MT7961 RAM SHA-256
`b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`,
NDS32, runtime GP `0x02003000`, EX9 table `0x0096c7bc`.
The `testEngGetRXStatistics` string resolves to the routine at `0x00931212`;
its two logging references are `0x0093151a` and `0x00931632`.

For band0, cached vector base is GP+`0x3d808` = `0x02040808`.
The band1 alternative is GP+`0x3d758`; only band0 was read on hardware.
The vector update path at `0x00930a58..0x00930a86` copies an internal standalone
receive-vector record into the cache: 18 words, then two words, then four words,
then 20 words. The CFO source words are zero-based **20/21 of that record**.
They are not words20/21 of an ordinary USB Group5 block.

At `0x0093141c..0x00931488`, the statistics builder writes output offset `0x4c`
(word19 in the 72-word format). It reads:

| Cached source | Address | Used bits |
|---|---|---|
| word0 | `0x02040808` | frame bandwidth code, 10:8 |
| word20 | `0x02040858` | CFO low13, 31:19 |
| word21 | `0x0204085c` | CFO high7, 6:0 |

The assembled 20-bit value is sign-extended. The observed integer instruction
order is reproduced exactly by `decode_cached_fields`, including 32-bit wrap:

```text
raw20 = (word20 >> 19) | ((word21 & 127) << 13)
signed20 = sign_extend_20(raw20)
factor = u32(10_000_000 << (bandwidth_code + 1)) >> 20
result = u32(signed20 * factor) >> 4
if signed20 < 0: result |= 0xfff00000
```

For code0/20MHz, this equals signed arithmetic `floor(signed20 * 19 / 16)`.
The code uses a frequency-shaped constant, but does **not** implement an ideal
floating-point conversion. Wider codes and extreme input values retain the
firmware's integer behavior; they have not been validated as physical units.

Adjacent SNR output word49 is built at `0x0093189a..0x009318b2` from
word20 bits18:13 **without subtracting16**. This matters: the public mt7915
standalone-vector path uses the same CFO split but subtracts16 for its SNR.
Do not transplant that chip's conversion into MT7961 statistics.

## Hardware controls, 2026-09-05

**Protocol correction after the first three runs:** the extra reply word is an
echoed band selector, **not status**. The initial request followed an older public
eight-byte definition, but this firmware reads a third word. The trace and
corrected request are described below. Historical evidence retains the old
`candidate_status_u32` label to preserve what was observed; it must not be consumed
as a status or freshness indication.

`research/cfo_crosscheck_probe.py` uses the established receive-only RF setup on
channel36/20MHz, reads exactly the three addresses above, and compares five matched
CE `0xc8` responses in normal/RF RX/stopped phases. It always attempts STOP and
normal firmware reload. It exports only identified bitfields and comparisons;
no full vectors, addresses of heard stations, frames or payloads are retained.

The first fresh-boot control observed raw signed20 **-23948**, factor19 and
firmware result **-28439** (`4294938857` unsigned). Both live queries and the
first stopped query returned that exact word19. SNR bits were27 and word49 was27.
The second stopped response had extra word2 and zero statistics, while the
cache retained the older nonzero values. Normal mode returned extra word100/zeros.

A third fresh boot independently reproduced the nonzero correspondence with raw
signed20 **-24018**, converted **-28522**, and SNR field28. The cache changed during
the first live query (which correctly gets no exact-match verdict), then the next
live and first stopped queries matched both fields exactly. The second stopped
query again returned extra word2/zeros despite the nonzero cache. All three runs
passed alive/reload checks.

A second fresh boot had an all-zero cache and matching zero replies with echoed
band0. That is an **uninformative zero control**, not a second independently
observed nonzero measurement. An echoed band is not a fresh-sample indication.
The probe reports stable/nonzero cache separately; wrong-band replies and
changing caches do not receive exact-match verdicts. Sequential memory reads are
not an atomic snapshot, and an unchanged cache does not prove uninterrupted RX.

[Sanitized three-run evidence](../research/evidence/cfo-crosscheck-2026-09-05.json).

## Complete CE 0xc8 request and the apparent-status correction

Dispatcher `0x00933cee` reads the header at command+`0x40` as sequence u16,
header-band u8, flags u8, count u32. With flag bit0 clear, instructions
`0x00933d3a..0x00933d48` read an **additional u32 at request offset8**, truncate it
to u8, write it to reply offset8, and pass that same byte as the band argument to
`0x00931212`. That callee rejects bands>=2 at `0x00931218..0x0093122a`.
Consequently the historical values2/100 were not status codes: they were invalid
band arguments taken from a request field the eight-byte builder never supplied.
The historical little-endian field matches with echoed band0 remain real, but
the intermittent invalid-band zeros are not meaningful status/freshness behavior.

The corrected fixed-band0 request is **12 bytes**:

```python
struct.pack("<HBBII", sequence, 0, 0, 72, 0)
```

`sequence` is bounded1..5, flags remain0, count remains72, final band is0 (or1 for
a read-only band-isolation control). The untested alternate flag1 format is not
exposed. `legacy_rx_stats_probe.request` now always supplies this word; its parser
calls the echoed word `reported_band_u32`. The first complete-request control
returned band0 in all five replies, including normal mode and both stopped queries.
Its cache remained zero, so that run verifies header control, not nonzero CFO.

A second complete-request boot returned band0 in all five replies and reproduced
a **positive** raw signed20 value16217 → integer result19257. Both stopped queries
retained that exact result. A third boot used requested bands **0,0,1,0,0** without
changing the active RF receiver; replies echoed **0,0,1,0,0**. The band1 query used
its different CFO cache (zero), then both band0 stopped replies exactly matched
the band0 cached result `4294938849` (-28447). SNR word49 is the exported band0
SNR field even in that band1 response; do not relabel all fields by requested band.
All reload/alive checks passed.

[Corrected-request and band-isolation evidence](../research/evidence/rx-stat-band-2026-09-05.json).

## What this enables, and what remains

- The integer CFO and SNR field positions can be checked against actual firmware
  inputs, and the little-endian statistics layout has a stronger independent check.
- Source identity, sample age, calibrated Hz/dB accuracy and oscillator drift are
  not established. A single cached sample must not become a home-network diagnosis.
- MT7961 normal Group5 currently carries18 words; blindly indexing20/21 would
  read outside it. A separate standalone-report route or a proven alternative
  layout is needed for passive per-packet CFO.
  Follow-up: a [finite RF-test vector log](RX_VECTOR_LOG.md) now exposes separate
  reception records through scalar queries. It is not a continuous monitor stream.
- CE `0xc8` can drain counters; this diagnostic remains separate from acquisition.

Primary comparisons: local mt76 revision
`c5a3bd91aa735b669618610d5f0ebfa5786845a6`, `mt76_connac2_mac.h`
(`MT_CRXV_FOE_LO/HI/SHIFT`) and `mt7915/mac.c:mt7915_mac_fill_rx_vector`;
Motorola gen4m revision `8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`,
`include/chips/cmm_asic_connac2x.h` (C-RXC bandwidth bits) and
`os/linux/include/gl_qa_agent.h` / `os/linux/gl_qa_agent.c` (statistics field names/order).
These are cross-checks, not a claim that different chips share all layouts.
No firmware bytes or vendor implementation are copied into the repository.
