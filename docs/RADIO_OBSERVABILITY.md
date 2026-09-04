# Radio observability exploration

Started 2026-09-04. Branch: `spike/radio-observability`.

## Questions and experiment order

1. What is in the extended receive vectors already delivered by MT7925 USB?
   Establish group boundaries, variation by PHY mode, and agreement with independently
   decoded frame fields before assigning meanings to unknown words.
2. What link evidence is lost by the minimal control-frame parser? Decode RTS/BlockAck
   transmitter addresses, sequence windows, and acknowledgment bitmaps. Separate observer
   loss from the receiving station's reported delivery.
3. Can the two radios share a useful time base through jointly received frames?
   Measure wrap, drift, ambiguity, and residual error before using packet timing for
   cross-channel forwarding hypotheses.
4. Can a bounded controlled transmitter or documented receive-vector enable falsify
   candidate fields? Keep the reference receiver running; record recovery and failures.
5. Follow ICAP, TX-status, and Bluetooth leads when the above results identify a specific
   question. Existing negative IPI results are not a reason to repeat the same probes.

The operator authorized transmit and receive experiments on both dongles for this session,
and requested regular commits. Tools retain explicit transmit flags for future operators.
Network identifiers and payloads stay out of committed evidence. Findings remain instrument
measurements, not site-specific topology verdicts.

## Initial passive census

Reference firmware and adapters: same pair and pinned firmware as
[MT7925 MIB characterization](MT7925_MIB.md). Three seconds per target, sequential
20 MHz dwells on 2.4 GHz channel 6, 5 GHz channel 36, and 6 GHz channel 37.
These initial results came from an inline diagnostic, before the reproducible probe below.

| Adapter | Frames by band (2.4 / 5 / 6 GHz) | RX group mask |
| --- | --- | --- |
| MT7961 `0e8d:7961` | 159 / 196 / 74 | `0x07`: groups 1, 2, 3 |
| MT7925 `0846:9072` | 143 / 242 / 17 | `0x17`: groups 1, 2, 3, 5 |

A separate four-second MT7925 channel-36 dwell returned 374 Group-5 records.
Of its 24 words, words 2, 6, 7, 8, 9, 10, 19, 20, and 21 varied (nine words).
The prior conversational summary incorrectly said ten: the recorded distinct-value counts
establish nine. Word variation alone does not prove a measurement's meaning or freshness.
The capture also contained 8 RTS, 121 CTS, 5 BlockAck, and 1 ACK.

The first inline census's control-frame count used the wrong dictionary key (`type` instead
of `ftype`), so its empty control counts are invalid. The separate dwell fixed that key;
group-mask and frame-count results are unaffected.

## Source evidence and limitations

All mt76 references in this section are at `c5a3bd91aa735b669618610d5f0ebfa5786845a6`.

- `mt7925/mac.c:mt7925_mac_fill_rx` describes Group 3 as four words and Group 5 as
  24 words; the local `rxd_connac3.py` steps over Group 5 without decoding it.
- `mt76_connac3_mac.c:mt76_connac3_mac_decode_he_radiotap` reads BSS color, TXOP,
  uplink indication, spatial reuse, and other fields from extended RXV words. Its indexes
  start at Group 3, not Group 5. This distinction must be tested.
- `mt7915/mac.c:mt7915_mac_fill_rx_vector` reads in-band/wideband RSSI, SNR, and
  frequency offset from a standalone RX-vector record. That is a different record type
  and chip; its offsets cannot be pasted into the MT7925 Group-5 decoder.
- `mt792x_mac.c:mt792x_mac_init_band` clears `MT_DMA_DCR0_RXD_G5_EN`, commenting
  that it disables RX rate reporting because of hardware issues. The userspace path
  nevertheless receives Group 5 on the A9000. Neither fact establishes that every field
  is correct. The corresponding MT792x register is band-0 `0x820e7000`, bit 23.
- `mt76_connac3_mac.h` contains MPDU-format TX-status noise/RCPI fields. Presence in a
  shared header is not evidence that MT7925 USB emits that format or valid noise values.
- Plaintext MT7961 region 1 contains `Current FWOpMode isn't ICAP`, `EvmRx%d=0x%02x`,
  and CFO diagnostics. This is evidence of code concepts, not a working host API.

## Interpretation boundaries

Received signal is the transmitter-to-observer path, not a measurement of the backhaul
receiver's signal. Clock agreement, packet correlation, four-address traffic, and advertised
Multi-AP/MLO roles are complementary evidence; none individually reconstructs an entire
mesh. A missing observed ACK or MPDU is not proof that the receiver missed it.
Per-frame signal quality is not an idle-channel noise survey. ED-active time remains
overlapping energy detection, not a non-Wi-Fi-only counter.
