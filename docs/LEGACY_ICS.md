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
