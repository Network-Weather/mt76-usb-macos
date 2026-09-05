# Station firmware test-mode surface

Measured 2026-09-04 Pacific / 2026-09-05 UTC on the attached MT7961 ALFA and MT7925
A9000, macOS 26.6.1, Python 3.14.7, pinned firmware from [NOTICE](../NOTICE.md).
Research only. [Redacted evidence](../research/evidence/station-testmode-2026-09-04.json)
contains commands' scalar outcomes and the bounded receive perturbation.

## MT7961: mode entry unlocks queries, live sampling not established

The upstream station interface is **CE command 0x01**, not EXT RF_TEST 0x04.
`mt7921/testmode.c` and `mt7921/mcu.h` at mt76 `c5a3bd91` define a 12-byte
payload: action byte, three zero bytes, two little-endian 32-bit parameters.
The command envelope is CE SET even for a payload-level query (action 2).

In normal monitor mode, all seven tested query selectors were silent. After
`action=0, param0=1, param1=0` (idle RF-test mode), all seven returned a matched
16-byte body whose first eight bytes echoed the selector and returned a value:

| Selector | Reference name | Returned u32 | Evidence level |
|---|---|---:|---|
| 0 | test interface version | 16777218 (`0x01000002`) | responding interface; reference header declares `0x01000001`, so do not assume identical semantics |
| 34 | RX OK count | 0 | no live counting yet |
| 35 | RX error count | 0 | no live counting yet |
| 41 | RX PHY statistics | 0 | only first scalar examined; not a validated statistics layout |
| 43 | temperature | 2097211 | raw packed word, not degrees |
| 46 | RX RSSI | 146 | raw word, not calibrated RSSI |
| 50 | wideband/in-band RSSI | 2646167382 | raw packed word; antenna ordering and units not established |

Each selector was tested after fresh boot and followed by full firmware reload
and successful alive check. The mode-switch request itself is sent without waiting,
as upstream does. The query behavior change, rather than USB completion alone,
demonstrates access to the test interface. No factory TX-start, tone, calibration,
efuse, or other nonvolatile write was issued.

### Bounded receiver activation experiment

After idle mode entry, a separate run sent these payload-level SET operations:
function 1/value 0 (stop), function 18/value 5180000 (channel frequency in kHz),
function 15/value 0 (20 MHz), function 1/value 2 (start **receive**, not transmit).
The reference `gl_hook_api.c` specifies the frequency units and start-RX operation.
These SET requests were not read back, so their effect is not independently confirmed.

MT7925 then submitted 36 synthetic OFDM6 no-ACK probes on channel 36 at 50 ms
spacing: 12 at power code 0, 12 at -16, 12 at 0 again. Quiet 0.6-second dwells
bracketed them. Queries 34/35/46/50 were sampled initially and after each phase.
All samples were unchanged: **0, 0, 146, 2155888704** respectively. Both chips
remained alive and both firmware reloads succeeded.

This does **not** validate a noise floor, live RSSI, or RX counter. The transmitter
used the previously independently measured OFDM path, but this particular run did
not independently decode its packets: the other dongle was the test receiver.
Untested prerequisites include RX-chain/path setup, other test state, and version-2
query semantics. A working query handler may expose cached or sentinel values.

## MT7925: receive-stat command result, not a statistics event

UNI `0x32` GET_STAT_ALL tags 8 and 9, each with an eight-byte TLV and four-byte
reserved prefix, produced 32-byte matched replies in normal mode and after an
idle RF-test-mode entry **attempt**. Neither produced a valid statistics TLV.
Mode-entry success on this chip was not established.

A follow-up tag-9 query explicitly parsed a command-result body: echoed CID
`0x32`, status **`0xc00000bb`**, nonzero. Earlier outputs mistakenly labeled the
status halves as a tag/length (187/49152); the evidence preserves that as an
unrecognized prefix, not as valid TLV data. The probe now distinguishes the
command result. This is an exact negative for these requests on the pinned image,
not proof that every testmode path is absent or that a factory firmware is required.

Important framing fact: `mt7925_mcu_fill_message` special-cases UNI `0x32` and
`0x46` to option **0x02 query / 0x06 set**, omitting the ACK bit. The research
probe overrides these two options locally; production Python/C code is unchanged.
The attempted mode entry used UNI 0x46, tag 0, length 92, action 0, opmode 1,
zero-padded to the upstream 96-byte request size.

## Reproduction and next leads

Use the project venv and set `MT76_FW_DIR` to the pinned firmware directory:

```sh
python research/station_testmode_probe.py --chip mt7961
python research/station_testmode_probe.py --chip mt7961 --test-mode
python research/station_testmode_probe.py --chip mt7925
python research/station_testmode_probe.py --chip mt7925 --test-mode
python research/testmode_receiver_probe.py --acknowledge-experimental-transmit
```

The first four issue no transmit-start command. The last transmits exactly the
bounded synthetic probes described above. Every run resets volatile state.
No ambient frames, identifiers, USB serials, or firmware bytes are saved.

Next concrete leads, not capability claims:

- Establish the test receiver's required RX-path/band settings and verify a
  counter follows independently controlled traffic before interpreting its signal words.
- Use the now-responding MT7961 station mode-switch path to investigate ICAP/spectrum
  status. Earlier standalone EXT spectrum silence did not test this route.
- MT7925's UNI 0x46 engineering-query action is distinct from UNI 0x32 statistics;
  the vendor bridge maps GET_AT action 2 to GET_AT_ENG action 4. This remains untested.
- Legacy station `ACCESS_RX_STAT` uses a separate eight-byte request with a
  sequence and requested count; its CID and live behavior still need checking.

## Primary protocol reference

Motorola's public MediaTek gen4m source, pinned at
`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`:
[rftest.h](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/rftest.h),
[UNI formats](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h),
[legacy-to-UNI bridge](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_uni_cmd_event.c),
[QA hook protocol usage](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/os/linux/gl_hook_api.c).
The read files carry BSD-2-Clause headers. Used for protocol facts; no vendor
implementation or header copied into this repository. Request builders and
bounded experiments are independent. This is a different source from the
proprietary AP-driver reference described in RELATED_WORK.
