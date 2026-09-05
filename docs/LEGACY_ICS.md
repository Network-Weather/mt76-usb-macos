# MT7961 MAC diagnostics through legacy CE93

**The older dongle also produces a live RMAC diagnostic stream in normal monitor
mode.** It uses source-defined legacy CE`0x93`, not MT7925's UNI49 transport.
Three passive channel6 controls with default Group5 settings produce20,19,18
enabled-phase type12 aggregates, each272 bytes with declared frame-count3.
Ordinary good-FCS CCK reception continues alongside them:20,20,18 frames.
This is a new transport/metadata surface, not calibrated RF measurement or a
networking driver.

## Source and pinned execution path

Pinned MT7961 RAM SHA-256:
`b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`.
The Motorola gen4m source at revision
`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec` names
[CE93 SET_ICS_SNIFFER](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/wsys_cmd_handler_fw.h)
and its84-byte
[CMD_ICS_SNIFFER_INFO](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_cmd_event.h).
The host initializer zeroes the structure, then fills action/module/filter/
operation and seven u16 conditions. Our request uses module2, action0/1,
condition0=1 (RMAC), condition1=0 (band0); other fields remain zero. No UNI
reserved header or TLV precedes it. It is a CE SET, not a query or AP EXT command.

The corrected CID-before-handler table contains file-layout record
`02025eec:{93,00922ce6}`. Applying the established`44c` data relocation gives
live`02026338/0202633c`. The preceding table count at`02026114` is70. All three
words and four fixed code-window SHA-256s are verified live before activation.

Handler`00922ce6` reads the84-byte payload at command buffer+`40`, action at+1,
condition0 at+8 and band at+`a`. Action0/1 selects RMAC through`0094abb8` →
`0096966c`; TMAC uses`0094ca88` →`0093a3ee` but is not activated in these tests.
Getters`0094abc6`/`0094ca96` read both enable states. Their OR controls two shared
paths, including **additional legacy-only writes not present in the newer path**:

| Band0 register | Changed mask | Pinned leaf |
| --- | --- | --- |
| `820e50d0` | bit0, RMAC enable | `0096966c`; getter`00969694` |
| `820e705c` | bit24, shared diagnostic enable | `00946128` →`00936a44` |
| `820e0004` | bit9 and bit2 | `00946136` →`009369f8` and`00936a1e` |

Both band leaves reject band>=2. Only band0 is used. The CE handler also contains
filter action2/op5 and6 branches; they are traced but not invoked. Unsupported
selectors are not probed. The module byte is not needed to choose the observed
RMAC branch; retaining source module2 is not evidence of a separate module check.

## Bounded reproducer and cleanup

[`research/legacy_ics_probe.py`](../research/legacy_ics_probe.py)
requires`--activate-legacy-rmac-ics`; optional channel is6 or36 at20MHz. Each
off/on/off collection is400ms with at most512 bulk-read attempts. No TX, PHY
capture selector, filter configuration, NVM programming or host-memory DMA.
Only exact traced masks are restored, then normal firmware is reloaded. The
optional previously qualified Group5-report bit (`820e7000` bit23) is included
in the restoration set even when left unchanged.

No matched legacy command events arrive. This is not treated as command failure:
all three command-controlled registers change from masks0 to1/`01000000`/`204`
while enabled and back to0 after STOP. Every run passes restoration and reload.
Initial off windows have no ICS; one final default-Group5 repeat has one diagnostic
in the post-stop window, so immediate queue emptiness is not guaranteed.

With`--match-rxd-in-memory`, at most128 ordinary and128 diagnostic transfers per
window are compared locally. Connac2 extraction uses the correct24-byte fixed
descriptor, eight-byte Group2/3 and72-byte Group5; the newer connac3 lengths are
not reused. Captured bytes, identifiers, headers and absolute timestamps never
leave process memory. Only equality counts, candidate offsets and relative
residual extrema are written to JSON.

Two default-Group5 matching runs yield19 and18 unique-header pairs. Their
24-byte MAC-header copy is at **offset120**, not the newer chip's144. The
P-RXV word1 (RCPI bytes in this short descriptor) exactly matches **offset40**,
with11/10 distinct values. Three clock candidates at **12,92,164** follow
relative RXD timestamp changes within−1..+1 ticks. No full fixed descriptor or
eight-byte P-RXV matches, and no absolute clock/ranging claim follows.

## Extended-vector counterexamples

Two extra tests enable the known Group5 report bit before the off/on/off phases.
Channel6 yields32 ICS aggregates but **no ordinary packets in the enabled phase**;
only one ordinary packet appears in its initial off window. Channel36 produces
neither ordinary packets nor ICS in its enabled window. All command masks still
transition correctly, all restorations/reloads pass, and the subsequent default-
Group5 channel6 repeat recovers18 ordinary/header-paired diagnostics.

These tests do not establish working simultaneous Group5+ICS reception, nor do
they prove Group5 universally prevents reception (earlier controlled HT/HE tests
did receive extended descriptors). Ambient PHY/traffic differences and capture
configuration remain possible factors. Keep the negative results rather than
calling an empty extended-vector comparison successful. A bounded known-HT
stimulus is a better next discriminator than another passive wait.

[Five-run sanitized evidence](../research/evidence/legacy-ics-2026-09-05.json).
Compare [MT7925 ICS](ICS_CAPTURE.md) and the older
[finite RF-test receive-vector log](RX_VECTOR_LOG.md), which is a separate path.

## Known HT stimulus qualifies simultaneous Group5 reception

[`legacy_ics_own_probe.py`](../research/legacy_ics_own_probe.py) sends sixteen
synthetic no-ACK HT MCS8/two-stream/20MHz frames from MT7925 to MT7961 on channel6:
four with ICS off, eight on, four off. Payloads alternate65/193 bytes and contain
a per-run nonce. Host submission gaps are at least35ms, each600ms phase stops
submitting after400ms and caps bulk-read attempts at1536. Both radios reload;
the legacy receiver's four masks are restored. No positive power changes,
association, NAV reservation, raw ambient export or unbounded transmission.

Three fresh-boot runs—default Group5, Group5 enabled, Group5 enabled again—receive
**48/48 exact full-payload good-FCS packets**, with48 matching TX statuses.
Every enabled-phase own packet has a corresponding unique header-matched ICS
record,24/24. The two Group5 runs establish **16/16 exact copies of the complete
72-byte C-RXV at aggregate offset16**, independently paired by header120 and
known full-payload receipt. RCPI40 and clocks12/92/164 repeat, with relative clock
residuals within one tick. The default-Group5 run retains two non-own diagnostics
in its post-stop window; the two Group5 runs have none. No own packet from an
off phase has a matched diagnostic in any of these runs.

Thus simultaneous Group5+ICS reception does work for this controlled HT traffic.
The earlier passive windows remain real counterexamples to assuming it will
immediately work for arbitrary ambient traffic; this is not evidence that a
particular initial HT frame is a formal prerequisite or a complete explanation
of the passive misses. Group5 phases also contain ambient diagnostics, so their
total aggregate counts are not synthetic delivery counts.

One source-inspired extra-vector hypothesis fails cleanly. The RF-test log
writer copies18+2+4+20 words, and its CFO/SNR calculation uses words20/21. After
finding18 C-RXV words in ICS, placing the presumed later P-RXV2 at104/108 looked
plausible. But applying those masks returns **signed20=−1 and SNR bits63 on all
24 own packets**, with or without Group5. These all-one fields are not usable
CFO/SNR measurements in these normal-mode controls. The subsequent RF-mode
experiment below establishes mode-dependent filling at that very location;
the initial normal-mode rejection must not become a universal absence claim.
Only identified source masks were exported, never arbitrary words.

[Three controlled HT runs](../research/evidence/legacy-ics-own-ht-2026-09-05.json).

## RF-mode ICS streams populated CFO/SNR beyond the finite log cap

**In RF-test receive mode, the same ICS offset104 contains the actual P-RXV2
vector, including the firmware-validated CFO and SNR fields.** This bridges the
previously finite five-record RF-test log to a USB diagnostic stream with known
frame-header attribution. It does not yet provide calibrated measurements in
ordinary monitor mode.

[`legacy_ics_rf_probe.py`](../research/legacy_ics_rf_probe.py) first requires four
exact full-payload good-FCS HT8/two-stream/20MHz normal controls. It then enters
the established RF RX mode, configures band0, two receive paths and20MHz, enables
CE93 RMAC ICS, and sends four or eight further synthetic no-ACK HT frames.
The frequency request is the source's SET18 in kHz: channel6=`2437000`,
channel36=`5180000`; no other frequency is exposed. The
[vendor channel setter](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/os/linux/gl_hook_api.c)
documents these units. Total submissions are capped at8 or12, RF gaps at least
50ms, and RF collection at one second/2048 bulk-read attempts. Collection stops
early once every submitted header is observed. RF STOP, masked ICS restoration
and both-radio normal reload are attempted on every exit.

After RF STOP, two reads of the **fixed96-byte cache at02040808** must agree.
Its layout is established by the pinned firmware copy at`00930a58..00930a86`:
18 C-RXV words, two P-RXV1 words, four P-RXV2 words. No arbitrary RAM range is
read and no cache bytes are exported. A stable cache's first72 bytes must match
an own-header ICS record's C-RXV16..87 before exporting its known CFO/SNR fields
or testing the16-byte P-RXV2 copy. This is an in-memory content match, not a
time-proximity assignment.

Three successful channel6 boots independently reproduce:

| RF own headers observed | Final matched sequence | Cached raw signed20 CFO | Raw SNR field | Exact P-RXV2 copy |
| --- | --- | --- | --- | --- |
| 4/4 | 7 | 234 | 24 | Offset104,16 bytes |
| 8/8 | 11 | 1139 | 24 | Offset104,16 bytes |
| 8/8 | 11 | 1117 | 24 | Offset104,16 bytes |

All three stable caches match the final own record's entire72-byte C-RXV and
entire16-byte P-RXV2. Applying the established masks at104/108 also exactly
reproduces the cache's CFO and SNR. Both eight-frame runs return the finite log
count **5** through the known GET36/subselector40, yet ICS contains all eight
own headers with changing populated fields, without resetting or rearming the
log. Their per-record raw CFO ranges are720..1245 and863..1353; SNR fields16..25
and24..25. These are raw fields, not Hz/dB or a stable oscillator fingerprint.

In RF mode no ordinary type2 records arrive, so **20/20 known RF headers is not
20/20 independently decoded full-payload/FCS receptions**. The12 preceding
normal controls are independently received; the RF records have exact submitted
24-byte headers and the final-cache content checks. Ambient diagnostics also
arrive and are not exported as attributed samples. This is a bounded proof of
streaming beyond the five-record log cap, not an unlimited/lossless throughput
qualification or a generic third-party-frame decoder.

An initial channel36 attempt receives0/4 normal controls and correctly skips
RF mode/ICS entirely. It is retained in the evidence. All four attempts reload
both radios successfully; all three activated attempts restore every mask.
RF STOP leaves ICS enabled until its separate STOP/restoration, as expected.
The key remaining question is which RF setup operation populates P-RXV2, and
whether a narrowly traced control can enable it with normal full-frame RX.
[Four attempts, including the failed prerequisite](../research/evidence/legacy-ics-rf-stream-2026-09-05.json).

## Staged entry brackets stream availability, not the filling bit

Two fresh-boot [staged runs](../research/evidence/legacy-ics-stages-2026-09-05.json)
use only the existing commands and20 synthetic HT8 frames each. The
[stage probe](../research/legacy_ics_stage_probe.py) reasserts CE93 RMAC ICS and
verifies its enable masks before each four-frame,600ms window:

| Stage | Normal exact good-FCS | Own ICS headers | CFO/SNR fields |
| --- | --- | --- | --- |
| Normal monitor + ICS | 4/4,4/4 | 4/4,4/4 | All-one sentinel −1/63 |
| RF-mode entry only | 0,0 | 0,0 | No records |
| STOP/band/paths/frequency/width setup | 0,0 | 0,0 | No records |
| RX START | 0,0 | 3/4,4/4 | CFO1459..2162, SNR15..26 |
| RX STOP | 0,0 | 0,0 | No records |

All40 submissions have matching TX status. Both runs restore all four masks and
reload both radios. No receiver packet types at all arrive in the entered,
configured or stopped windows; enabled ICS readback alone is not an active RX
path. The missing first own header in one START window is retained, not silently
converted into a lossless-stream claim. No full-payload/FCS claim applies in RF
mode. These controls **cannot distinguish setup-time P-RXV2 filling from
START-time filling**, because the intermediate stages provide no vectors.

The pinned SET dispatcher at`00931b2c` sends selector1 to`00931e66`; the
little-endian signed-halfword table at`00931eb0` maps value0 to`00932030` and
value2 to`0093220e`. The ordinary RX-start tail`009322f4..0093232e` separately
calls `00964a9c`, `0093091a`, `00930b9a` and `009311c2`. Thus START is not a
single vector-enable write. RF initialization`00933114` independently calls
`0094382e(0,1,band)` at`009332c4` and conditionally`00943852(1,band)` at
`009332ea/00933300`. The first wrapper writes abstract field keys
`(band<<16)+680/681`; **these are field indices, not register masks**. Resolving
their old-chip ROM descriptors is the next narrow target. No old-chip register
address is inferred from the newer radio's similarly named controls.

## Normal RXV START is insufficient; quiesce is a separate operation

The older radio's live ROM resolves the control without a cross-chip guess:
domain0 slot`02014f04` → descriptor`020138d4` → mapper`0082a322`;
table`0084b7a4`, entry`0084b944`, bit-pair table`0084bb0c`, register offset14,
band0 base`820e3000`. Thus the five keys680..684 map to
**820e3014 bits8,7,4,2,0**, respectively: TX-report enable, RX-report enable,
RXV START, quiesce request and ordinary RX START. The mapped names for bits0/4
also agree with the pinned mt76 MT7615 definitions, but that different chip's
register recipe is not used as old-chip address evidence.

Live slot`008226a8` points to`0082a3f4`, which clears key683, then selects
key682 for argument1 or key684 for argument0. **Argument0 does not mean STOP.**
An initial interpretation and experiment labeled it `rxv_stopped`; the retained
evidence explicitly corrects that label. START stuck at1 after that attempt,
and normal reload restored the original state. No successful masked cleanup is
claimed for it.

The separate disable caller`0094a950` reaches live slot`00822a58` →
**0082a452**. This routine clears keys684/682, writes1 to683 and waits for683
to clear, bounded by1000 iterations. Its companion ordinary-RX selection then
resumes delivery. The480-byte ROM window at`0082a320` hashes to
`1e4fb6f19419b2281f039ee6e8fdfed49feadbff1bbe1ea3341258b582706bb4`.
The [normal RXV probe](../research/legacy_rxv_control_probe.py) verifies that
hash, the live pointers and exact bit descriptors before any control writes.
Only RX reporting is enabled; TX reporting is refused. Full normal reload is
still mandatory on every exit, even when masked restoration succeeds.

Two activated attempts establish a useful negative: RX-report enable0x81 and
RXV START0x91 preserve ordinary HT packet reception, but **all eight own packets
in the two START windows retain CFO−1/SNR63** at P-RXV2 offset104. These controls
alone do not enable RF-mode CFO/SNR filling. No new ordinary RX-vector packet
type appears.

The corrected quiesce run separately establishes a packet-path control:

| Phase | 820e3014 | Exact normal good-FCS | Own ICS headers |
| --- | --- | --- | --- |
| Baseline ICS | 1 | 4/4 | 4/4 |
| RX report only | 81 | 4/4 | 4/4 |
| RXV START | 91 | 4/4 | 4/4 |
| Quiesced | 80 | 0/4 | 4/4 |
| Ordinary RX resumed, report off | 1 | 4/4 | 4/4 |

The quiesced headers have sequences first submitted **after** quiescence, so
they are not merely pre-quiescence leftovers. ICS continues receiving current
diagnostics while ordinary full-packet delivery is suppressed; this is not a
physical RF shutdown. All20 ICS fields remain all-one. Final quiesce reads0,
ordinary RX resume reads1, and all five owned bits match their original values
before reload. ICS masks and both-radio reloads also pass.

A fresh repeat receives only2/4 required normal prerequisites (but4/4 ICS
headers) and correctly skips all RXV writes; it is not a repeat validation of
quiescence. The first experiment receives19/20 ordinary packets; the corrected
one16/16 outside intentional quiescence. All44 submissions across these three
attempts have TX status. USB leading-record counts are not lossless RF-delivery
statistics. [Complete sanitized attempts and historical-label correction](../research/evidence/legacy-normal-rxv-2026-09-05.json).

## RF-init RMAC bit0 does not fill normal P-RXV2

RF initialization calls `0094387c(0,band)` at `00933294/009332a6`.
This writes abstract key12038a. Live domain18 slot02014f4c points through
020138dc to ROM mapper008270aa, table0084abd4; entry0084acb4 points to
0084b104, offset604, count13. Field index10 is bit0, hence band0 register
**820e5604 bit0**. Adjacent RX-path fields12038b/12038c are bits21:20 and26;
their normal values already match the traced RX-start values3/1.

The [candidate probe](../research/legacy_prxv2_probe.py) pins firmware, mapper
and wrapper hashes, verifies field descriptors, and changes only bit0. This
is a source-derived candidate, **not an established P-RXV2 enable bit**.
Two completed baseline/candidate/restored runs each receive12/12 exact
good-FCS HT8 packets and12/12 matching own ICS headers. The first clears bit0
alone; the second also enables RX reporting and RXV START. Both observe
24f00903 →24f00902 →24f00903; the combined run observes RXV91 →1 after the
traced quiesce/resume handshake. Every P-RXV2 CFO/SNR value remains−1/63.
Thus neither this bit alone nor this tested combination recovers normal-mode
CFO/SNR. Eight candidate-window packets provide the controlled negative.

An earlier attempt receives3/4 normal prerequisites and skips the candidate
clear. Its unchanged baseline/restoration writes still occurred; it is not a
zero-MMIO-write run. All28 submissions across the three attempts have TX
status;27 ordinary packets and27 own ICS headers are observed. Candidate,
optional RXV and ICS masks restore successfully, and both radios reload on
every exit. [All sanitized attempts](../research/evidence/legacy-prxv2-candidate-2026-09-05.json).

The RF-init patch callback `e027c732(3)` updates a software bitset and invokes
a common callback with operation6 and value2; it is not a direct P-RXV2
register setter. Another traced setup wrapper0094be50 selects fields40080..84
at820e7050. Their normal values differ from the RF-init arguments; live RF-mode
comparison is the next test, before considering any direct activation.

## RF DMA setup matches the trace but is insufficient in normal mode

Live domain4 slot02014f14 →02013898 →ROM0082de58 resolves table0084c22c,
entry0084c24c →0084c2b0, offset50 and five fields. Band0 base820e7000
therefore selects820e7050, not a host-memory pointer. RF initialization calls
0094be50(1,1,2,2,0,7f,band); its ten-argument field writer sets:

| Key | Bits | Normal | RF entry |
| --- | --- | --- | --- |
| 40080 | 6:0 | 47 | 127 |
| 40081 | 12:8 | 4 | 2 |
| 40082 | 15:13 | 2 | 2 |
| 40083 | 27:16 | 1 | 0 |
| 40084 | 31:30 | 1 | 1 |

A20-frame staged repeat adds only read-only snapshots of820e7050,820e5604
and820e3014. Normal values4001442f/24f00903/1 become
4000427f/24f00902/91 at RF entry, exactly matching the trace, and remain
unchanged through configuration, START and STOP. It receives4/4 normal
controls and4/4 RF START headers (CFO1684..1949/SNR23..24); intermediate
stages remain empty. Thus these register values alone do not distinguish
active receive from stopped RF state.

The [pinned DMA helper](../research/legacy_rx_dma_setup.py) verifies both code
hashes, the pointer chain and all five bit pairs. It exposes only the observed
normal/RF values, preserves unrelated bits under maskcfffff7f, and never
changes a DMA address or buffer. Two12-frame normal-mode experiments combine
that setup with the preceding RMAC bit0 and RXV controls. All8/8 active-window
packets are good-FCS and all8 own ICS vectors still contain CFO−1/SNR63.
Overall ordinary reception is11/12 then12/12; own ICS is12/12 in each.

One first-run restoration-window header (sequence8) has CFO1714/SNR17, but
there is no matching ordinary good-FCS packet. The next three and the entire
fresh-boot repeat are all-one. **This single exception does not establish a
working normal-mode configuration, a bad-FCS cause, or valid calibrated units.**
It is retained for exceptional-path investigation. All44 submissions across
the staged run and two controls have TX status; every activated mask restores,
and both radios reload. [Complete sanitized evidence](../research/evidence/legacy-rx-dma-setup-2026-09-05.json).
