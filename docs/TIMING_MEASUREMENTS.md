# Timing and arrival-measurement firmware surfaces

The normal receiver timestamps already support relative clock alignment; see
[radio observability](RADIO_OBSERVABILITY.md). They are not RF ranging. This
investigation asks whether a separate time-of-arrival (ToA) / timing-measurement
engine is accessible without a full networking driver.

A separate [TX-status timing investigation](TX_STATUS_TIMING.md) now finds live
timestamp/front-time/delay telemetry with rate and payload-length controls.
It does not depend on the refused RTT interface or establish ToA/ranging.

## RTT capability query: explicit negative on both builds

The pinned gen4m source defines CE`0x44` QUERY with an empty payload.
`wlanoidGetRttCapabilities` sends zero command-body bytes. Its MT7925 bridge
`nicUniCmdRttGetCapabilities` constructs UNI`0x5d`, reserved4 bytes plus tag0,
length4: `0000000000000400`. QUERY_ACK option3 is required on MT7925; the
older chip uses an explicit CE command-word QUERY bit, not its UNI helper.

`research/rtt_capability_probe.py --chip mt7961` / `--chip mt7925` performs two
one-second,512-transfer-ceiling, dual-endpoint collections and full reload.
It sends no ranging request, peer address, TMR calibration, RF-mode change,
or host-generated frame. Potential capability replies are shape-checked;
no successfully validated capability-reply layout is claimed from this run.

| Firmware interface | First / second outcome | Cleanup |
|---|---|---|
| MT7961 CE44 QUERY | Matched EIDfd command-not-found, twice | Alive/reload pass |
| MT7925 UNI5d/tag0 QUERY_ACK3 | Matched EID1 status`0xc00000bb`, twice | Alive/reload pass |

MT7925 also receives56/60 good-FCS OFDM frames during those windows. Neither
trial hits the receive ceiling. This is an explicit command-interface negative,
not missing replies, and not proof that the chip lacks timing hardware.

## LOCATION advertises a newer-chip ToA engine

A separate normal NIC capability query returns tag`0x0c` with four bytes on
both radios. Source `CAP_LOCATION_CAP` names byte0 `ucTOAE`, with1 meaning
supported and0 unsupported. Both reserved tails are zero:

- MT7961: ToA-engine advertised value **0**.
- MT7925: ToA-engine advertised value **1**.

Both reload/alive checks pass. The reproducible probe now includes this scalar
check and deliberately discards all other NIC tags, including MAC addresses.
**Advertisement is not a working engine or sample stream.** In particular, the
newer chip's advertised1 coexists with its RTT capability command's refusal.

## Lower-level leads and boundaries

The public RF-test enum names SET116..119 as TMR role/module/DBM/iteration.
On the pinned MT7961 firmware, SET dispatcher`0x00931b2c` compares the low-byte
selector. For116..119, the branch at`0x00931cfc` takes`0x00931d54`, passes no
matching case, and reaches the common return`0x00933110` through EX9 index10.
Thus these named setters do not select a dedicated TMR case on this build;
**no live SET116..119 command was sent**. This says nothing about arbitrary
high selector bits or newer-chip behavior, which are not tested.

EXT`0x2d` TMR_CAL and event IDs`0x2e`/`0x51` also occur in the vendor headers.
No calibration command is issued: IDs alone do not establish a safe payload or
an accessible measurement path. A local unanchored CID2d candidate at file
address`0x02022e3c` points to`0x009175b4`, shared by several adjacent IDs; it is
not identified as the EXT TMR handler and is not used to construct a command.

NAN's FTM path supplies a peer address and depends on ranging/scheduling state.
It is not treated as a standalone sensor query. The most useful remaining lead
is the MT7925's ToA-engine producer/control path, with explicit stream freshness
and clock/units validation required before any topology or distance claim.

### Additional public-source pointers, not activated interfaces

The same pinned tree's `include/nic/nic_rx.h` retains20-byte TMRI/TMRR report
structures with32-bit ToA/ToD, validity/status bits, and (for TMRR) a transmitter
address. Their legacy packet header does not match a normal Connac3 RXD, so they
are not applied to arbitrary USB records. No such report has been validated.

`nic_connac3x_tx.h` names management type1 as timing measurement in TXD DW1
bits24:21. However the inspected `nic/nic_txd_v3.c` management constructor
(lines436–442) selects the normal type; an enum alone is not a demonstrated
timing-engine enable recipe. A subsequent bounded descriptor-only control is
described below; it does not exercise a full timing protocol.

The compile-conditional802.11v path in `mgmt/wnm.c` requires an in-use station
record and trigger, builds a directed action frame and follows up after TX-done.
Its `wnmReportTimingMeas` uses a conversion named`MICRO_TO_10NANO`; numerical
unit conversion is not evidence of10ns hardware resolution. The corresponding
`nic/nic_tx.c` block uses older reserved-field names. This remains source lineage,
not a verified API for the pinned station firmware or a distance measurement.
No peer action, calibration command or new register write was sent for this audit.

### Descriptor timing-type control: ordinary TX works, no extra report

The `phy_tx_probe --suite timing-type` follow-up changes **only DW1 bit21**
for the middle phase: normal0 / timing-measurement1 / normal0. Each phase
sends four synthetic broadcast no-ACK Probe Requests at HT8/20MHz on channel6,
50ms apart. The PHY, frame format, power, fixed-rate table and TX-status format
stay constant. This deliberately tests the descriptor bit alone, **not** an
802.11v/FTM action exchange, associated peer or enabled ToA engine.

Both fresh runs receive **4/4/4 exact good-FCS frames**, still decoded as
HT8/NSS2/20MHz/GI0/BCC. All12 TX statuses per run are format0, single attempt,
error-free, raw power36. The timing-marked packets transmit unchanged.

With `--both-endpoints`, input84 and85 are alternated using1ms timeouts.
Across both runs the MT7925 sees only ordinary type2 frames and its12 type0
TX statuses per run; the MT7961 sees only type2 frames. Neither run receives
an extra packet type or a transfer on85. This is a negative for **this
descriptor-only, unassociated, no-ACK setup**, not proof that timing hardware
or an enabled producer cannot report. Both alive checks and transmitter
reloads pass. Packet-type/declared-size counts contain no ambient payloads
or identifiers; own timing fields remain behind the timing opt-in.

```sh
python research/phy_tx_probe.py --suite timing-type --transmitter mt7925 \
  --channel 6 --per-phase 4 --tx-timing --both-endpoints \
  --acknowledge-experimental-transmit
```

The nearby TXD6 timestamp-offset enable/index fields remain **untested**:
the inspected source names the bits but supplies no exercised caller or offset
units. No timestamp-insertion guesses, peer actions or calibration writes were
used. [Sanitized descriptor controls](../research/evidence/timing-management-2026-09-05.json).

## Evidence and source provenance

[Sanitized query/location evidence](../research/evidence/timing-capabilities-2026-09-05.json).
Firmware is pinned in [NOTICE](../NOTICE.md). Vendor source at commit
`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`:

- [CE IDs and RTT events](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/wsys_cmd_handler_fw.h).
- [Legacy query caller](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/common/wlan_oid.c).
- [UNI bridge and event translation](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_uni_cmd_event.c).
- [UNI RTT layouts](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h).
- [LOCATION and TMR enums](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_cmd_event.h).
- [RF-test setters](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/rftest.h).
- [Legacy timing report layouts](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic/nic_rx.h).
- [Connac3 descriptor constructor](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_txd_v3.c).
- [802.11v timing workflow](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/mgmt/wnm.c).
