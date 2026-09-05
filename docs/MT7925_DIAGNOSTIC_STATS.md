# MT7925 UNI23 diagnostic report: command-object leak and misleading statistics

**Do not poll diagnostic tag3 in a long-running session.** Each report consumes
one initially available command-pool object without returning it. Three reports
leave an unrelated temperature command working; four make it fail. Ordinary
receive traffic continues. Normal firmware reload recovers the radio.

This is a maintainer-facing reproduction/pointer, not a firmware patch or a
production API. Pinned station RAM SHA256:
`23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`,
build20260813113118, MT7925 A9000 USB0846:9072,2026-09-05.
No TX, NVM writes, code patch, free-list mutation, hardware MIB reads, buffer
pointer exports or ambient packet exports occur in these tests.

## Reproduction and controls

UNI23 QUERY uses the ordinary option3. Both requests are eight bytes:
four zero reserved bytes followed by little-endian tag/length `(0,4)` or `(3,4)`.
Matched EID23/sequence replies are bounded by RXD length, not USB padding.
The published [gen4m command/event structures](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h)
name these basic statistics and diagnostic/bug report respectively.

| Fresh-boot control | Result | Unrelated temperature query |
| --- | --- | --- |
| Six basic tag0 requests | Six empty basic replies | Works,45°C |
| Six planned tag3 requests, no retunes | Four reports, fifth reply missing; loop stops | Fails with MCU timeout/error class |
| Exactly three tag3 requests | Three reports | Works,45°C |
| Exactly four tag3 requests | Four reports; no fifth diagnostic attempted | Fails with MCU timeout/error class |

Three earlier mixed-tag/channel-reversal runs each receive four diagnostic
reports before a later command/query failure. Their first failure records only
`McuError`, the second records `ValueError`, and the instrumented third records
a missing final basic response with no MCU events while54 ordinary good-FCS
records arrive. The initial probe redundantly retuned even an unchanged channel;
later probes avoid this. Fixed-channel, single-tag controls above eliminate that
retune/interleaving prerequisite. The failure is not a universal five-query cap:
the six-basic control succeeds.

### Direct free-list count witness

The request cleanup routine identifies three free-list heads and increments
head+8 when returning an object. Only those three scalar counts are read;
no list node, pointer chain, request payload or peer buffer is inspected.

| Read point | 0222efc0 | 0222ed84 | 0222e238 |
| --- | --- | --- | --- |
| Fresh normal boot | 4 | 4 | 16 |
| After diagnostic1 | **3** | 4 | 16 |
| After diagnostic2 | **2** | 4 | 16 |
| After diagnostic3 | **1** | 4 | 16 |
| After successful unrelated temperature query | **1** | 4 | 16 |
| After normal reload | **4** | 4 | 16 |

A matched fresh six-basic run holds all counts at4/4/16 after every query and
after its working temperature control. Reload also leaves4/4/16. This directly
demonstrates per-diagnostic resource retention, not merely absence of a reply.
Four is the number initially free in this configuration, **not a claim that the
underlying pool's total capacity is four**. Counts were not read in the earlier
four-report stall trial; depletion to zero there is a strongly supported inference.

## Source-supported ownership explanation

Runtime GP is02212800. The registered UNI23 handler at`e003bd10` walks exactly
six8-byte entries at GP+11524 = **02215504**. Live reads match:

| Tag | Handler | Meaning used here |
| --- | --- | --- |
| 0 | e00535f0 →e003bbba | Basic statistics |
| 1 | e0053538 | Not invoked |
| 8 | e0053578 | Not invoked; do not infer a public layout |
| 2 | e0053c6e | Peer statistics, not invoked |
| 3 | e00535f4 →e003ba76 | Diagnostic report |
| 6 | e0054090 | Not invoked |

Diagnostic builder`e003ba76` fills a200-byte TLV, then sets **a0=1** at
`e003bb7c`; only loads/stores follow before return. The outer statistics
handler preserves the tag handler's return in s0 at`e003bdc4`, builds/sends
EID23, and returns that value at`e003bd7e`.

Generic UNI dispatcher`e002f076` calls the handler and saves its return in s1.
At`e002f090`, result1 takes the special path through`e002f094`, **bypassing**
the ordinary `e002f054..058` call to`e0028a48(original_request,1)`.
For basic tag0, builder`e003bbce` returns0 instead.

Cleanup`e0028a48` clears owned buffer pointers, calls`e00779dc` on non-null
buffers, relinks the object onto a free list at`e0028aa4..aac`, then increments
the free count at`e0028aae..ab2`. Its heads are GP+116664,GP+116092 and
GP+113200; those yield the three scalar count addresses above.

**Likely defect:** a synchronous diagnostic reply propagates a pending/special
return value, leaving the original request owned rather than returning it.
The special result1 branch and missing cleanup are traced; calling this exact
constant "pending" is an ownership interpretation, not a recovered firmware
enum. No runtime branch trace, patch-and-retest, or complete allocator audit is
claimed. No firmware code or instruction bytes are distributed.

## What the reports actually provide

Basic tag0 returns only a four-byte `(tag0,length4)` TLV, with no counters.
This matches its entire builder at`e003bbba..bbd8`, not the published full
basic-statistics structure. **Empty is unsupported, not fourteen zero counters.**

Tag3 returns a200-byte TLV/version1. Its channel-state fields at TLV offsets
30/34/38/3c/40 hex follow primary/center1/center2/width/secondary offset.
Three fresh reversal runs each report6→11→6 correctly at20MHz. This is useful
firmware configuration readback, not proof of actual LO, occupied bandwidth or
RF performance.

Builder`e003bb84..bbb0` copies nine32-bit MAC values from RAM base0224c408:

| Source offset | TLV offset | Published field name |
| --- | --- | --- |
| 34 | 8c | RX MDRDY |
| 08 | 90 | RX FCS error |
| 0c | 94 | RX FIFO full |
| 10 | 98 | RX MPDU |
| 48 | 9c | RX length mismatch |
| 4c | a0 | RX primary CCA |
| 58 | a4 | RX ED |
| 24 | c0 | TX channel idle |
| 54 | c4 | TX CCA/NAV |

Offsets are hexadecimal. All observed copies match before/after source words,
but **all are zero despite ordinary good-FCS reception**. Endpoint equality is
not atomicity, and trivial zero matches do not validate a live survey-counter
feed. The code reads these RAM caches rather than draining the hardware MIB,
but their producer/refresh prerequisites remain unresolved.

The entire advertised PHY-error section at TLV5c..8b is zeroed by the initial
memset and never populated by this builder. Those fields are unsupported, not
zero PHY errors or a clean channel. Other zero-filled sections similarly must
not be interpreted as measured absence of activity. The parser exports only
the whitelisted channel/counter scalars and availability flags, never the
diagnostic's pointer fields.

## Guarded research reproducer

[`mt7925_diagnostic_stats_probe.py`](../research/mt7925_diagnostic_stats_probe.py)
verifies the image and live tag table, defaults to three diagnostics, reads only
the identified cache/count scalars, tests temperature afterward, and always
reloads. **Even the three-query default consumes objects until reload; it is not
a safe reusable polling primitive.** Four-or-more suites require the explicit
`--allow-command-stall` flag. Do not run concurrently with another device owner.
Any failed temperature control causes a nonzero process exit.

[All nine runs plus the independent tag-table read](../research/evidence/mt7925-diagnostic-command-leak-2026-09-05.json)
retain failed/partial runs, live counts, empty replies and recovery evidence.
Every normal reload succeeds. Production Python/C APIs are unchanged.
