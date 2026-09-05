# MT7961 finite receive-vector log

**Separate receive-vector records are readable through the station RF-test
interface.** This gives access to CFO, SNR bits and per-chain RCPI for individual
logged receptions, beyond the single cached statistics sample. It is not yet a
continuous monitor-mode measurement stream or a source-attributed RF fingerprint.

The bounded reproducer is `research/rxv_log_probe.py
--acknowledge-experimental-transmit`. It sends four synthetic no-ACK HT MCS8
two-stream controls from MT7925 on channel36/20MHz and requires independent
good-FCS exact-frame receipt on MT7961 before sending four RF-test stimuli.
After STOP, it reads four identified vector words from at most three older log
records. Both radios are normally reloaded, including after failure.
No full vector, transmitter address, payload, per-run nonce or payload hash is
published. No association, tone, continuous carrier, efuse or calibration write.

## Wire requests and firmware-derived bounds

Pinned MT7961 RAM SHA-256
`b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`.
CE command1, action2, normal matched scalar EID9 response:

| Operation | Request body | Reply's defined scalar pair |
|---|---|---|
| Log count | `<B3xII>(2, 36, 40)` | selector36, count |
| One log word | `<B3xII>(2, 40, byte_offset)` | selector40, value |

Bytes after that eight-byte scalar pair are discarded. They are not extra
measurements. The band comes from current RF-test configuration, selected by
SET104=0, not from arbitrary high selector bits.

Public gen4m QA hooks name36 `RESULT_INFO` and40 `RXV_DUMP`, but describe an
older **36-byte/nine-word** record. This firmware instead writes **176 bytes /
44 words per record**. Using the public stride would split records incorrectly.

The pinned NDS32 paths establish the actual behavior:

- GET entry `0x00933572` loads current band from the test configuration. Selector36
  dispatches via `0x009335de..0x009335e2`; subselector40 at `0x009338ce..0x009338dc`
  returns per-band state+`0x24`, the log record count.
- Writer `0x00930ac2..0x00930b52` bounds the count to five, computes
  `old_count * 0xb0`, increments count, stores that record's starting offset at
  state+`0x28`, then copies18+2+4+20 words. Its input steps184 bytes, accounting
  for a separate eight-byte record header; output records are176 bytes.
- Selector40 dispatches via `0x00933652..0x00933656`. Getter
  `0x009338f0..0x0093391e` requires stored offset>=4 and requested byte offset
  <=stored offset-4, then reads the corresponding scalar from the log buffer.
  Thus the newest record is excluded by this getter. The tool respects that
  existing bound; it does not probe the boundary with out-of-range requests.
- `log_offsets` allows only words0,6,20,21 of at most three older records, with
  count0..5 validation. Counts0/1 yield no reads. It is not an arbitrary-memory API.

Word0 bits7:4 provide PHY mode, word6's first two bytes RCPI, and words20/21 the
[firmware-validated CFO and SNR fields](FREQUENCY_OFFSET.md). No calibrated Hz/dB
or normalized phase/amplitude interpretation is added.

## Hardware evidence, 2026-09-05

The first controlled run independently received4/4 baseline frames, then the
four RF stimuli changed log count **0 → 4 → 4** (last after STOP). The cached
mode was HT2, raw CFO -3653, integer CFO -4338, SNR bits29. RF mode did not send
ordinary decoded packets to the host; the count/vector route is separate.

The first readout run again received4/4 controls, then reached the five-record
cap. Three retrieved older records were HT mode2, RCPI bytes29/29,30/30,29/29,
raw CFO **-3945,-4065,-3988**, integer CFO **-4685,-4828,-4736**, SNR bits29.
Meanwhile the last-sample cache held **OFDM mode1**, raw CFO -24155 / integer
-28685 and SNR bits28. This directly demonstrates different retained records
versus a subsequently overwritten global sample.

The tracked-tool validation repeated4/4 exact controls with decoded HT/MCS8/NSS2/
20MHz evidence. Log count was0→4→4. Three read records gave raw CFO
**-4228,-4174,-4205**, integer CFO **-5021,-4957,-4994**, SNR bits29/30/30 and
RCPI29/30,29/30,28/30. All three controlled runs passed both-radio reload/alive
checks. [Sanitized evidence](../research/evidence/rx-vector-log-2026-09-05.json).

The association of those HT records with our stimulus is supported by timing,
the known PHY and independently verified normal-receive controls; the log readout
does **not** contain a checked transmitter identity, exact frame or FCS flag.
The fifth record shows that ambient receptions can mix into the log. Do not call
the RF-mode count an exact synthetic-packet delivery count.

Count-only preflights returned matched zero counts in RF mode; normal-mode
queries failed. Adding bounded USB drains and one CE0xc8 query still yielded no
received traffic/nonzero cache in those controls. The controlled stimulus made
the log observable. This is not proof that stimulus is a formal prerequisite;
the passive windows simply provided no useful samples.

## Rearming the log and receiving HE

`--rearm-he` extends the bounded experiment to16 total synthetic frames: four
normal HT controls, four normal HE-SU/MCS0/two-stream controls, then four HT and
four HE RF-test stimuli in separate batches. Both control formats must have
independent exact-frame receipt before the RF-test experiment proceeds.

The public counter reset SET91=0, `<B3xII>(1, 91, 0)`, dispatches through
`0x00932780`. Besides resetting TX/RX counters, firmware stores zero to the
per-band log count at `0x009327a0` and last-record offset at `0x009327a4`.
This is a volatile counter reset, not a log-only operation or an NVM write.
The tool stops RX, reads the first batch, resets, requires count zero, then
restarts RX for the second batch. It never reads old records after the reset.

The first live validation received **4/4 HT and4/4 HE normal controls**. Its
first log reached5 and returned three HT records. Reset changed count5→0;
the second batch reached4 and returned three **HE mode8** records, with raw
CFO -4167/-4493/-4471, integer CFO -4949/-5336/-5310, SNR bits28/27/28 and
RCPI bytes28/29 each. Both radios reloaded and passed alive checks.
[Sanitized evidence](../research/evidence/rx-vector-log-rearm-2026-09-05.json).

**Reset does not invalidate or clear the latest-vector cache.** Immediately
after reset its old integer CFO -28025 and SNR bits27 remained, despite count0.
New HE reception subsequently replaced it. Consumers must not treat a nonzero
cache or successful counter reset as proof of a fresh measurement. The changing
HT→HE records establish reusable finite batches, not continuous streaming,
exact synthetic-frame attribution, or calibrated frequency units.

## Transmitter matching does not isolate this log

`--match-ta` compares matching→mismatching→matching synthetic transmitter
addresses in three reset-separated four-frame HT batches, after four exact
normal controls (16 submissions maximum). The mismatching target differs in
one bit of the final byte; the transmitted address stays unchanged. No ambient
address is selected or published. `--rf-clean-start` additionally reloads the
receiver after the controls, without normal monitor/sniffer/tune preparation.

Firmware provenance:

- SET68 stores the six-byte receiver address at config+`0x3e`; SET69 stores the
  transmitter address at+`0x44`. `0x00932628..0x0093265c` takes four bytes when
  selector high16=0 and two bytes when high16=4 (selector bit18), then applies
  configuration after the second fragment.
- SET70 accepts rule0..3 at `0x009326e2`, stores config+`0x38`, and calls
  `0x009302f0` for both addresses. With rule0, a zero address disables that
  side; nonzero TA sets flag+`0x3c`, while receiver flag is+`0x3d`.
- TA programming reaches `0x0094beba` → ROM slot`0x0082287c`, verified to hold
  `0x0082776a`. That routine packs low32/high16 address bits, adds enable bit16
  to the upper word, and writes the selected address slot. The band0/slot0
  pair is`0x820e5208/0x820e520c`. No host write to those registers was needed.
- The bounded state check reads the band0 configuration pointer from
  `GP+0x1417c = 0x0201717c`, validates its RAM range/alignment, and exports
  only rule/flags and equality to our synthetic target. No pointer or address
  bytes are exported. A separate no-transmit check showed those flags and
  the enabled matching hardware address survive RX start and STOP.

Two fresh-boot A/B/A runs received4/4 normal controls. Log counts were5/4/4
and4/5/4. **The mismatch still retained three HT records in both runs.**
RX-OK counts were6/4/4 and4/6/4, so they did not isolate the target either.
In the second run, every phase confirmed transmitter flag on, receiver flag
off, rule0, hardware enable on, and hardware equality to the requested target,
including the intentionally wrong target. This is not a failed-setting inference.
RX-error counts were0/0/0 and0/5/0; ambient/error mixing prevents assigning
those errors to our four stimuli.

The clean-entry control also received4/4 normal controls, then reloaded the
receiver without the normal preparation. All three RF batches returned count0,
RX-OK0/RX-error0 and a zero cached vector, despite verified match configuration.
**That all-zero control does not establish successful filtering:** the matching
positive control failed too. It identifies an RF initialization dependency still
to separate. Both-radio cleanup passed in all runs.
[Sanitized evidence](../research/evidence/rx-vector-match-2026-09-05.json).

Consequently, this path is not a source-attributed CFO interface. The firmware
vector writer has no visible address comparison in its record-copy path; the
live negative controls are stronger evidence than the existence of a match slot.
Do not infer the behavior of other receive modes or all match rules from rule0.

## Normal channel preparation is sufficient without monitor enable

`--rf-clean-prepare` reloads only the receiving radio after independent normal
controls, then applies one named, existing preparation before RF-test entry:

| Preparation | Normal commands after reload | Observed log count |
|---|---|---|
| `tune` | CHANNEL_SWITCH plus sniffer CONFIG, no sniffer enable | 4 |
| `channel` | CHANNEL_SWITCH only | 5 |
| `config` | sniffer CONFIG only, no sniffer enable | 5 |

Each run had4/4 exact HT controls followed by four RF stimuli, and each returned
three older HT records with nonzero CFO/SNR/RCPI fields. All cleanup passed.
These controls distinguish normal channel preparation from enabling promiscuous
MAC filters or the sniffer. Either individual channel-setting command sufficed
in this setup; the combined `tune()` is not a single wire command. The earlier
bare clean-entry control lacked all three and produced no useful RF samples.
This identifies a practical preparation requirement, not every internal clock
or calibration action performed by those commands.

A further **tune-only matching→mismatching→matching** run repeated the filter
negative: log counts5/4/4 and RX-OK10/4/4, with three HT records in the mismatch
batch despite verified flags/hardware target. Thus inherited monitor filters or
sniffer enable do not explain the missing source isolation.
[Sanitized preparation evidence](../research/evidence/rx-vector-preparation-2026-09-05.json).

## Avoid a dead-end control

The source-defined SET109 `SET_RXV_INDEX` packs group1,group2,band in bytes0,1,2.
Static tracing confirms the unpacking through `0x009305d8` and `0x00964d8c`, but
the final callee **`0x0094bed0` is a three-instruction unsupported stub**, returning
`0xc00000bb`. Its wrapper discards that return and itself returns zero.
No live SET109 experiment was needed: an outer success cannot establish a changed
vector selection on this pinned firmware.

Protocol comparisons use Motorola gen4m pin
`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`, `include/rftest.h`,
`os/linux/gl_hook_api.c:MT_ATEGetDumpRXV`, and
`wlan_service/glue/hal/gen4m/operation_gen4m.c:mt_op_get_rxv_cnt`.
These BSD-2-Clause sources supply protocol names; the actual stride, cap and
getter bounds come from this firmware. No vendor implementation is copied.
