# Command-table field order: CID before handler

**The original `fw_triage.py --command-map` scanner had its two words reversed.**
Observed tables on both pinned images use `{u32 cid, u32 handler}`. Reading
`{handler, cid}` four bytes later associates a real handler with the **next
record's ID**, producing plausible but incorrect mappings.

This explains the earlier NDS32 “internal tags differ from wire IDs” finding for
RDD and MU control. That warned against the old mapping, but the discrepancy is
now explained by record alignment, not ID translation.

## Independent checks

| Image/table | CID-word address | CID | Following handler | Independent check |
|---|---|---|---|---|
| MT7961 r1 file layout, legacy CE | `0x02025cec` | `0x8f` | `0x00961422` | CE8F changes the exact RDD state traced from this handler |
| MT7961 r1 file layout, EXT candidate | `0x02018d2c` | `0x3a` | `0x00961422` | Same string-identified `rdmCmdRddCtrl`; EXT routing not requalified here |
| MT7961 r1 file layout, EXT candidate | `0x02018d24` | `0x40` | `0x0095c90e` | String-identified `muExtCmdMuTxRxCtrl`, not RDD |
| MT7925 live data | `0x0221c05c` | `0x19` | `0xe009ea2c` | UNI19 TLV dispatcher; tag0 matches the RDD request fields |
| MT7925 live data | `0x0221c064` | `0x33` | `0x0091719c` | Independently verified beamforming dispatcher and PFMU reads |
| MT7925 live data | `0x0221c0cc` | `0x4a` | `0xe003d3f0` | Independently verified CSI control and live reports |

MT7961 addresses above are **file-layout addresses**; runtime data relocation
adds`0x44c`. The MT7925 table was read live and is not adjusted. Raw firmware
windows stay local. The newer table was located by searching its declared data
region for the already verified CSI handler, then inspecting neighboring records.

The MT7925 RDD dispatcher checks tag<=2 and consults three eight-byte records at
GP+29352=`0x02219aa8`: tag0→`0xe009f098`, tag1→`0xe009ea24`,
tag2→`0xe009ea28`. Only source-defined tag0 is sent. Its callback checks the
detector-index byte at TLV+5, control at+4, RX selector at+6 and region at+7;
it also checks a newer byte at+8, kept zero by our request. Table presence is not
permission to invent tag1/2 payloads or assume their capabilities.

## Scanner correction and limits

The scanner now reads **CID then handler**, includes a complete final eight-byte
record (the old loop skipped it), and reports *candidate pairs*, not implemented
features. Tests cover adjacent records, exact-eight-byte input, trailing records,
reversed layout, truncation and misalignment.

The unanchored heuristic still uses pinned MT7961 code ranges. It does **not**
establish table boundaries, whether a table is CE/EXT/UNI, dispatch reachability,
or valid request payloads. EXT enum names in the report are numeric labels only.
An empty result proves only that no candidate pair was found in the scanned
bytes—not that a chipset or firmware lacks a feature. Earlier mapping counts and
handler assignments from the reversed scanner are superseded. Independently
measured live command responses remain valid.

[Sanitized mapping evidence](../research/evidence/command-table-order-2026-09-05.json).
