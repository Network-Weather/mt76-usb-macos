# Experimental raw histogram integration (R32)

Implemented on `feat/measurement-api`, not released. The installed Python module
`mt76_histogram` and native `mt76_histogram.h` expose matching **pure wire/record
helpers**. `mt76_histogram_acquisition` / `mt76_histogram_acquisition.h` add matching
opt-in control guards with short native/Python live evidence. This is not a
calibrated noise measurement service or a released continuous stream.

| Python | C | Profile |
| --- | --- | --- |
| `build_histogram_request` | `mt_histogram_request` | MT7925 only, fixed UNI36/tag2 one-shot request, SET/ACK option7; no duration, index, threshold or address parameters |
| `parse_histogram_ack` | `mt_histogram_ack` | Exact EID1/nonzero sequence/CID36/status envelope; return actual status |
| `parse_histogram_event` | `mt_histogram_event` | MT7925 EID36/sequence0, exact96-byte body, tag2/length92, two arrays of11 u32 bins |
| `parse_legacy_histogram` | `mt_histogram_legacy` | MT7921 only, exactly44 little-endian bytes from the already stopped ordinary bank |
| `HistogramGuard.begin/finish/restore` | `mt_histogram_begin_device/finish/restore` | One outstanding acquisition, checked fixed controls, explicit pending/reload state and unknown sample coverage |

`HistogramBins` / `mt_histogram_bins_t` owns the arrays. Source is
`legacy_ordinary` / `MT_HISTOGRAM_LEGACY_ORDINARY`, or `firmware_timer` /
`MT_HISTOGRAM_FIRMWARE_TIMER`. Native `view_count` distinguishes1 from2 arrays.
Totals use wide arithmetic (Python integers/native u64) so11 large u32 bins do
not silently wrap their sum. Native outputs remain unchanged on error.
Complete USB padding is ignored, but cannot fill a truncated declared event.
All-zero arrays and unequal totals are retained as raw observations, not repaired.

The ten `threshold_labels_raw` values are pinned firmware constants:
−92, −89, −86, −83, −80, −75, −70, −65, −60, −55.
They are **not a demonstrated dBm calibration**, nor independently verified bin
inequalities. Raw view indices are not physical antenna labels. Neither record
contains a mean noise floor, interference class, sample period, exposure duration,
coverage fraction or channel ranking. No conversion from histogram deficit to
CCA/non-Wi-Fi time is justified. Syntax alone establishes neither freshness nor
sensor health. Keep acquisition, channel, epoch and loss metadata separately.

## Acquisition guard contract

Construct `HistogramGuard(dev)` or zero-initialize `mt_histogram_guard_t`. Use
`session.call(lambda d: guard.begin())` / a callback invoking
`mt_histogram_begin_device(dev, &guard)` when the session owns USB. Device wrappers
limit the profile to normal20MHz channels1/6/11/36. MT7921 begin freezes/resets the
ordinary bank, verifies zero, sets the traced option mask and enables sampling.
MT7925 begin snapshots both control indices, refuses existing activity and sends
the checked fixed one-shot request. Neither helper enters RF-test mode or TX.

Keep one histogram controller/device and serialize all methods. The caller owns
the event queue and epoch/channel provenance: do not retune, reset, mix other
histogram controls or carry a guard across firmware reload. No CSI/histogram
combination is qualified. The native injectable `mt_histogram_begin` boundary is
for tests/custom transports; its caller must supply the qualified profile context.

Outside the worker callback, collect normal frames and route events for a bounded
interval. Tested legacy windows are250/500/1000ms; use a two-second deadline for
the modern one-shot. The guard does not sleep, run a background timer, consume
queues or provide automatic cancellation. For modern events, retain/check session
epoch, generation and host receive time against the activation before submitting
the raw event; a queued sequence0 report has no unique acquisition identifier.
Host time and bank agreement still cannot prove exact sample freshness.

Call `finish(raw_event)` / `mt_histogram_finish` through a session callback.
Legacy uses no event (C `NULL,0`): finish freezes and reads its eleven bins. Modern
requires a strict complete event, all four control masks stopped, and exact
agreement with both stopped timer banks. It cannot use an event alone to bypass
the hardware check. Finish returns `HistogramSample` / `mt_histogram_sample_t`,
with owned bins and command-open/closed and read-open/closed host microseconds.
These outer bounds include USB/reset/queue/consumer overhead, not just exposure.
Python coverage/cadence are `None`; C `coverage_known=false`, `sample_period_ns=0`
means unknown. Native sample output is unchanged on failure.

`active`/`pending`/`needs_reload` become true before the first possible mutation;
`ready` becomes true only after begin's own commands complete. It does not promise
session health, event availability or firmware lifetime across reload. Finish
clears pending/ready only on success. Always restore a completed guard through a
session callback: it preserves unrelated bits and attempts every saved mask.
Restoration failures retain active for retry. Legacy pending restore can stop its
engine; modern pending restore refuses without I/O and clears ready, requiring
full reload after worker stop. A failed begin must not be treated as a sample.
`needs_reload` deliberately stays true after restoration: reload after the whole
experiment and discard the old guard/session objects. Shared history is lost.

## Coexistence and repeated one-shot gate

```sh
python research/histogram_session_probe.py --chip mt7921 --fw PINNED_DIR \
  --channel 6 --reset-shared-histogram
python research/histogram_session_probe.py --chip mt7925 --fw PINNED_DIR \
  --channel 6 --reset-shared-histogram
make -C c mt76_histogram_probe
c/mt76_histogram_probe --chip mt7925 --fw PINNED_DIR \
  --channel 6 --reset-shared-histogram
```

The explicit flag acknowledges irreversible loss of shared histogram history.
Use one session/USB owner per radio, no other histogram consumer, CSI or retune.
The probe uses only the previously traced volatile masks, normal monitor capture
and named CCA/MPDU plus thermal queries. MT7921 uses reset-separated host-timed
250/500/1000ms windows. MT7925 issues three sequential firmware one-shots, each
with a two-second event deadline and one matching ACK. It verifies both event
arrays against the stopped timer banks and checks all stopped views again after
100ms while capture and queries continue. No next activation starts until the
previous event, stop and stable-repeat checks complete.

Normal completion restores the original masks with readback, then reloads
firmware. On cancellation/error with acquisition pending, the probe stops the
USB worker and **reloads without a potentially timer-racing masked restore**.
There is no proven MT7925 host command to cancel the already armed callback.
Restoring register bits alone is not a cancellation guarantee or history recovery.

Current [session evidence](../research/evidence/r32-histogram-session-2026-09-06.json)
records three successful channel6 windows on each chip. MT7925 events arrive at
512.395/512.048/511.623ms, with49,435/53,133/48,279 samples in each timer array.
MT7921 records29,063/54,695/113,946 samples, still entirely bin0. Both retain
normal capture and matched counter/thermal queries without queue overflow or USB
errors; all stop/repeat, restoration and reload checks pass. Host command-to-event
time includes firmware/transport delay and is not exact sample exposure.

Channel36 repeats also pass: MT7925 reports62,042/61,879/61,935 samples in each
timer array, predominantly bin0, while normal capture continues. MT7921 still
receives no normal frames on36 despite bin0 histogram accumulation: this repeats
the prior weak5GHz limitation, not a healthy RF qualification. SIGTERM during
the first active acquisition on each chip exits130 after worker stop and full
reload, exercising the pending-acquisition cleanup policy above.

The MT7925 ordinary index1 bank remains a distinct observation (about63,500
samples, predominantly bin10), not an extra event array or an interchangeable
receiver. Different counts/distributions cannot yet identify their physical cause.

The [public-guard gate](../research/evidence/r32-histogram-guard-2026-09-06.json)
adds12 fresh runs: both implementations/chips on6/36, plus active cancellation.
All completed windows pass bank/stop/repeat/restoration checks; all12 reload
successfully with no reported USB/queue-overflow errors. Transport failures at
every begin/finish/restore stage (including failed writes that reached hardware)
and pending-timer refusal are tested against matching Python/C operation traces.
The older dongle remains bin0-only and weak/intermittent on5GHz: its new Python36
run receives13 total frames, native36 zero. Cancellation is a recovery check,
not proof of healthy RF reception during its short baseline.

Here `reload_alive` means firmware bring-up completed and a register-health
check succeeded, not that post-reload capture was tested. The old-radio native
channel6 run received131 frames, but a later channel6 cancellation baseline was
already silent before activation. Subsequent long and unchanged-main controls
confirm sustained old-radio RF silence; its cause remains unresolved. These
short guard results do not override that [current RF acceptance failure](TESTING.md#r32-current-mt7921-rf-failure-and-soak-status-2026-09-06).

Included candidate: narrowly experimental raw histograms on these pinned profiles,
with coverage/cadence/calibration unavailable. Longer-session acceptance and
combined-feature qualification remain separate. Earlier firmware traces, channel
and own-TX controls remain
in [MT7925 findings](MT7925_NOISE_HISTOGRAM.md), [legacy findings](LEGACY_PHY_HISTOGRAM.md)
and [own-TX coverage limitations](NOISE_SELF_TRANSMIT.md).
