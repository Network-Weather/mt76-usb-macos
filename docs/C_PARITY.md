# Native C acquisition parity

Sprint R30, Python reference baseline `6081908`, started 2026-09-04. The C
implementation remains an instrument, not a networking driver. This contract
covers acquisition primitives; it does not move site analysis into the driver.

## Port contract

| Python reference | C interface | Semantics and boundary |
|---|---|---|
| `rxd.decode`, `rxd_connac3.decode` | `mt7921_rxd_decode*`, `mt7921_rxd_frame_t` | Group-2 timestamp with presence flag; local 32-bit microsecond counter, wrap-aware downstream, not wall time or ranging |
| `research/rx_vector_probe.py:vectors` | `mt7921_rxd_groups`, frame `g3`/`g5` arrays | Group mask and explicit word counts; connac2 G3/G5 = 2/18 words, connac3 = 4/24; no Group-1 packet numbers or Group-4 addresses exported |
| `scripts/mcu_stats.py`, `research/mib_offset_sweep.py` | `mt_mib_request`, `mt_mib_parse`, `mt_mib_read` | MT7921 EXT 0x5a, one offset per request, measured 32-bit counter at reply-body byte 28; no offset echo in this firmware |
| `research/mt7925_mib_characterize.py` | same MIB interfaces | MT7925 UNI 0x22, atomic batch up to 16 offsets, unique echoed 64-bit counters; missing/duplicate/truncated entries fail rather than become zero |
| `research/rx_vector_probe.py` G5 cycle | `mt_g5_begin_device`, `mt_g5_restore` | MT7921 opt-in only, saved bit/readback, restore on failure as well as success; upstream hardware-issue warning remains |
| `research/dual_radio_probe.py:fixed_rate_txwi`, `research/tx_power_probe.py:power_txwi` | `mt_probe_txwi` | Connac2 CCK1 at zero offset; OFDM6 at codes 0/-8/-16; synthetic Probe Requests only |
| `research/mt7925_tx_probe.py` | `mt_probe_txwi`, `mt_probe_prepare`, `mt_probe_transmit` | Connac3 OFDM6/54, table slots 18/25, DIS_MAT enabled, codes 0/-8/-16/-32; no ACK, association, keys, or aggregation |
| Both TX-status research parsers | `mt_tx_status_parse` | Chip-specific prefix/stride, raw rate/power/error fields; signed power representation is not calibrated dBm; TX count only for connac3 format 0 |

All register/message layouts cite `openwrt/mt76` at
`c5a3bd91aa735b669618610d5f0ebfa5786845a6` in the C sources. Measured semantics
remain in [firmware reconnaissance](FIRMWARE_RECON.md),
[MIB characterization](MT7925_MIB.md), [RX observability](RADIO_OBSERVABILITY.md),
and [MT7925 TX](MT7925_TRANSMIT.md). Source-derived mechanisms are not claimed as
new Linux capabilities.

## Measurement rules

- MCU samples include host-monotonic request-open/request-close times and frames
  discarded by the MCU reader. Use midpoint-to-midpoint sample intervals, with the
  query spans retained as timing uncertainty. A separate frame dwell is not exactly
  the counter interval. There is still one reader per device, not a lossless queue.
- Counter widths are 32 bits on the MT7921 path and 64 bits on the MT7925 path.
  `mt_mib_delta` requires a caller-supplied plausible maximum and the same firmware
  epoch. Wrap and reset cannot always be distinguished from two observations.
- CCA offsets 11/19 concern the primary 20 MHz. MT7925 offset 20 is overlapping
  ED-active time, not non-Wi-Fi time. The CLI emits raw counters, not misleading
  busy-minus-decoded residuals or a noise-floor estimate.
- Extended vector words remain raw. HE/EHT interpretation, clock fitting, and
  BlockAck/mesh analysis remain Python/downstream. No candidate SNR/noise field or
  reconstructed 64-bit TSFT is exported as a verified measurement.
- Transmit commands require explicit acknowledgement. The new submission helper
  checks successful tune state, 20 MHz, measured band/channel/rate combinations,
  at most 60 attempts per boot, and at least 50 ms spacing. Failed writes consume
  an attempt. This does not implement regulatory-domain enforcement.
- Connac3 table state requires firmware reload after the experiment, including
  setup errors. Group-5 guards remain active after a restoration failure so callers
  can retry. Unplug, SIGKILL, or host failure may make restoration impossible.

## Verification

`tests/test_c_parity.py` compiles a native library in a temporary directory and
passes the same synthetic bytes through Python and C. It covers all 32 RX group
masks on both chips, timestamp absence/wrap values, DMA/group truncation, MIB
wire layout, TX descriptors, and both status record formats. Invalid inputs may
be rejected more strictly in C than in the exploratory Python parser.

`tests/c_parity_bridge.c` also injects stale MCU replies, ordinary timeouts,
transport failures, insufficient response buffers, and register read/write/
readback failures. `make -C c sanitize` runs those faults and 10,000 deterministic
malformed-input cases with AddressSanitizer and UndefinedBehaviorSanitizer. It is
part of `scripts/check.sh`, alongside existing C and Python regression tests.

Hardware qualification uses [`mt76_radio_probe`](../c/mt76_radio_probe.c), a
native CLI emitting redacted NDJSON. [`c_radio_pair.py`](../scripts/c_radio_pair.py)
only supervises two C processes: it waits for the receiver to be ready, runs the
bounded transmitter, and records independent exact-byte/rate counts, RSSI, TX
status, and cleanup. It stops the matrix on a failed strict all-frames check;
a missing observation remains a negative result, not proof of RF loss or success.

Dated live evidence and remaining untested behavior belong in
[TESTING.md](TESTING.md); passing offline tests alone does not establish hardware
parity. No iPad or baseline-connectivity implementation is included.
