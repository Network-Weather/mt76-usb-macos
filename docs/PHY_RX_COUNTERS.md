# MT7961 PHY detection and decoding counters

**Ten PHY counters are reachable through CE1 GET41, and their normal monitor-mode
accumulation can now be enabled with the exact firmware control.** Controlled HT and HE
receptions produce nonzero detection/receive-ready counts; a busier window also
produced PHY-header and FCS errors. These complement MAC delivery counts and the
finite RX-vector log. They do not by themselves classify non-Wi-Fi interference,
attribute errors to a transmitter, or measure calibrated RF power.

The adjacent [CN/EVM diagnostic register](PHY_SIGNAL_FIELDS.md) is a separate
latched raw signal surface, not another cumulative counter.

Pinned RAM SHA-256:
`b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`.

## Firmware and wire mapping

`<B3xII>(2, 41, byte_offset)` through CE1 returns an EID9 scalar pair
`<II>(41, value)`. Only that pair is defined here; reply tail bytes are discarded.
Use exactly offsets0,4,...,36. The firmware accepts byte offsets up to36 but
does not enforce alignment; the tool does, and never probes unaligned/out-of-range
locations. GET offset0 refreshes all ten counters; the other nine read that
stored snapshot. This is not a guarantee of an atomic five-register hardware
snapshot, or protection against another firmware consumer refreshing it.

- GET dispatch `0x0093363c..0x00933640` reaches`0x00933922`.
- `0x0093392a..0x0093393c` refreshes only for offset0, through`0x00942d0e`.
- `0x00933946..0x00933954` reads per-band state+`0x34+offset`.
- The actual refresh routine`0x00936cc8..0x00936d10` reads five registers and
  splits each into two **unsigned16-bit values**, stored in32-bit slots.
  Band0 uses base`0x83081000`; band1 uses`0x83091000` (only band0 tested).

| Band0 register | Low16: GET byte offset / name | High16: GET byte offset / name |
|---|---|---|
| `0x83081010` | 0 / CCK PD | 4 / OFDM PD |
| `0x8308101c` | 8 / CCK SFD error | 12 / CCK SIG error |
| `0x83081020` | 16 / OFDM TAG error | 20 / OFDM SIG error |
| `0x83081024` | 24 / CCK FCS error | 28 / OFDM FCS error |
| `0x83081014` | 32 / CCK MDRDY | 36 / OFDM MDRDY |

Names are cross-checked against the **72-word** CE0xc8 output assignments at
`0x009312e8..0x0093135c` and`0x009313c2..0x009313e0`, plus pinned Motorola gen4m
`os/linux/include/gl_qa_agent.h:PARAM_RX_STAT`. That structure uses a different
order: e.g. CCK SIG precedes SFD, and OFDM SIG precedes TAG. The table above
follows actual GET41/register order, not a guessed copy of the public structure.
PD and MDRDY are detection and receive-ready counter names, not exact-frame
counts. CCK interpretation was not validated by transmitting CCK in this test.

The firmware's human-readable PHY diagnostic calls `0x00942d0e` into a40-byte
buffer and computes **FalseCca = PD - MDRDY** separately for CCK and OFDM:
`0x0096261c..0x00962624` uses buffer offsets0/32, and
`0x00962660..0x00962668` uses4/36. Thus that label is derived arithmetic over
these same counters, not a separate detector or proof of non-Wi-Fi interference.
The printer uses a signed decimal format; snapshot/reset/wrap effects still
apply. No new SCS command or threshold write was inferred from the label.

## Live results and counter semantics

`research/phy_stats_probe.py` makes bounded passive normal/RF-RX/stopped queries.
Its first passive control returned McuError in normal mode, matched all-zero
snapshots in RF mode, and no host packets in its short receive windows. That
alone did not establish inactive counters.

`research/rxv_log_probe.py --acknowledge-experimental-transmit --phy-counters`
then received4/4 exact normal HT controls, sent four RF stimuli and retrieved
four logged vectors. PHY fields changed from all-zero to **OFDM PD5/MDRDY4**,
with all error counters zero. Thus the counter route is live under independently
checked reception conditions, not merely an accepted command.

A second run added `--rearm-he --phy-registers`:4/4 HT and4/4 HE exact controls,
then four HT and four HE stimuli in reset-separated batches (16 total frames).
Its busier first RF window changed OFDM PD/MDRDY74→101, FCS errors33→42,
and SIG errors0→1. These include ambient activity and are not assigned to the
four synthetic HT frames. After STOP, **two complete queries, a direct five-
register read, and another complete query all agreed exactly**. No clearing on
read was observed in that stopped sequence. SET91 reset then returned all-zero
PHY fields; the subsequent HE batch gave **PD4/MDRDY4**, with errors zero,
and another repeated stopped query agreed.

Treat these as16-bit snapshots: wrap versus saturation at the limit, periodic
firmware resets, inter-consumer effects and long-running accumulation still need
validation. Do not infer packet-loss rate as `PD-MDRDY`, or non-Wi-Fi activity
from any one of these counters. All experiments restored normal firmware on both
radios and passed alive checks. No direct register writes or raw frame export.

The normal-mode wire query refusal does not establish that direct register
access is unavailable. `--phy-registers` explicitly opts into the separate fixed-
register comparison; its read effects are recorded rather than hidden inside
the standard counter-query path. In a third controlled run, normal monitor-mode
reads before and after4/4 exact HT receipts stayed at PD0/MDRDY0 and FCS errors2.
After entering RF RX, the same physical registers and GET41 agreed at PD7/MDRDY7,
FCS errors1, across repeated reads. **Unmodified normal-mode accumulation failed**;
the physical addresses alone are not a working always-on survey API. The next
discrimination is the firmware's counter enable/reset sequence, not another
uncontrolled idle observation.

## Normal monitor-mode enable/freeze control

The initial normal-mode negative was an enable-state issue, not an inaccessible
counter bank. The reset call chain is now fully traced:
`SET91 → 0x009311c2 → 0x00964cba → 0x00943ed0 → 0x00968b1e` for band0.
`0x00968b1e..0x00968b3a` changes only bits11:9 of **`0x83082004`**:
argument0 clears mask`0xe00`; argument1 replaces it with`0xa00`.
The band1 sibling at`0x00968b3c` uses`0x83092004`, not tested here.
The band0 operation independently agrees with `mt7915_mac_cca_stats_reset` and
`MT_WF_PHY_RX_CTRL1_STSCNT_EN` in mt76 pin
`c5a3bd91aa735b669618610d5f0ebfa5786845a6`. We do not assume sibling register
maps generally transfer; the MT7961 firmware trace establishes this one.

`research/normal_phy_counter_probe.py --acknowledge-experimental-transmit
--enable-counters` uses **normal monitor mode only**. It brackets the exact
clear→enable sequence with baseline and restored-mask phases, four synthetic
HT/MCS8/NSS2 frames per phase,12 submissions maximum. Each phase has a one-second/
512-transfer receive ceiling. All writes preserve bits outside`0xe00`; the
original masked bits are restored before both radios are normally reloaded.
This resets statistics and requires exclusive ownership, not concurrent use
alongside another statistics collector.

In the first live run the original bits were0. All three phases independently
received **4/4 exact frames**. Baseline PD/MDRDY stayed0/0; enable read back
`0xa00`, reset the fields, then PD/MDRDY reached7/7. Restoring the original0
froze PD/MDRDY at7/7 despite four further exact receptions. Thus ordinary packet
delivery continues while counter accumulation is enabled or frozen. The seven
counts include ambient activity and are not seven synthetic deliveries.
Original-bit restoration and both-radio reload/alive checks passed.
A second fresh-boot run independently reproduced the same0→7→7 pattern, with
4/4 exact HT receipts in each phase and successful restoration/cleanup.
[Sanitized normal-mode evidence](../research/evidence/normal-phy-counters-2026-09-05.json).

This establishes a useful normal-survey primitive. It does not yet establish
long-run overflow behavior, multi-band operation, an error classifier, or absence
of interaction with other CCA/statistics consumers. The earlier normal-mode
negative remains above as the control that led to this enable sequence.

Public-source pin: Motorola gen4m
`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`, `include/rftest.h` and
`os/linux/include/gl_qa_agent.h`. Protocol names only; no vendor implementation
or firmware bytes copied. See also [RX-vector findings](RX_VECTOR_LOG.md) and
[sanitized evidence](../research/evidence/phy-rx-counters-2026-09-05.json).
