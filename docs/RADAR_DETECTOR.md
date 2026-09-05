# Station radar-detector control: transport works, pulse measurement unproven

On the pinned MT7925 firmware, **UNI0x19 STOP/START/STOP returns status0** in
normal unassociated channel36/20MHz receive mode. Three post-START one-second
windows contain301 good-FCS OFDM frames and **no candidate radar events**. This
establishes command acceptance, not hardware activation or usable pulse telemetry.
No transmitted test pattern, radar emulation, threshold writes, TX queue controls,
DFS-channel transmission or calibrated detection claim is involved.

## Exact station protocol

The pinned BSD-2-Clause gen4m source defines two transports:

- MT7961 candidate: CE`0x8f` SET, eight bytes containing control, detector index,
  RX selector, set-value and four reserved bytes. STOP is eight zero bytes.
- MT7925: UNI`0x19`, SET/UNI/ACK option7, reserved4 + tag0/length12 + that
  eight-byte control. STOP is `0000000000000c000000000000000000`.
- Receiver START uses control1, index0, RX selector0, **region1 (FCC detector
  profile)**: `0000000000000c000100000100000000`. This is not a TX country/power
  change. All-zero START would select region0/CE, not a neutral default.

Sources at gen4m commit`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`:
[command structures and enums](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_cmd_event.h),
[UNI layout and events](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h),
[nicUniCmdRddOnOffCtrl bridge](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_uni_cmd_event.c),
[p2pFuncStartRdd / p2pFuncStopRdd callers](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/mgmt/p2p_func.c).
The bridge is conditional on DFS-master support in that source. These protocol
facts do not establish which detector implementation the shipped image contains.

Source event candidates are UNI EID`0x11` (tags0 pulse/1 report), or legacy
EID`0xed`/extended EID`0x3a`. The probe deliberately exports only event metadata;
no unobserved variable-length pulse structure is advertised as a working parser.
Do not confuse station CE`0x8f`, AP EXT`0x3a`, and internal dispatch-table tags.

## Live controls, 2026-09-05

`research/rdd_stop_probe.py` allows STOP only on either pinned chip.
`research/rdd_receive_probe.py --enable-passive-detector` allows the single
source-defined MT7925 START shape only after a matched successful STOP reply.
Both restore normal firmware in cleanup, including on exceptions.

| Probe | Result | Recovery |
|---|---|---|
| MT7961 CE8F, two STOPs,20ms endpoint waits | No event or decoded frame | Alive/reload pass |
| MT7925 UNI19, two STOPs,20ms waits | First ACK0; second not observed | Alive/reload pass |
| MT7925 STOP/START/STOP,20ms waits | Initial STOP ACK0; later ACKs not observed | Alive/reload pass |
| MT7925 STOP/START/STOP,1ms waits | **All three matched EID1/status0**;301 good-FCS frames after START; no pulse event | Alive/reload pass |
| MT7961 CE8F, two STOPs,1ms waits | No event or decoded frame | Alive/reload pass |

The20ms version alternated endpoints0x84/0x85 and collected about46 transfers/s
on the active endpoint. A quiet endpoint can throttle active-endpoint draining
enough to hide a later command reply. The1ms version collected77/154/70 good-FCS
frames across its post-START windows and recovered both START and final STOP
ACKs. This is evidence of a **receive-loop confound**, not evidence that the
earlier commands were refused or the firmware stopped replying. No window hit
its transfer cap (256 originally,512 after the correction). All observed frames
and replies came through endpoint0x84; none came through0x85.

The MT7961 silence remains ambiguous, especially with no normal ch36 frames in
those windows. No START was issued to that chip by these new tools. Older AP-EXT
experiments are separate and must not be counted as validation of the CE route.

[Sanitized evidence](../research/evidence/radar-detector-2026-09-05.json).
Only counts, timing, fixed command status and event shapes are retained. Raw
ambient identities, frame bodies and detector payloads are not published.

## What would turn this into a measurement?

Trace the actual UNI handler to its detector register/state changes and event
producer, then read back those specific fields around STOP/START/STOP. No random
register sweep, threshold guessing or emulated radar is needed for that next
step. Ordinary traffic and successful command ACKs are not a positive control
for radar sensitivity. Even real pulse reports would need separate validation
before being labeled radar, non-Wi-Fi interference, or a calibrated power source.
