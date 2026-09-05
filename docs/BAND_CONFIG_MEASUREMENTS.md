# Band-config queries and receive-vector reporting

**MT7925 exposes EDCCA enable and a three-byte threshold configuration through
normal-mode UNI queries.** The receive-vector reporting switch in the same
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
  threshold bytes plus an auxiliary byte, observed0.

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

Next: trace actual band-config handlers and reply construction, compare reported
thresholds with source-identified physical fields, and identify the reporting
switch's routing/enable dependencies. Matching literal−69 in unrelated rate-
selection routines is not sufficient provenance; those candidates are rejected.
