# Station CSI control and working MT7925 readout

## Current result: live 64-tone I/Q reports on MT7925

**CSI readout works on the attached A9000.** The missing step was a nonzero frame
selector: UNI 0x4a/tag2, index0/value **0x20**, before START on **band 0**.
This value was an explicit hypothesis from the firmware's six-bit selector and
the beacon frame-control type/subtype bits, not a blind command sweep. It produces
unsolicited EID 0x4a/sequence0 reports in normal unassociated monitor operation
on channel36/20MHz. Band1 with the same selector remains silent in this setup.

Two fresh-boot validation runs yielded **114 and 116 valid reports** during their
one-second START windows, versus zero in the preceding stop/configuration windows.
Each report contains **64 signed-16-bit I values and 64 Q values**. All payloads
were distinct within each run and most values were nonzero. RX indices were
0/1 in equal pairs (57/57 and 58/58), TX index0, receive-mode raw1/rate raw11,
band/CBW/DBW/segment raw0. Neither transfer ceiling was reached; STOP and normal
reload succeeded. One earlier run had one queued report immediately after STOP,
so instantaneous queue emptiness is not promised.

This establishes live CSI data delivery, **not** calibrated amplitude/phase,
distance, angle, channel impulse response, or mesh-topology inference. Maximum
chain commands sent **before START** both produced RX indices0/1; later controls
establish that sending count1 **after START** restricts reports to RX index0.
This is an output restriction, not proof of physically disabling an RF chain.
No association or transmission
was required. Transmitter addresses, coefficient arrays and their hashes are
never exported; the tool records aggregate cardinalities/ranges only.

```sh
python research/csi_control_probe.py --chip mt7925 --ack --band 0 --chains 2 --hardware --beacon-selector
```

[Sanitized CSI readout evidence](../research/evidence/csi-readout-2026-09-05.json).
The earlier negative controls below are retained to explain how this was found.

## Initial controls: acknowledgments without sample events

On 2026-09-05, the A9000's pinned MT7925 firmware accepted **UNI 0x4a** stop,
start and maximum-chain commands: matched EID 1 command-result events contained
status **zero**. This is distinct from both UNI 0x33 PFMU profile reads and the
older AP **EXT** 0x4a airtime command. Numeric command IDs are not interchangeable
between command families.

**No CSI samples were observed.** A successful command acknowledgment does not
prove the capture machinery was armed, that a firmware build implements every
tag, or that its defaults accept unassociated monitor traffic. No CSI, channel
matrix, calibrated SNR or spatial-location capability is claimed.

## Reproduction and bounded controls

Tool: [csi_control_probe.py](../research/csi_control_probe.py).
[Sanitized seven-run evidence](../research/evidence/station-csi-2026-09-05.json).
Hardware/firmware pins are the same as the
[loaded-code investigation](MT7925_LOADED_FIRMWARE.md).

```sh
python research/csi_control_probe.py --chip mt7925 --ack
python research/csi_control_probe.py --chip mt7925 --ack --band 1
python research/csi_control_probe.py --chip mt7925 --ack --band 1 --chains 1
python research/csi_control_probe.py --chip mt7925 --ack --band 0 --chains 2
python research/csi_control_probe.py --chip mt7961
```

Each run freshly boots normal firmware, enables monitor/sniffer reception on
channel 36 at 20 MHz, then sends stop / optional chain configuration / start /
stop. Each phase collects for at most one second plus the final 100-ms USB read,
with a 512-transfer ceiling. Cleanup sends stop again, then reloads normal
firmware. All observed alive and reload checks passed. No test-mode entry,
transmission, association, filter changes, nonvolatile writes, raw coefficients
or ambient frame output occurs.

| Control | Layout | Observed result |
|---|---|---|
| MT7925 stop/start | band byte + 3 reserved; u16 tag 0/1 + u16 length 4 | ACK option 7: status 0, both band selectors |
| MT7925 chain count | band/reserved; tag 3 + length 8; u8 count + 3 reserved | status 0 for band1/count1 and band0/count2 |
| MT7961 stop/start | CE 0x4c SET, 48 bytes: band, mode 0/1, zeroed remainder | EID 0xfd at each matched sequence; vendor labels this command-not-found |

The vendor bridge uses UNI **option 6**, SET without ACK. Our first no-ACK
MT7925 run reached its then-64-transfer ceiling and was inconclusive. A repeat
with the 512 ceiling consumed the full one-second windows (68/66/58 transfers)
without CSI or command-result events. The separate `--ack` diagnostic uses
option **7** and exposed the successful status replies. No-ACK silence was not
misclassified as rejection.

Band 1 is not a random sweep: the vendor private-command frontend explicitly
selects band 1 for a 5/6-GHz BSS and band 0 for 2.4 GHz. Both were tested because
the USB monitor's band selection and this station interface may differ. Neither
selector yielded EID 0x4a data events. Optional chain-count runs likewise had
no sample events and did not reach their transfer limits.

## Source pointers and next discrimination

Protocol facts, not copied implementation, from Motorola gen4m
[`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/tree/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec):

- `include/nic_uni_cmd_event.h`: command enum 0x4a, tags 0/1/2/3/4,
  packed stop/start/chain structures, unsolicited CSI event 0x4a/tag0.
  Its section comment still says 0x48; the enum and conversion code take priority.
- `nic/nic_uni_cmd_event.c:nicUniCmdSetCsiControl`: legacy-to-UNI conversion.
  Notably, it maps `CSI_CONFIG_OUTPUT_FORMAT` to the chain-count tag; names from
  the legacy API cannot be substituted directly for UNI tag numbers.
- `common/wlan_oid.c:wlanoidSetCSIControl`: SET/no-ACK choice.
- `os/linux/include/gl_csi.h`: 48-byte legacy control, modes, event fields.
- `include/wsys_cmd_handler_fw.h`: CE command 0x4c, CSI event 0x3c,
  and EID 0xfd command-not-found meaning.
- `os/linux/gl_wext_priv.c:priv_driver_set_csi`: band selection and CLI validation.

Next useful distinction: trace which state the accepted controls modify, then
resolve frame-type/filter defaults and the report path. The public frame-type
tag has an index and u32 value but does not establish their bit semantics here;
we have not guessed a catch-all mask or written arbitrary filter settings.
The weak MT7961-to-MT7925 test link also prevents a strong controlled-stimulus
CSI experiment for now. Initial offline tests cover request bounds, chip/band
layouts, matched status versus unsolicited data, rejection events, truncation,
ambient-frame filtering and absence of coefficient/address output.

## Loaded-code follow-up: control and report routines identified

The entire declared code region 3 (`0xe0026c00`, 594896 bytes) was read locally,
SHA-256 `a4fbdb6a78bb1e8847947f22f4310005e67b21e81f3b3e1eeff9d63e58a3e2cd`.
Its two earlier independently read PFMU windows match exactly. No code bytes are
published. A targeted static-data search found `whCsiLoadMemory`; its reference
at `0xe0061100` led to the CSI hardware helpers, but the symbol alone was not
treated as evidence of a reporting interface.

Independent instruction references identify the **report constructor at
`0xe009e396`**. It emits EID 0x4a with sequence zero, builds outer TLV tag 0,
and calls the nested-TLV builder `0xe009e222`. The observed inner tag order
matches the public CSI enum, including I/Q tags 6/7, DBW 8, channel index 9,
transmitter address 10, receive mode 12 and TX/RX indices 18. Report-state base
is `0x0225d994`; the transmitter-address field is deliberately not read or saved.
This establishes an implemented report-construction path, not its execution in
our live runs or correctness/calibration of hypothetical samples.

**Control handler `0xe003d3f0`** accepts band 0/1, walks TLVs at command-buffer
offset 0x34, and indexes a five-entry jump table at **`0x02215558`**. A live USB
read exactly matches all five decoded branch destinations:

| Tag | Branch | Observed instruction behavior |
|---|---|---|
| 0 | `0xe003d466` | clears selected configuration's mode; stop helper `0xe009e2de` |
| 1 | `0xe003d49a` | stores mode/enable=1 and band; hardware helper `0xe009e256` |
| 2 | `0xe003d4c4` | validates index <=3, stores one selection byte, marks that index configured |
| 3 | `0xe003d4ec` | stores chain byte and a configuration flag |
| 4 | `0xe003d4fa` | delegates filter operation and supplied address to `0xe00611d4` |

There are two **14-byte configuration records at `0x02239760` and
`0x0223976e`**. The optional `--state` probe reads only this fixed 28-byte
configuration array, not report/sample/address buffers. Both records remained
all zero before/after accepted stop, chain and start commands in two fresh-boot
controls (band0/count2 and band1/count1). This **does not prove the handler is
idle**: CPU-cache/USB visibility, alternate dispatch, or another unmet condition
remain unresolved. The live jump table corroborates the address derivation, but
does not by itself establish coherence of subsequent RAM reads. The MMIO controls
below subsequently establish real hardware changes despite these zero RAM reads.

An independent read-path control used upstream `mt7925_mcu_regval`, UNI 0x0d
QUERY, BASIC tag0/length12 and its 20-byte union-sized payload. EID 6 returned
a valid matching hardware-status register value for `0x7c0600f0` (3), but the
four attempted CSI RAM addresses returned no valid TLV/address match. Those
responses are **not accepted as zero CPU-memory values**. Transfers were 1548
bytes with declared RX length 1536; only the recognized first TLV is meaningful.
No register writes or RAM-access bypass was attempted through that API.

The hardware-enable helper's field keys are `0x001302c0/2c1` plus band<<16;
frame-selection keys are `0x001302c7/2cb` plus band<<16 minus index. Its live
field callback at `0x02210428` points to ROM `0x0082a21e`. Further callback
tracing is underway before naming or probing the corresponding MMIO registers.

[Sanitized state/static evidence](../research/evidence/csi-code-state-2026-09-05.json)
contains pointers, code hashes, configuration snapshots and matched-event shapes,
not code/sample bytes. The Andes annotator now renders GP-relative word stores
from pinned upstream operand definitions; it remains annotation-only and does
not resolve all custom instructions. Twenty offline CSI-probe tests pass.

## CSI commands demonstrably change band-specific hardware

ROM callback `0x0084581e` performs a read/modify/write of bit 29 at
**`0x820e5060 + (band << 16)`**, using the enable argument. This address was
derived before probing. The new `--hardware` option reads only the two fixed
registers; it never writes MMIO directly. Two independent fresh-boot runs give:

| Phase | Selected band register | Other band register |
|---|---|---|
| normal monitor before | `0x20000000` | `0x20000000` |
| stop before | `0x00000000` | `0x20000000` |
| maximum-chain command | `0x00000000` | `0x20000000` |
| start | `0xe0000000` | `0x20000000` |
| stop after | `0x40000000` | `0x20000000` |
| full normal reload | `0x20000000` | `0x20000000` |

This pattern repeated with band0/count2 and band1/count1. Every requested command
returned status zero; no CSI event was received and neither collection limit was
reached. Alive and cleanup checks passed. Bit 29 alone is **not a CSI-active
indicator**, because normal monitor setup already leaves it set. Nevertheless,
the selected-band start/stop effects independently rule out a simple no-op ACK.
Bits 30/31 also change; their semantics remain under investigation. STOP is not
an exact original-register restore, which reinforces the full-reload cleanup.

The preceding callback `0x0084583e` is another field-batch write, not merely a
validator: it writes keys `0x000500e0..e3` plus band<<16 through `0x0082a21e`.
The loaded caller tests its return value before proceeding. The batch writer
resolves a register with `0x0082a100`, applies fields with `0x0082a142`, then
stores the resulting word. Mapping those descriptors is the next useful lead.

[Sanitized hardware evidence](../research/evidence/csi-hardware-control-2026-09-05.json)
includes full raw register words, matched-event shapes and hashes of narrow ROM
windows, but no firmware bytes, addresses of observed transmitters or samples.
Twenty-one offline CSI-probe tests cover the new fixed read-only register set.

## ROM field mapping and the frame-selector breakthrough

The live field-domain callback at `0x02210484` points to ROM `0x00829e1e`.
It accepts domains <=0x79 and indexes `GP-5308 = 0x02211344`. Domains5/6 share
descriptor `0x02210498` / mapper `0x008322ce`; domains0x13/14 share descriptor
`0x022104dc` / mapper `0x0082a73c`. The register descriptor is eight bytes:
field-table pointer, u16 register offset, u8 field count, padding. Key bits15:5
select the register; low five bits index two-byte inclusive low/high bit pairs.
Band1 uses the next domain and adds 0x10000 to the hardware address.

| Field keys, band0 | ROM descriptor / field table | Register and bits |
|---|---|---|
| `0x500e0..e3` | `0x84d620` / `0x85528c` | `0x820e701c`: 15:14, 13:11, 1, 0 |
| `0x1302c0`, `0x1302c1` | `0x84b4e4` / `0x84bdf0` | `0x820e5060`: 31, 30 |
| `0x1302c7 - index` | same | bit `24 + index`, four slots |
| `0x1302cb - index` | same | six-bit field `6*index + 5 : 6*index` |

The enable helper writes bit31 from its enable argument and bit30 from config+4;
the direct ROM callback writes bit29. These independently explain the earlier
`0xe0000000` START and `0x40000000` STOP results. Zero default selector fields
suggested that zero was a specific frame type, not an all-frame wildcard.

Public tag2 is **11 bytes packed**, not 12: u16 tag/length, u8 index, u32 value,
two padding bytes. With the four-byte band prefix, the full payload is 15 bytes.
The loaded handler consumes only the low value byte; the field writer masks to
six bits. Configuring index0/value0x20 yields `0x00820820` in the low24 hardware
bits: the START routine duplicates the configured selection into unused slots.
Band0 readback was `0xf0820820` during the first active event run, band1
`0xe0820820` without events. Bit28's extra transition is observed but not yet
given a hardware-status name. All cleanup readbacks returned `0x20000000`.

The first pointer-range assumptions stopped two descriptor reads before following
the unexpected pointer. Subsequent bounded reads established the two exact ROM
tables above; these were host validation failures, not firmware command errors.
No direct MMIO write was needed to unlock CSI.

## Event layout: verified I/Q with a firmware-specific zero tail

The 564-byte event body consists of four reserved bytes, outer tag0/length560,
then 22 nested u32-tag/u32-body-length fields. Nested lengths exclude their
eight-byte headers. Observed tags are 0..12 and 17..25; I/Q tags6/7 are 128 bytes
each, address-shaped tags10/24 are eight bytes, and the others are four bytes.
Only documented measurement metadata is interpreted; tags10/24 and unknown
contents are discarded.

The meaningful nested fields end at body offset528, followed by **36 zero bytes**.
Initially a strict old-layout parser rejected the tail as a duplicate tag0. The
updated validator accepts only exactly 36 all-zero bytes after terminal tag25 of
length4, reports that padding explicitly, and rejects nonzero/different tails.
Both validated runs satisfy this exact rule with no invalid events. Loaded code
at `0xe009e3cc` sums descriptor sizes while skipping tag16; its emit path skips
13/14/15 as well. This is consistent with three unused 12-byte records accounting
for the tail; a universal cross-firmware padding convention is not claimed.

The validation runs have version raw22, data-count64, I/Q raw ranges
[-2582,2575] and [-2386,2620]. RSSI/SNR bytes are reported as raw metadata, not
calibrated measurements. `csi_event_summary.py` validates dimensions, lengths,
duplicates, bounded tails and required fields, then exports aggregate counts,
value ranges and transient I/Q digest cardinality (never digests themselves).
Thirty-one targeted CSI tests cover command bounds, event separation, privacy,
malformed payloads and the narrow tail rule. Production Python/C APIs are unchanged.

## Passive source coincidence and a receiver-pair key

`--correlate` compares identifiers only transiently within each bounded receive
window. It exports counts, not MAC addresses, timestamps, sequence numbers or
sample arrays. Across two fresh boots, every CSI transmitter was also observed
sending a good-FCS beacon in that same START window:

| Run | Window | Heard beacons / transmitters | CSI reports / transmitters | Exact RX0/RX1 pairs using TA + tag25 |
|---|---|---|---|---|
| 1 | 0.671 s; 512-transfer ceiling reached | 34 / 6 | 58 / 5 | 29 |
| 2 | 1.003 s; 157 transfers | 59 / 6 | 96 / 5 | 48 |

All 58/96 reports belonged to the shared transmitter set. The first run is
transfer-limited and **must not be compared as a full one-second rate**. Both
runs had zero CSI reports in the preceding configuration/stop windows and the
following STOP window; cleanup/alive passed. Source coincidence supports the
beacon-selector interpretation but is not yet exact per-frame attribution.

Tag17 (the public H-index field) produced only singletons. Tag23 grouped multiple
reports per transmitter and was unsuitable for per-frame pairing. **TA + tag25**
gave exact one-RX0/one-RX1 groups in both runs, with no repeated RX index within a
group. Tag25 is newer than the pinned public enum; it is an empirical pairing
key, not a globally unique identifier or a clock with established units. Its
full u32 value did not equal the heard beacons' sequence number, sequence-control
word, TSF-low32 or normal RX descriptor timestamp in either run.

[Sanitized correlation evidence](../research/evidence/csi-correlation-2026-09-05.json).
Two additional tests verify the counting/pairing logic, reject bad FCS/nonbeacons,
and ensure none of the transient identifiers or correlation values are exported.

## Tag25 comes from the MCU general-purpose timer

Following the actual store resolves the pairing field without guessing from its
values. Loaded routine `0xe006117a` calls the pointer at `0x00828418`, then stores
the return value at report-state offset0x164 (`0xe0061190`). The report builder
copies that word into tag25 at `0xe009e670..680`.

The live pointer is ROM **`0x0080e3fa`**, a wrapper supplying argument4 to
**`0x0081497e`**. That routine's argument4 branch reads **`0x81060068`** directly.
Pinned upstream `mt7925/pci.c` labels the enclosing `0x81060000` block
**WF_MCU_GPT**. Thus tag25 is a snapshot of an MCU general-purpose counter taken
during CSI handling, **not** a copied over-air TSF or the normal RXD timestamp.
Its relation to the exact RF arrival instant is still unmeasured.

A separate normal-mode, read-only timing control compared the register against
host monotonic time over approximately 108, 256 and 108 ms. Modulo-u32 increments
were 108646, 255624 and 108314; estimated rates were 1,002,339, 999,958 and
1,000,153 increments/s. USB read latencies were about0.7ms. This supports a
**nominal microsecond counter**, not precision clock calibration. At that nominal
rate a 32-bit value wraps in about71.6minutes; wrap/reset handling must be explicit.

Tag23 follows a different path: `0xe0060c08` calls `0xe00acabc`, which reads
bits15:0 of `0x83080d10` (band0) or `0x83090d10` (band1). It is not substituted
for the timer or given an unsupported semantic name.

[Sanitized timer-source evidence](../research/evidence/csi-timer-source-2026-09-05.json)
contains callback pointers, code-window hashes and timing deltas, never raw ROM.
No timer writes, CSI-buffer reads, host-memory DMA or clock configuration occurred.

## Receive-width controls and the initial QoS-data candidate

Passive primary36 runs at 80 MHz (center42) and 160 MHz (center50) both preserve
the beacon CSI readout. They yielded 112/98 validated reports and 56/49 exact
RX0/RX1 pairs, respectively, without reaching transfer limits. All CSI sources
were also heard as beacon transmitters; normal reload/alive checks passed.
CBW changes to raw2/raw3 while DBW remains raw0 and data-count remains64. This
distinguishes configured channel width from the narrow beacon's data width; it
**does not establish 80/160-MHz packet CSI**. I/Q remained nonzero and distinct,
and the same 36-byte zero-tail rule held.

The corresponding QoS-data FC[7:2] candidate, **0x22**, is separately available as
`--qos-data-selector` (mutually exclusive with `--beacon-selector`). Two 80-MHz
runs acknowledged the controls and read back the predicted repeated selector,
`0xe08a28a2`, but returned no CSI events. In the follow-up START window, normal
receive decoding saw 58 good-FCS beacons and two legacy non-QoS data frames,
**no good-FCS QoS data**. That is an insufficient-stimulus result, not proof of
unsupported QoS/wider-PHY CSI. Further traffic-selective experiments remain open.

`good_fcs_frame_classes` exports only type/subtype and PHY-class counts to make
such negative controls interpretable. It does not export payloads or identities.
[Sanitized width/selector evidence](../research/evidence/csi-width-controls-2026-09-05.json).

## MT7961 UNI follow-up is also refused

The earlier CE0x4c refusal did not settle whether MT7961 implemented the newer
station UNI route. A separate fresh-boot control therefore used the already
supported Connac2 UNI transport, CID0x4a, option7, band0/STOP tag0/length4.
It returned a matched EID1 result with **0xc00000bb**. Frame-selection and START
were skipped after that refusal. Normal reload/alive passed. This adds a specific
negative for the tested UNI STOP, not a proof that no other firmware/CSI route can
exist on MT7961. [Sanitized evidence](../research/evidence/mt7961-uni-csi-2026-09-05.json).

## Working per-transmitter CSI allowlist

Station UNI0x4a/tag4 accepts the public packed 16-byte command:
`<4xHHBB6s>` = reserved band0 prefix, tag4, length12, operation, reserved,
six-byte transmitter address. The loaded handler at `0xe003d4fa` maps operation1
to ADD and operation0 to REMOVE. The public converter at the pinned vendor source
does not implement this tag, so the loaded handler was checked independently.

`csi_filter_probe.py` chooses one transmitter already heard as both a valid CSI
source and a good-FCS beacon source. It requires at least two eligible sources,
retains the selected address only in memory, and exports counts only. Two fresh
boots reproduced this sequence (selected / other CSI reports, roughly one second
per window, no transfer limits reached):

| Phase | Run 2 | Run 3 |
|---|---:|---:|
| Unfiltered START | 20 / 74 | 20 / 76 |
| ADD selected | 20 / 0 | 20 / 0 |
| REMOVE selected, without START | 20 / 74 | 20 / 78 |
| ADD selected again | 18 / 0 | 18 / 0 |
| START again, without REMOVE | 18 / 78 | 18 / 78 |
| STOP | 0 / 0 | 0 / 0 |

All controls acknowledged status0, all CSI events validated, and six beacon
transmitters remained visible throughout. Post-ACK counts match the table.
Thus this is a **CSI-only transmitter filter**, not a normal receive filter.
An earlier run independently reproduced ADD isolation and START restoration.
Operationally, apply the allowlist **after START**, and reapply after restarting.
The START initialization helper `0xe0060e72` independently explains this:
`0xe0060ec8` stores zero to the list bitmap and `0xe0060ecc` stores zero to its
count byte. The earlier call at `0xe0060eae` also supplies the list base, zero and
length0x24 to a memory-fill-shaped routine; the explicit stores suffice to prove
the reset without relying on that routine's name.
REMOVE and full normal reload are attempted in cleanup; reload/alive passed.

The loaded helper `0xe00611d4` uses a five-slot, six-byte address list at
`0x0225d93c`: active bitmap at +0, addresses at +4, count at +0x22. ADD takes a
free slot; REMOVE clears its active bit and decrements the count. Internal
operation2 compares the active slots with report TA `0x0225daad`; it is not an
extra public operation. Caller `0xe0061302` passes the count into wrapper
`0xe00612c6`; zero count bypasses matching, explaining empty-list restoration.
The address RAM was **not read or published**. Only single-entry behavior has
been tested; duplicate, full-list and multi-entry semantics remain unvalidated.

[Sanitized filter evidence](../research/evidence/csi-filter-2026-09-05.json).

## Maximum-chain control works after START

The initial before-START control missed a real capability. In a fresh normal
channel36/20MHz run, START produced116 reports (58 each RX0/RX1); tag3/count1
then produced57 reports, **all RX0**. Tag3/count2 restored116 reports (58 each).
A second fresh boot yielded98 paired reports,57 RX0-only,100 paired,58 RX0-only,
then96 paired after another START. Thus START also resets the effective override.
All windows lasted about one second, no transfer limit was reached, every CSI
event validated, commands acknowledged status0, and stop/reload/alive passed.

The checked-in CLI reproduces the one-chain result:

```sh
python research/csi_control_probe.py --chip mt7925 --ack --beacon-selector --chains 1 --chain-order after --correlate
```

Its separate hardware validation yielded90 paired baseline reports and48 RX0-only
reports after the command. The default remains `--chain-order before` for faithful
reproduction of earlier controls; the output records the selected order explicitly.
Offline mocked-device tests verify command ordering, STOP/reload cleanup, and
rejection of an after-START order without a count.

This validates selection of reported receiver indices for these beacon captures,
not radio power saving, physical antenna-path disable, or arbitrary chain counts.
The wire count remains bounded to1/2. [Sanitized evidence](../research/evidence/csi-chain-order-2026-09-05.json).

A third ordering control further narrows the lifetime: START92 paired → count1
45 RX0-only → resend the same beacon-selector command94 paired → count2 96 paired
→ count1 48 RX0-only → START94 paired. This matches the control handler's
unconditional clearing of configuration byte+3 at `0xe003d43a`, with only tag3
setting it again at `0xe003d4f2`. Consequently, send the maximum-chain override
**last**, after START and any other CSI configuration commands, and reapply it
after changing those commands. This is not a persistent radio-chain setting.

## Specific data/control selectors: still no readout

Five additional passive controls narrow the present result without broad command
sweeping. Each used fresh normal firmware, matched status0 for all controls,
one-second windows, no transfer-cap truncation, and successful normal reload.

| Candidate FC[7:2] | Primary / width | Good-FCS matching frames during START | CSI |
|---|---|---:|---:|
| QoS data0x22 | 149 / 80 | 0 | 0 |
| Non-QoS data0x02 | 36 / 20 | 1 | 0 |
| BlockAck0x25 | 149 / 80 | 5 | 0 |
| RTS0x2d | 149 / 80 | 1 | 0 |
| BlockAck0x25 | 36 / 20 | 3 | 0 |

The hardware selector fields agree with each requested repeated six-bit value;
the two channel149 control-frame START snapshots include bit28, also seen with
working beacon capture. **Bit28 is not thereby proven to mean completed CSI.**
No QoS opportunity was observed, and the data/RTS counts are small. BlockAck has
matching frames on two channels but still no report. These are tested negative
controls, not a general firmware prohibition or a validated type/subtype mapping
for every frame class. The currently established readout remains beacon CSI.

The probe now accepts only named beacon/data/QoS/BlockAck/RTS selectors and two
previously tested passive primaries. Primary149 supports only20/80 here; invalid
geometry is rejected before device access. [Sanitized evidence](../research/evidence/csi-other-frame-controls-2026-09-05.json).
