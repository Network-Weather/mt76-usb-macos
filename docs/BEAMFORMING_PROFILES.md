# MT7925 beamforming profile read surface

## Confirmed 2026-09-05: PFMU tag and profile-data queries work

The Netgear A9000 (`0846:9072`, RAM build `20260813113118`) answers UNI **0x33**
beamforming tag **5** (PFMU tag read) and tag **7** (profile data read). Seven
fresh-boot runs produced the expected events and passed subsequent alive and
cleanup-reload checks. No association, sounding, packet transmission, profile
allocation/write, calibration change, or nonvolatile write was performed.

This is a new **read surface**, not demonstrated CSI, valid channel matrices,
angle-of-arrival, or calibrated per-stream SNR. Nonzero bytes and the profile's
validity bit are insufficient to establish a live measurement.

Tool: [beamforming_read_probe.py](../research/beamforming_read_probe.py).
[Sanitized evidence](../research/evidence/beamforming-profiles-2026-09-05.json)
contains event/header metadata and payload hashes, never profile coefficients.

## Identification from loaded code

[Loaded-code/ROM investigation](MT7925_LOADED_FIRMWARE.md) established GP
`0x02212800` and a 30-slot live table at `0x02212a18`. Its entries match the
station driver's BF tag enum: tag-read/write 5/6, profile-read/write 7/8, BFEE
hardware control 0x12, software tag write 0x13, null mode-control 0x14, and PFMU
data write 0x16. The read handlers corroborate more than numeric matches:

| Handler | Request fields relative to command buffer | Output |
|---|---|---|
| `0x009169b0`, tag 5 | profile `+0x38`, BFer `+0x39`, band/TxBf `+0x3a` | EID 0x33, two seven-word tag blocks |
| `0x0091689c`, tag 7 | profile `+0x38`, BFer `+0x39`, subcarrier u16 `+0x3a`, band/TxBf `+0x3c` | EID 0x33, fixed 268-byte data block |

Firmware loads EID `0x33`; hardware returned that event family, tags and sizes.
The earlier `0xc00000bb` miss path belongs to this BF dispatcher, **not the
unrelated UNI 0x32/0x46 engineering refusals**. Sounding tags 0/1 and allocation
tags 3/4 are absent from this table. We did not probe them or infer that every
firmware route lacks those capabilities.

## Framing: read tags inside a SET envelope, unsolicited replies

The vendor bridge uses UNI option **0x06** (UNI + SET, no ACK), even for these
read tags. `wlanoidTxBfAction` chooses `fgSetQuery=true`, `fgNeedResp=false` for
unified commands; `nicUniCmdBFActionTagRead/DataRead` supplies the read tags.

Firmware clears the request sequence byte before constructing its event
(`0x9169f2` for tag 5; `0x9168d8` for tag 7). Every measured profile event had
**sequence zero**, while our request sequence was 13. Ordinary `mcu_wait`
request-sequence matching would discard the useful event as stale.

The probe has one outstanding request after a fresh boot and accepts only the
expected EID/tag/exact size with sequence zero or matching sequence. This is
not permission to accept arbitrary unsolicited events in a production command
queue; profile correlation and concurrent requests need separate handling.

| Read | Request payload | Event body after 44-byte C3 MCU RX header |
|---|---|---|
| tag 5 | reserved 4 + TLV length 68; profile, BFer, band; zeroed output slots | 68 bytes: reserved 4, TLV length 64, BFer/reserved 4, tag1/tag2 56 |
| tag 7 | reserved 4 + TLV length 12; profile, BFer, subcarrier, band | 280 bytes: reserved 4, TLV length 276, subcarrier/reserved 4, data 268 |

The tool allows only profile 0/1, BFer 0/1, band zero and subcarrier zero. It
collects for at most 1.5 seconds / 64 transfers, then reloads normal firmware.
No raw ambient frames or coefficient arrays are emitted or saved.

```sh
python research/beamforming_read_probe.py --tag 5 --profile 0 --bfer 0
python research/beamforming_read_probe.py --tag 7 --profile 0 --bfer 0
```

## Controls and limits

- Profile-zero tag blocks repeat exactly after fresh boots in both directions.
  BFer=0 has one nonzero payload byte; candidate fields show explicit-BF=1,
  invalid=0, all dimensions/mode codes and SNR bytes zero. **Invalid=0 alone
  does not establish a live/usable profile.**
- BFer=1 has four nonzero payload bytes, invalid=1, and candidate SNR bytes
  beginning 234/42. Those bytes are not accepted as meaningful SNR measurements.
- BFer=0 subcarrier-zero data changed between fresh boots (28 versus 27 nonzero
  bytes, different hashes) without controlled sounding. BFer=1 data had four
  nonzero bytes. Stale/default/uninitialized contents remain possible.
- Candidate metadata bits come from the vendor Connac3 `rFieldv2/v3` definitions,
  including invalid bit 28. They remain raw fields, not calibrated units.

Next: establish profile provenance and an independently observed controlled
stimulus before interpreting values as measurements. Missing sounding/allocation
entries are a separate firmware-path question, not a reason to write arbitrary
coefficients into profile memory.

## References and validation

Protocol facts (not copied implementation) from Motorola gen4m commit
[`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/tree/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec):
`include/nic_uni_cmd_event.h` BF enums/layouts, `nic/nic_uni_cmd_event.c` conversion
and event handling, `common/wlan_oid.c` SET/no-ACK choice, and `include/wlan_oid.h`
PFMU tag unions. Firmware hash is pinned in the loaded-code document. Twenty
offline tests cover request bounds, exact size/sequence filters, ambient-frame
rejection, metadata bits, and exclusion of write/sounding tags.
