# Station firmware test-mode surface

Measured 2026-09-04 Pacific / 2026-09-05 UTC on the attached MT7961 ALFA and MT7925
A9000, macOS 26.6.1, Python 3.14.7, pinned firmware from [NOTICE](../NOTICE.md).
Research only. [Redacted evidence](../research/evidence/station-testmode-2026-09-04.json)
contains commands' scalar outcomes and the bounded receive perturbation.

**Follow-up:** the MT7961 sampler is now active with an explicit RX-path write.
The initial negative below is retained as history; see [RX-path activation](#rx-path-activation-follow-up).

## RX-path activation follow-up

Four matched-condition runs isolated the missing setting. Each began with 12/12
synthetic OFDM6 probes independently decoded in normal monitor mode, then entered
RF-test mode and used the same 36-probe/quiet/attenuation sequence described below.
All were on channel 36 at 20 MHz; both firmware reloads passed after every run.
[Redacted evidence](../research/evidence/testmode-rx-path-2026-09-04.json).

| Additional setup | RX OK initial → last phase | RX error initial → last phase | Signal words |
|---|---:|---:|---|
| Band 0 + RX mask 3 + explicit CBW/DBW/primary | 7 → 213 | 1 → 142 | changing |
| Band 0 + RX mask 3, no extra bandwidth writes | 8 → 224 | 11 → 193 | changing |
| None (same monitor control) | 0 → 0 | 0 → 0 | fixed |
| Band 0 only | 0 → 0 | 0 → 0 | fixed |

**Critical protocol detail:** CE TEST_CTRL action 1, function **106**, value
**`3 << 16` (`0x00030000`)**, following function 104/value 0 (DBDC band 0).
The receive antenna mask occupies the **high 16 bits**. The reference
`operation_gen4m.c::mt_op_set_rx_path` specifies that encoding. Its separate QA
wrapper contains a logical-OR expression which collapses a nonzero mask to 1;
we did not copy that expression. Both firmware-visible values and experiment
outcomes are recorded rather than inheriting correctness from a vendor wrapper.

The path-only run also tested stop: after function 1/value 0, counts reached
225/193 and remained exactly 225/193 across the subsequent 0.6-second dwell;
both signal words also froze. This provides start/stop evidence for a live
test-mode receiver, not merely a responsive query handler.

Queries of configuration selectors 15/18/71/72/73/104/106 returned echoed selectors
with zero first values even for the nonzero frequency/path settings. They are
**not validated configuration readbacks**. Behavioral controls establish activation.

Limits: aggregate counters include ambient frames; individual query reads are
sequential, not an atomic sample. RSSI words are raw, packing/units remain unverified,
and the attenuation phases did not establish a calibrated or probe-specific signal
response. This is a separate test mode, not concurrent normal monitor capture.
No new Linux implementation or shipped Python/C API is asserted.

Reproduce using the project venv and pinned firmware directory:

```sh
python research/testmode_receiver_probe.py --acknowledge-experimental-transmit --rx-path 3 --verify-monitor-control
python research/testmode_receiver_probe.py --acknowledge-experimental-transmit --select-band --verify-monitor-control
```

The first enables sampling, the second is the band-only negative control.
Each invocation sends at most 48 paced no-ACK packets and resets both devices.

## ICAP status through station mode entry

The same station CE 0x01 mode switch can request opmodes 1 (RF-test),
2 (ICAP) and 4 (spectrum). A status-only experiment then sent EXT 0x04 **QUERY**,
88-byte payload: action 1, three zeros, little-endian function 12 (`0x0c`),
80 zero bytes. This follows `wlanoidExtRfTestICapStatus` in the pinned station source.
No capture-start, IQ dump, ADC/gain change, or transmitter-start command was sent.

After requesting ICAP mode 2, a 1.5-second bounded receive window observed a
sequence-matched EID `0xed` / EXT EID `4` event, 68-byte body, function 12 and
raw `capture_done=1`. Mode-1 and mode-4 attempts produced no firmware events in
their corresponding windows. All attempts passed alive and firmware-reset cleanup.
Two more mode-2 attempts reproduced the same reply across fresh firmware resets
(three successful ICAP status attempts total).
[Evidence](../research/evidence/icap-status-2026-09-04.json).

This establishes a **responsive ICAP status interface**, not a working capture.
`done=1` was reported without starting any capture and cannot establish sample
validity. Mode-4 silence is not proof that spectrum functionality is absent.
The event collector handles unsolicited as well as sequence-matched notifications;
all reported positive replies here were sequence-matched. It excludes normal
frame payloads and records only event metadata.

```sh
python research/icap_status_probe.py
python research/icap_status_probe.py --mode 2 --mode 2
```

The next ICAP experiment is a bounded on-chip capture with known capture-node
selection and explicit sample ceiling, followed by status and shape/count-only
validation of retrieved samples. Do not configure host-memory/EMI DMA from a
phone-driver reference on this USB host, or assume raw IQ can be calibrated yet.

## MT7961: initial mode-entry and query experiment

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

- RX-path/band activation is established above. Next isolate per-chain signal-word
  packing and controlled-traffic effects before interpreting the words as measurements.
- ICAP status now responds through station mode 2, as recorded above. Capture-start
  prerequisites, on-chip node selection and bounded sample retrieval are next.
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
The follow-up RX path comes from
[operation_gen4m.c](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/wlan_service/glue/hal/gen4m/operation_gen4m.c),
checked against the separate QA wrapper in `os/linux/gl_qa_agent.c` at that revision.
ICAP status requests use
[wlan_oid.c](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/common/wlan_oid.c)
and [wlan_oid.h](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/wlan_oid.h)
at the same revision.
The read files carry BSD-2-Clause headers. Used for protocol facts; no vendor
implementation or header copied into this repository. Request builders and
bounded experiments are independent. This is a different source from the
proprietary AP-driver reference described in RELATED_WORK.
