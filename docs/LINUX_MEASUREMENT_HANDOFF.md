# A small firmware-evidence package for mt76 maintainers

Prepared2026-09-06 for possible future sharing. **No message, issue, patch or PR
has been sent upstream.** This is concrete documentation/pointers, not a claim
that this userspace instrument is generally ahead of Linux or a commitment to
implement kernel interfaces.

## Existing upstream work versus the additional evidence

The research originally used `openwrt/mt76` revision
`c5a3bd91aa735b669618610d5f0ebfa5786845a6`, pinned vendor gen4m structures at
`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`, and the firmware hashes below.
A read-only check of public mt76 HEAD on2026-09-06 returned
`be5ce7910521492d4a2e4ce7ee3843680a46c047`.

At that checked revision, the [shared command enum](https://github.com/openwrt/mt76/blob/be5ce7910521492d4a2e4ce7ee3843680a46c047/mt76_connac_mcu.h#L1295)
already names EXT5a/UNI22 MIB queries; [MT7925 temperature](https://github.com/openwrt/mt76/blob/be5ce7910521492d4a2e4ce7ee3843680a46c047/mt7925/mcu.c#L986)
already uses UNI THERMAL, and [common MAC work](https://github.com/openwrt/mt76/blob/be5ce7910521492d4a2e4ce7ee3843680a46c047/mt792x_mac.c#L9)
already updates survey/MIB state. Those mechanisms are not our invention.
The [Group5 default-disable warning](https://github.com/openwrt/mt76/blob/be5ce7910521492d4a2e4ce7ee3843680a46c047/mt792x_mac.c#L302)
is still present; our new failures do not resolve it.

A scoped text inspection of current `mt7925/mcu.c`, `mt7925/mcu.h` and
`mt7925/mac.c` found no CSI/NOISE_FLOOR symbols. This is **not** a proof of absence
from every Linux tree, vendor implementation or similarly named feature. The
useful contribution is the reproducible firmware behavior and cleanup constraints,
not an unsupported novelty claim.

| Packet | Concrete additional evidence | Why it may help |
| --- | --- | --- |
| UNI23 diagnostic retention defect | Each tag3 report removes one initially free command object; three leave thermal working, four cause the unrelated query to fail. Tag0 controls retain the pool | A narrow firmware ownership-path investigation with a non-RF control and recovery, not just a timeout anecdote |
| UNI22 field and ownership map | Firmware/ROM-resolved offset0/2 fields; direct-first reads consume counts that disappear from the next firmware delta. Corrected17/19 names and idle saturation | Helps choose one counter owner and avoid bogus occupancy/width assumptions |
| Beacon CSI prerequisites and ordering | Working new-chip narrow report, START clears allowlist; ADD transmitter must precede the final receiver-count command. Host filters remain necessary | Gives a minimal sequence, strict event dimensions and reproducible negative control |
| Firmware-timed raw histogram event | UNI36/tag2 produces two11-bin timer views after roughly512ms, exactly matching stopped banks; counts vary with conditions | Supplies a bounded one-shot path plus the important absence of proven calibration, full-dwell coverage and timer cancellation |

## 1. Diagnostic retention: the most actionable isolated defect

Use the [full defect note](MT7925_DIAGNOSTIC_STATS.md) and its
[nine-run evidence](../research/evidence/mt7925-diagnostic-command-leak-2026-09-05.json).
Request: UNI23 QUERY option3, four reserved bytes, tag3/length4. The tested
fresh state has four free objects at scalar count address`0222efc0`; successive
diagnostics yield3/2/1. This is the initially free count, not a proven total
capacity. Basic tag0 controls hold4 and an unrelated thermal query does not
replenish the retained objects. Full reload restores4.

Pointer chain: diagnostic builder`e003ba76` returns1 at`e003bb7c`; outer handler
`e003bd10` propagates it; generic dispatcher`e002f076` takes the special path at
`e002f090`, bypassing ordinary cleanup`e0028a48`. The likely defect is ownership
being retained after a synchronous reply. The exact semantic name of return1
is inferred, not a recovered enum; no patch-and-retest or allocator-wide proof.

[`mt7925_diagnostic_stats_probe.py`](../research/mt7925_diagnostic_stats_probe.py)
defaults to a bounded three-report experiment and reload. **Even three consumes
objects until reload.** Four-or-more suites require its explicit stall flag.
Do not copy this into polling, run it under another device owner, or treat empty
statistics/zero-filled sections as live measurements. No firmware bytes, pool
nodes, pointer fields, ambient frames or identifiers are distributed.

## 2. Counter mappings and competing consumers

[Mapping/ownership](MT7925_MIB.md) and [subchannel semantics](SUBCHANNEL_MEASUREMENTS.md)
separate vendor labels, firmware-resolved hardware fields and observed behavior.
Offset0 resolves to`820ed7f0[31:0]`; offset2 to`820ed9a8[31:0]`. Direct-first
passive reads repeatedly leave approximately zero for subsequent UNI deltas,
while immediate second direct reads are zero. This is a consuming-owner hazard,
not evidence for two independent streams or an existing Linux-driver defect.

UNI offsets17/18/19 are primary CCA / secondary CCA / CCA+NAV+TX per the
[pinned vendor enum](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h#L2649).
A multi-entry command is not a simultaneous latch.64-bit wire values do not
establish64-bit hardware or accumulator width. The16-bit idle-slot field can
saturate before firmware accumulation, even when returned totals exceed65,535.
Some duration units retain a1-versus1.024us ambiguity; ED is not non-Wi-Fi-only
time, and inactive-width secondary fields must not become occupancy percentages.

## 3. CSI: a small sequence and a useful negative control

The [API contract](CSI_API.md) and [ordering evidence](../research/evidence/r32-csi-session-2026-09-06.json)
give exact request/TLV shapes. On pinned MT7925 channel36/20MHz:
normal monitor/sniffer → STOP → beacon selector → START → ADD selected transmitter
→ receiver count last. Count1 before ADD yields both receiver indices in fresh
Python/C controls; ADD before count1 yields receiver0. We have not identified
the exact field reset behind that interaction.

The narrow parser accepts version22,64 signed I/Q pairs, reported OFDM6 and
unsegmented20MHz metadata. It rejects the known-stale CCK layout and unknown
versions/shapes. Sequence0 events need explicit host epoch/generation/source/index
filters and queued/late-report accounting. MCU GPT tag25 is not RXD/TSF/ToA.
Short session/overflow/cancellation gates and control-stage faults are documented;
calibration, broad bandwidth, pairing guarantees and ranging are not established.

## 4. Histogram: raw sampled distributions, not a noise-floor number

The [firmware trace](MT7925_NOISE_HISTOGRAM.md#one-shot-firmware-event-now-works)
identifies UNI36 SET/ACK option7, payload`00 00 00 00 02 00 04 00`.
It resets/enables both control indices. EID36/sequence0 contains a96-byte body,
tag2/length92 and two11-u32 arrays from`83001000`/`83011000`; they are not the
ordinary second bank at`83098600`.

[Twelve guarded Python/C runs](../research/evidence/r32-histogram-guard-2026-09-06.json)
cover repeated acquisition/restoration and active cancellation. No known host
command cancels an already armed callback: pending failure uses full reload
after worker stop, not a register restore that may race the timer. Shared history
is irreversibly reset. The old chip has a different host-timed ordinary-bank
path, still bin0-only. Neither raw view indices nor threshold labels are
calibrated antenna/dBm labels, and sampled fractions do not cover the full dwell.

## Reproducibility and sharing boundary

| Firmware profile | RAM SHA-256 |
| --- | --- |
| MT7925 A9000, USB0846:9072 | `23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120` |
| MT7961 ALFA, USB0e8d:7961 | `b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9` |

Patch hashes, dated commands, limits and cleanup outcomes accompany the linked
evidence. Pure parsers/shared synthetic fixtures need no hardware; hardware
reproducers require exclusive ownership and pinned images. No firmware binaries,
ROM instructions, private identifiers or IQ captures are included in the gift.
The current old reference unit has an [unresolved RF-silent baseline](TESTING.md#r32-current-mt7921-rf-failure-and-soak-status-2026-09-06);
that limits fresh old-chip RF claims and is not hidden by historical successes.

If shared later, a maintainer can take any one packet independently. No kernel
implementation, interface choice, upstream acceptance or external coordination is
required to retain the value of these concrete findings.
