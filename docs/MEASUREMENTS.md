# Named MCU measurements (R32)

Implemented on `feat/measurement-api`, not yet released. Python
`mt76_measurements` and C `mt7921_radio.h` expose the same finite raw-counter
profile; `mt7921_mcu.h` also declares query-only thermal measurements. CSI,
histograms and calibrated occupancy retain their [separate delivery gates](NEXT_RELEASE.md).
CSI now has [pure wire/parser parity and a short coexistence gate](CSI_API.md);
its public streaming lifecycle is not yet promoted.

## Callable contract

| Python | C | Meaning |
| --- | --- | --- |
| `Counter`, `counter_descriptors(chip)` | `MT_COUNTER_*`, `mt_counter_descriptor(chip, counter)` | Named profile with offset, unit category, wire/hardware/accumulator widths, known tick period and hardware saturation flag |
| `build_mib_request`, `parse_mib_reply` | `mt_mib_request`, `mt_mib_parse` | Pure bounded wire helpers; EXT one entry, UNI up to 16, unique complete requested values |
| `parse_mib_event` | validation in `mt_mib_read` | DMA length/type/sequence checks; USB padding cannot supply missing values |
| `read_counters(dev, counters)` | `mt_counter_read(dev, names, count, &sample)` | Band0 MCU-only sample with outer host-monotonic microsecond interval; no MMIO fallback |
| `build_thermal_request`, `parse_thermal_event` | `mt_thermal_request`, `mt_thermal_parse` | Query-only sensor wire helpers with DMA/type/sequence validation |
| `read_thermal(dev, action)` | `mt_thermal_read(dev, action, &sample)` | Reported temperature on both chips; separately labeled raw ADC on MT7925 |

The named read validates the entire request before I/O. MT7921 reads one offset
per command; MT7925 uses one batch. Both return results in requested order.
An unsupported name is an error (Python `ValueError`, native unsupported result),
not a successful zero. Truncated/missing/duplicate replies fail the sample;
native named-read output remains unchanged on failure, including a partially
completed old-chip sequence. A failed operation may still have consumed hardware
counts; unchanged output does not mean unchanged hardware.

The profile describes the repository's checksum-pinned firmware, not automatic
identification of arbitrary loaded firmware. Use `load_firmware` in Python or
the checksum-checked native probe loader, and retain firmware hashes with evidence.
Caller-supplied replacement firmware is not qualified by a matching chip name.

## Current names and interpretation

Both chips: `rx_mpdu`, `rx_mdrdy`, `primary_cca`, `cca_nav_tx`.
MT7925 additionally: `rx_fcs_error`, `cck_rx_duration`, `ofdm_rx_duration`,
`primary_ed`, `nav`, `idle_slots`. Unsupported names are absent on MT7921.

- Names are source/experiment-backed, not an additive occupancy decomposition.
  Primary CCA is old offset11/new offset17; new offset19 is CCA+NAV+TX.
  ED is not non-Wi-Fi-only activity. CCK duration concerns CCK reception, not
  generic receive duration; zero CCK ticks on 5 GHz is not zero channel activity.
- Values are raw firmware counters. Duration units are `DURATION_TICKS`, with
  unknown conversion (`None` in Python, zero `tick_ns` in C). Historical 1-us
  assumptions do not settle the source's 1.024-us ambiguity.
- Wire widths are 32/64 bits, independent of hardware field and software
  accumulator widths. Unknown widths are `None`/zero. No new automatic delta,
  wrap, percentage or reset inference is provided. Existing `mt_mib_delta`
  requires independently justified width/epoch/plausibility; do not blindly feed
  it the compatibility `counter_bits` wire-width field.
- Idle slots have a source/empirically supported 9-us cadence and a saturating
  16-bit hardware field. Firmware accumulates those samples: its total can exceed
  65,535 while losing idle slots between reads. The flag describes that hazard,
  not detection that a particular returned total is saturated or lossless.
- A batch is not a simultaneous hardware latch. Keep request-open/close times,
  session epoch and channel generation; do not compare across retunes/resets or
  competing read-clear owners. No freshness detector is implied by an unchanged
  value. `legacy_dropped_frames`/`raw.dropped_frames` excludes session queue loss.

Sources: [MIB mapping/ownership](MT7925_MIB.md),
[idle/subchannel semantics](SUBCHANNEL_MEASUREMENTS.md), and
[old-chip mapping](FIRMWARE_RECON.md). Inactive-width secondary fields and
known-invalid offset94 are not in the named profile.

## Query-only thermal measurements

`ThermalAction.TEMPERATURE` returns a raw u32 and its signed reported Celsius
value. `RAW_ADC` is MT7925-only and has no temperature conversion (`None` in
Python, `has_temperature=false` in C). Neither API changes thermal protection,
selects arbitrary sensors, or implies that the two chips measure the same physical
location. Samples retain host-monotonic microsecond intervals and legacy MCU drops.

The old chip uses EXT2c; MT7925 uses UNI35 QUERY_ACK option3, tag0, band0,
actions0/1. Invalid actions fail before I/O. Parsers reject malformed lengths,
sequence mismatches, and the known EXT unsupported-command reply rather than
reporting its status254 as temperature. Native sample output stays unchanged on
failure. The native convenience getter and MT7925 Python getter reuse this path;
the older Python getter retains its compatibility implementation.

Call `read_thermal` inside `session.call`, or `mt_thermal_read` inside an
`mt_session_call` callback. Add `--thermal` to either session probe to interleave
thermal reads with named counters and normal capture. The new-chip probe brackets
each ADC query with two temperature queries; the old chip only queries temperature.

[Thermal qualification evidence](../research/evidence/r32-thermal-2026-09-06.json)
retains an initial native MT7925 mixed-run failure. Investigation reproduced a
counter-parser bug in both languages: scanning inside a complete value could
invent a second TLV. Both parsers now consume whole entries, and research readers
reuse the corrected parser. The exact failed live reply was not saved, so that
bug is a plausible explanation, not a proven attribution of that failure.
Fixed-parser 15-second Python/C runs passed on both chips with RX, retunes,
thermal and named-counter queries; they do not establish multi-hour stability.

## Experimental raw Group5 fields

The ordinary MT7921 `rxd.decode` result adds `raw_signal` only when the complete
18-word Group5 is inside both DMA and USB bounds, with Group3 present. C
`mt7921_rxd_frame_t` exposes `has_raw_signal` and two signed-byte arrays,
`fagc_ib_raw_s8[2]` / `fagc_wb_raw_s8[2]`. Python names are
`fagc_ib0_raw_s8`, `fagc_ib1_raw_s8`, `fagc_wb0_raw_s8`, `fagc_wb1_raw_s8`.
MT7925 does not use this layout and never receives these fields. Keep each
frame's PHY/FCS context. Presence establishes structural completeness, not sensor
freshness or a valid measurement across every PHY mode. These are firmware
receiver indices, not antenna labels, dBm, SNR or an interference classifier.
The [source/earlier controls](INBAND_WIDEBAND_SIGNAL.md) document the extraction;
research readers now reuse `rxd.decode_fagc`.

`Group5Guard(dev).begin()` / `.restore()` mirror native `mt_g5_*`: opt-in,
saved-bit/readback, preservation of unrelated bits, active-on-failure for retry.
Call restore in `finally` even if begin fails. While a session owns the device,
serialize these operations through its callback queue. Do not stack guards or
reset firmware during their lifetime. No ICS or RF-test mode is enabled.
Reporting is off by default; upstream's hardware-issue warning is not resolved.

[Four live cycles](../research/evidence/r32-group5-2026-09-06.json) expose an
important qualification limit: the first Python enabled phase received324
populated frames, but both native repeats and another Python run nearly stopped
receiving while enabled, recovering after restoration. This is not established
as a C bug; the cause remains unknown. One queued Group5 frame also survived
restoration in the first run. The raw decoder/guard is implemented and offline
tested, but dependable live Group5 acquisition is **not qualified**. No sensor
validity should be inferred from the isolated odd values in the failing runs.

## TX-status timing without new transmit controls

`parse_tx_status(chip, raw, max_records=128)` returns immutable `TxStatus`
records and matches native `mt_tx_status_parse`. Both require type0 TXS,
chip-specific prefix/stride, complete DMA/record bounds and sufficient output
capacity; malformed packets fail without partial output. USB padding is ignored.
The Python capacity is0..2047 (maximum that fits the old-chip u16 DMA length).
A well-formed empty TXS packet is an empty result, not an error. Research status
readers reuse the installed parser while retaining their existing output keys.

Both chips expose raw rate/power, signed power representation, sequence, PID and
error bits. MT7925 additionally exposes raw bandwidth, STBC, 16-bit TX delay and
32-bit timestamp. Only format0 supplies TX count and 25-bit front-time. C uses
`has_timing` / `has_front_time` / `has_tx_count`; Python uses `None` for absence.
Old-chip timing is not promoted; neither are format1 MPDU-counter hypotheses,
noise or ACK RSSI measurements. Embedders must rebuild for the expanded C struct.

`timestamp_tick_ns`, `front_time_tick_ns`, `tx_delay_tick_ns` are1000/32000/32000
only on pinned MT7925 format0, following [earlier measured controls](TX_STATUS_TIMING.md).
Other formats have unknown scales (`None` / native0), even when raw layout fields
are present. Timestamp and front-time are separate wrapping device clocks, not
synchronized RXD or host time; front-time is not a duration. Delay includes packet
and service time, not pure contention. No automatic unwrap, clock alignment,
calibrated airtime, exact latch point or ranging calculation is supplied.

[Live shared-byte qualification](../research/evidence/r32-tx-status-2026-09-06.json)
matched all12 format0 statuses in Python/C during an existing channel6 CCK/OFDM
experiment. The independent receiver obtained8/12 exact good-FCS frames, all CCK;
the two OFDM brackets remained unreceived. This qualifies the raw parsers on those
status bytes, not successful delivery or an expanded transmit profile. The run
used Python transport with native decoding of the same bytes; both radios stayed
alive and transmitter firmware reload succeeded. Native `mt76_radio_probe` also
exports the new fields as redacted metadata without changing its TX limits.

## Use during capture

After explicit pinned-firmware bring-up, monitor/sniffer configuration and tune:

```python
from mt76_measurements import Counter, read_counters
from mt76_session import AcquisitionSession

with AcquisitionSession(dev) as session:
    sample = session.call(lambda d: read_counters(d, (Counter.RX_MPDU, Counter.PRIMARY_CCA)))
    context = session.snapshot()  # epoch/channel; serialize retunes with sampling
    packet = session.read(timeout=1)
    # Decode packet outside the USB worker; log only redacted aggregates by default.
```

In C, call `mt_counter_read` from a short `mt_session_call` callback, passing a
caller-owned `mt_counter_sample_t` through its context. Native descriptors have
static lifetime; the sample owns its copied scalar values. The session probes
provide runnable Python/native examples using no research imports:

```sh
python scripts/session_probe.py --usb-id 0846:9072 --fw /path/to/firmware --seconds 20 --named-counters
make -C c mt76_session_probe
c/mt76_session_probe --usb-id 0846:9072 --fw /path/to/firmware --seconds 20 --named-counters
```

Do not run both commands simultaneously on the same adapter. `--named-counters`
exports raw named totals with the session epoch, requested channel and host
interval. Defaults still sample only primary CCA. Snapshot context is safe in
these single-control-caller examples; concurrent applications must serialize
sampling/context collection against retunes. The API does not invent RF channel
labels for buffered packets. Raw frames/ambient identifiers are not exported.

## Qualification checkpoint

The slice passes shared Python/C request/profile/parser fixtures, native fake-USB
read/partial-failure tests, and malformed DMA/sequence/length tests. Sanitizers
include the named-read failure paths. The installed wheel imports both new
modules outside the checkout.

Short live runs exercise all four/ten named counters with normal RX and retunes;
see [dated evidence](../research/evidence/r32-named-counters-2026-09-06.json).
MT7925 receives normally in these runs. MT7921's weak/no 5-GHz reception is also
observed on unchanged main; its baseline receives on 2.4 GHz. The new probes accept
`--band 2.4GHz` for the bounded channels1/11 qualification. Neither
short tests nor a zero process exit establish multi-hour stability, calibrated
units, hot-unplug, or a healthy independent transmit reference.

The final 12-second 2.4-GHz 1/11/1 runs passed capture, all named queries and
orderly stop on both chips in both languages: Python/C decoded 534/768 frames on
MT7921 and 1,561/1,388 on MT7925, with 11 named samples and two retunes per run.
Queue drops, malformed transfers, USB errors and legacy MCU discards were zero.
Off-requested-channel records around retunes are retained, not relabeled or
discarded to manufacture perfect channel agreement. Counts from separate runs
are not a same-traffic sensitivity comparison.
