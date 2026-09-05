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
