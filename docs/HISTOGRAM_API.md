# Experimental raw histogram integration (R32)

Implemented on `feat/measurement-api`, not released. The installed Python module
`mt76_histogram` and native `mt76_histogram.h` expose matching **pure wire/record
helpers**. Public acquisition lifetime/cleanup and native live orchestration are
still separate gates; this is not yet a ready-made noise measurement service.

| Python | C | Profile |
| --- | --- | --- |
| `build_histogram_request` | `mt_histogram_request` | MT7925 only, fixed UNI36/tag2 one-shot request, SET/ACK option7; no duration, index, threshold or address parameters |
| `parse_histogram_ack` | `mt_histogram_ack` | Exact EID1/nonzero sequence/CID36/status envelope; return actual status |
| `parse_histogram_event` | `mt_histogram_event` | MT7925 EID36/sequence0, exact96-byte body, tag2/length92, two arrays of11 u32 bins |
| `parse_legacy_histogram` | `mt_histogram_legacy` | MT7921 only, exactly44 little-endian bytes from the already stopped ordinary bank |

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

## Coexistence and repeated one-shot gate

```sh
python research/histogram_session_probe.py --chip mt7921 --fw PINNED_DIR \
  --channel 6 --reset-shared-histogram
python research/histogram_session_probe.py --chip mt7925 --fw PINNED_DIR \
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

Remaining: native live acquisition, reusable matched Python/C ownership/cleanup
helpers and fault injection; then independent inclusion/defer and longer-session
acceptance decisions. Earlier firmware traces, channel and own-TX controls remain
in [MT7925 findings](MT7925_NOISE_HISTOGRAM.md), [legacy findings](LEGACY_PHY_HISTOGRAM.md)
and [own-TX coverage limitations](NOISE_SELF_TRANSMIT.md).
