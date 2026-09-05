# Transmit width and duration counters

MT7925 UNI MIB counters distinguish bounded 20/40MHz transmissions and track
payload-dependent transmit duration. Four fresh-boot trials use20 synthetic,
no-ACK Probe Requests each, with MT7961 independently checking exact payload,
FCS and PHY. This adds transmitter-side measurement to per-packet TX status;
it does **not** turn firmware success into proof of over-air reception.

## Source and live-ROM mapping

The pinned public gen4m [UNI counter enum](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h#L2672)
names the wire offsets below. Read-only live translation/ROM reads resolve
each through the [previously traced MIB path](MT7925_MIB.md):
u16 at`0x0224c220 + 2*offset`, ordinary ID to
`((ID + 0x3e810) & 0xffff) << 5`, domain29 ROM table`0x0084d79c`,
base`0x820ed000`. Only these resolved counters are queried.

| Wire offset | Source name | Internal ID | Hardware field |
| --- | --- | --- | --- |
| 22 | TX_BW_20MHZ | 28 | `0x820ed6ec[31:0]` |
| 23 | TX_BW_40MHZ | 29 | `0x820ed6f0[31:0]` |
| 24 | TX_BW_80MHZ | 30 | `0x820ed6f4[31:0]` |
| 25 | TX_BW_160MHZ | 31 | `0x820ed6f8[31:0]` |
| 28 | TX_DUR_CNT | 6 | `0x820ed050[23:0]` |
| 31 | MAC2PHY_TX_TIME | 3 | `0x820ed040[23:0]` |
| 85 | SU_TX_OK | 24 | `0x820ed6d0[31:0]` |
| 86 | TX_FULL_BW | 38 | `0x820ed718[31:0]` |
| 87 | TX_AUTO_BW | 39 | `0x820ed71c[31:0]` |

Source-named abort offsets53–56 translate to special IDs256–259. Their
special handling was not resolved, so **they were not queried**. No direct
hardware-counter reads or enable writes occur in the TX trials: UNI remains
the sole consuming owner. No whole cross-chip register map is assumed.

## Length reversal: reproducible duration change

Both length trials alternate65/193/65/193/65-byte frames, excluding FCS,
four per phase, at HT8/two streams/20MHz/BCC/long GI. Fresh nonces remain private.

| Phase size | Offset28 delta, first / repeat | Offset31 delta, first / repeat | Exact receipts, first / repeat |
| --- | --- | --- | --- |
| 65 | 356 / 356 | 368 / 368 | 3 / 3 |
| 193 | 656 / 656 | 672 / 672 | 4 / 4 |
| 65 | 356 / 356 | 368 / 368 | 4 / 3 |
| 193 | 655 / 655 | 671 / 671 | 4 / 4 |
| 65 | 356 / 356 | 368 / 368 | 4 / 4 |

Every phase increments20MHz count22, SU_TX_OK85 and TX_FULL_BW86 by4;
40/80/160MHz and auto-width counters stay0. All20 per-packet statuses in
each run report one transmission and no error bits.

The related [MT6655 register description](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/chips/coda/mt6655/bn0_wf_mib_top.h#L666)
describes`+0x040` as MAC-to-PHY transmit assertion time in1us units and
`+0x050` as FES airtime in1.024us units. These addresses/widths match the
independently resolved MT7925 fields, but source units remain distinguished
from endpoint calibration.

For this fixed HT8/2SS/20/BCC mode,52 data bits per symbol gives
`4 * ceil((16 + 8*(length+4) + 6)/52)` data-symbol microseconds:
48 for65 bytes and124 for193 bytes. The difference is76us per packet,
304us per four-packet phase, agreeing with offset31's observed303–304 ticks.
This supports its1us unit. It does not identify the absolute RF endpoint,
preamble/extension contribution, or explain every tick of the two counters.
In particular, do not treat offset28 raw ticks as microseconds or assume the
two duration counters cover identical intervals.

## Width reversal: counters remain active when reception fades

Both width trials keep both radios configured channel6/center8/40MHz and
alternate requested TX20/40/20/40/20, with65-byte frames throughout.
Only the already validated fixed-width descriptor changes between phases.

| Requested width | Count22 / count23 delta | Offset28, first / repeat | Offset31, first / repeat | Exact receipts, first / repeat |
| --- | --- | --- | --- | --- |
| 20 | 4 / 0 | 356 / 356 | 368 / 368 | 3 / 3 |
| 40 | 0 / 4 | 264 / 264 | 272 / 272 | 2 / 3 |
| 20 | 4 / 0 | 356 / 356 | 368 / 368 | 4 / 4 |
| 40 | 0 / 4 | 264 / 264 | 272 / 272 | 0 / 0 |
| 20 | 4 / 0 | 355 / 356 | 367 / 368 | 4 / 4 |

SU_TX_OK and TX_FULL_BW remain4 per phase, other selected counts0, and
all statuses remain count1/error0. Received wide frames independently decode
HT8/2SS/40MHz. The later failed-reception wide phase still has the same width
and duration counts as the successful early phase. This narrows the
[wide-instability investigation](PHY_TRANSMIT.md#wide-reception-also-declines-without-a-receiver-command):
the transmitter's accounting path is still advancing with wide-like duration.
It does not establish RF quality, antenna output or which radio causes the loss.

## Reproduce and scope

Run [`research/tx_airtime_probe.py`](../research/tx_airtime_probe.py) with
`--suite length` or`--suite width` and both
`--acknowledge-consuming-counters --acknowledge-experimental-transmit`.
The maximum is20 frames,100ms receive windows with256-transfer caps,50ms gaps,
synthetic broadcast addresses, zero NAV, no ACK/BA, and normal reload of both
radios in cleanup. There are no power, calibration, FCS-filter or counter-enable
writes. Tests constrain payloads, sequence/nonce bounds, width descriptors,
symbol arithmetic, exact offset selection and opt-in before USB access.

[Sanitized evidence](../research/evidence/tx-airtime-counters-2026-09-05.json)
contains the source-map readback and all four trials, including failed receipts,
firmware hashes, statuses and raw deltas. All alive/reload checks pass.
Production Python/C APIs and passive defaults are unchanged.
