# Named MCU measurements (R32)

Implemented on `feat/measurement-api`, not yet released. Python
`mt76_measurements` and C `mt7921_radio.h` expose the same finite raw-counter
profile. This first slice does not include thermal, CSI, histograms or calibrated
occupancy. Those retain their [separate delivery gates](NEXT_RELEASE.md).

## Callable contract

| Python | C | Meaning |
| --- | --- | --- |
| `Counter`, `counter_descriptors(chip)` | `MT_COUNTER_*`, `mt_counter_descriptor(chip, counter)` | Named profile with offset, unit category, wire/hardware/accumulator widths, known tick period and hardware saturation flag |
| `build_mib_request`, `parse_mib_reply` | `mt_mib_request`, `mt_mib_parse` | Pure bounded wire helpers; EXT one entry, UNI up to 16, unique complete requested values |
| `parse_mib_event` | validation in `mt_mib_read` | DMA length/type/sequence checks; USB padding cannot supply missing values |
| `read_counters(dev, counters)` | `mt_counter_read(dev, names, count, &sample)` | Band0 MCU-only sample with outer host-monotonic microsecond interval; no MMIO fallback |

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
