# Band-config queries and receive-vector reporting

**MT7925 exposes three real PHY threshold bytes through normal-mode UNI
queries, but its EDCCA enable reply is synthesized by a stub.** The receive-vector reporting switch in the same
command family acknowledges off/on/off but did not produce a new record type
on either dongle. No new normal-mode CFO/SNR interface is claimed.

Firmware pins are the same as [station CSI](STATION_CSI.md) and
[MT7961 PHY counters](PHY_RX_COUNTERS.md). Protocol facts come from Motorola
gen4m `8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`,
`include/nic_uni_cmd_event.h`: `UNI_CMD_ID_BAND_CONFIG=0x08`,
EDCCA enable/threshold command tags5/6, and `UNI_EVENT_ID_BAND_CONFIG=0x21`.
Only protocol facts are used; no vendor implementation is copied.

## EDCCA: a configuration read, not a noise measurement

`research/edcca_query_probe.py` sends two pairs of **queries only** after a fresh
normal firmware boot and receive-channel setup:

- Command UNI08, exact option3 (`ACK | UNI`, **without SET**).
- Band0/reserved4 + tag5 or6/length8 + zero4: `<4xHH4x>(tag,8)`.
- Matched EID`0x21` has a12-byte body: reserved4, event tag/length8, data4.
- **Event tags differ from request tags:** request5 yields event0, request6 event1.
- Event0 returns enable byte0/1 and three zero bytes. Event1 returns the three
  threshold bytes plus a request-echo byte, observed0 (not a fourth threshold).

The raw USB transfer includes20 extra bytes beyond the descriptor's declared
event size. These are not a second TLV or part of the EDCCA payload. The parser
bounds the event by RXD length and never interprets/exports that trailing data.
It validates packet type, sequence, event ID, exact body length, reserved bytes
and expected event tag. Unknown shapes remain shape-only; an ACK is not config.

| Receive configuration, 2026-09-05 | Enable | Signed-byte triplet |
|---|---|---|
| Channel36 /20MHz, 11:27:04 UTC | 1 | −69, −66, −63 |
| Channel1 /20MHz, 11:27:28 UTC | 1 | −65, −62, −59 |
| Channel36 /80MHz | 1 | −69, −66, −63 |
| Channel36 /160MHz | 1 | −69, −66, −63 |

Each boot's repeated query pair agrees. All matched-event checks, alive checks
and reloads pass. These are **firmware-reported configuration values**, not
observed RF power, a calibrated energy-detection boundary, or proof that CCA
asserts at exactly those levels. The array looks compatible with width-indexed
thresholds, but its exact per-entry width mapping and hardware gain corrections
are not established by this experiment. In particular, a160MHz receive setting
still returns **three**, not four, values. No160MHz-specific threshold is inferred.

No EDCCA enable/threshold SET is exposed by this tool. No TX, RF-test mode,
direct MMIO writes or raw replies are exported.
[Sanitized EDCCA evidence](../research/evidence/edcca-queries-2026-09-05.json).

### Handler provenance and physical cross-check

The actual dispatcher checks packet option bit2 at`0xe0031144`, searches twelve
12-byte records at GP+9328 =`0x02214c70`, and selects the SET pointer at+4 or
QUERY pointer at+8. Its event builder explicitly uses EID`0x21` at`0xe00311a0`.
A bounded144-byte live table read matches these callbacks:

| Command tag | SET callback | QUERY callback |
|---:|---|---|
| 1, RX-vector reporting | `0xe0030dda` | null |
| 5, EDCCA enable | `0xe0030e14` | `0xe0030e70` |
| 6, EDCCA thresholds | `0xe0030eb4` | `0xe0030ef0` |
| 7, MAC timeout fields | `0xe0030f28` | `0xe0030f60` |

The enable query zeroes an eight-byte buffer and calls`0xe0078ebc`, which calls
`0xe0057c4e`. That leaf is simply **return0**: it never fills the buffer. The
query's bit8 test on that zero buffer then takes the branch that stores enable1
at`0xe0030ea8`. Consequently **enable1 does not establish hardware EDCCA enable**
on this firmware. Earlier live evidence records the wire value accurately, but
it must not be promoted to a verified hardware state.

The threshold path is different: `0xe0030ef0` →`0xe0078ecc` →`0xe0057c52`.
The read branch at`0xe0057cde` extracts four unsigned bytes into four halfwords:
band0`0x83088554` bits7:0,15:8,23:16, and`0x83088608` bits7:0. The UNI wrapper
copies only the first three, then **echoes request TLV byte7** into the last
reply byte at`0xe0030f1c`. Thus the extra internal field is inaccessible through
this query wrapper; it is not that echoed byte. No per-width meaning is yet proven.

`edcca_query_probe.py --registers` reads only those two exact registers before
and after the query pairs. Fresh channel36/160MHz and channel1/20MHz runs at
11:41–11:42 UTC both show stable registers and exact triplet agreement:

| Channel | `0x83088554` | `0x83088608` | Four extracted signed bytes |
|---|---|---|---|
| 36 /160MHz | `0xd8c1bebb` | `0x00000000` | −69,−66,−63,0 |
| 1 /20MHz | `0xd8c5c2bf` | `0x00000000` | −65,−62,−59,0 |

This establishes register provenance, not calibration or the meaning of the
zero fourth field. Both runs finish normal reload/alive checks. The address
`0x83088608` is also inside a **different chip's** MT7961 histogram window:
never transfer the MT7961 bin interpretation to MT7925 merely by address.
[Hardware cross-check evidence](../research/evidence/edcca-hardware-2026-09-05.json),
[live callback table](../research/evidence/band-config-dispatch-2026-09-05.json).

## Important framing-control correction

The initial exploratory script passed `query=True` through both chip helpers.
The base MT7961 `uni_option` **ignores that argument and returns option7**,
whereas MT7925 correctly returns option3. Therefore the initial MT7961 tag1/5/6
trials were **zero-valued SET-framed controls, not queries**. They returned
status0; whether those values reached hardware was not verified. No TX occurred,
and each trial completed a normal firmware reload and alive check. They are not
evidence of configuration readback or harmlessness of arbitrary threshold writes.

The corrected exploratory run explicitly forced option3 only for UNI08 and
asserted it before sending. MT7961 again returned only a command-result status0,
not the MT7925 configuration events. The committed EDCCA reader is consequently
**MT7925-only** and rejects option7 before any command. It does not alter the
production driver's framing conventions. Regression tests pin this distinction.
[Sanitized framing controls](../research/evidence/band-config-framing-2026-09-05.json).

## RX-only vector report switch: accepted, no new stream observed

The same pinned header defines UNI08/tag1/length8 as RX-vector-enable byte,
TX-vector-enable byte and two reserved bytes. `research/rxv_report_probe.py
--chip mt7925 --enable-reporting` (or `mt7961`) sends RX-only off/on/off using
option7; the TX-vector enable stays0. It uses passive channel1/20MHz windows,
one second/512 transfers each, then sends OFF and fully reloads firmware.

| Receiver | Good-FCS frames: off / on / off | Descriptor group mask | Other record types |
|---|---|---|---|
| MT7925 | 76 /90 /92 | `0x17` throughout | None |
| MT7961 | 93 /76 /52 | `0x07` throughout | None |

All controls acknowledged status0, no transfer ceiling was hit, and cleanup
passed. This was not an idle/no-reception negative. However, it covers only the
normal packet endpoint/configuration tested: a separate routing prerequisite,
an ineffective command path or a different reporting consumer remain possible.
It does not rule out every receive-vector mechanism. The finite RF-test log and
MT7961's independently validated Group5 DMA bit remain separate working paths.
[Sanitized report-switch evidence](../research/evidence/rxv-report-switch-2026-09-05.json).

`--both-endpoints` then repeated this control while alternating bounded reads
from the two bulk-IN endpoints resolved from each device's USB descriptors,
packet`0x84` and command-response`0x85`. MT7925 received43/43/43 good-FCS frames;
MT7961 received42/45/46. Every transfer came from`0x84`, none from`0x85`, with
unchanged group masks and no new record type. OFF/reload cleanup passed again.
This closes the simple alternate-existing-endpoint hypothesis for the tested
configuration, not firmware routing configurations that were never enabled.
[Dual-endpoint evidence](../research/evidence/rxv-report-endpoints-2026-09-05.json).

### The RX-vector setter really reaches hardware

MT7925 callback`0xe0030dda` passes normalized TX/RX booleans and band to
`0xe0079e50`, which uses the live callback at GP−9216+40 =`0x02210428`
→ROM`0x0082a21e`. The first argument4 is a **varargs argument count**, not a
register domain. Band0 keys are`0x620` (TX) and`0x621` (RX), domain0.
Domain0 mapper`0x0082e6ea` uses table`0x0084c9f8`; the exact record at`0x84cb80`
points to`0x84cd6c`, offset`0x14`, five fields. The first two resolve to
**`0x820e3014` bits8 and7** respectively. This is a ROM-derived mapping, not an
assumption from another chipset's ARB layout.

`rxv_report_probe.py --chip mt7925 --enable-reporting --both-endpoints --registers`
now reads that exact register before/after each window. Fresh normal boot gives
`0x1`; RX-only off/on/off gives **`0x1 →0x81 →0x1`**, stable throughout each
window. TX bit8 remains clear. Good-FCS frames are42/42/43, all on0x84, with no
new stream and unchanged Group5. Reload returns0x1. Thus an ineffective command
is no longer the explanation on MT7925; a further start/routing dependency remains.
[Hardware report control](../research/evidence/rxv-report-hardware-2026-09-05.json).

## A third query: MAC timeout configuration

Tag7 has three selectors0/1/2, a12-byte TLV and a16-byte body:
`<4xHHB7x>(7,12,selector)`. QUERY option3 yields matched EID`0x21`, reserved4,
tag7/length12, selector/reserved3, value32. The getter bounds selector≤2 and
all three paths return only a16-bit hardware field. No SET was exercised.

Callback`0xe0030f60` →`0xe0083b72` uses ROM read helper`0x0082a374` for
keys`0x1a0420`/`0x1a0440`, resolving through domain26 mapper`0x0082bd2c` and
table`0x84c094` to`0x820e40c8`/`0x820e40cc` low16. Selector2 uses ROM callback
slot`0x829d7c` →`0x82e2f8`, reading`0x820e40d0` low16 directly.

Pinned upstream mt76 `mt7996/regs.h` names the first two registers TMAC
CDTR/ODTR and their low16 fields `MT_TIMEOUT_VAL_PLCP`. The third field remains
unnamed here. This supports a timeout-configuration interpretation, **not**
measured latency, arrival time, RF range, or a promise that these units are µs.

`research/band_timeout_query_probe.py` exercises each selector twice and reads
the exact corresponding register before/after. Fresh channel36 and channel1
boots agree: selectors0/1/2 yield **462/120/208**. Full register values are
`0x006001ce`, `0x00380078`, `0x001c00d0`; all twelve query values match low16,
all registers stay stable, and reloads pass. This is a newly verified query
surface, not a new RF measurement or a reason to alter timeout settings.
[Sanitized timeout evidence](../research/evidence/band-timeout-queries-2026-09-05.json),
[field descriptor provenance](../research/evidence/band-field-descriptors-2026-09-05.json).

Next: resolve the separate RX-vector start bit and routing dependencies. Matching
literal−69 in unrelated rate-selection routines is not sufficient EDCCA provenance;
those candidates were rejected before the actual dispatcher was found.
