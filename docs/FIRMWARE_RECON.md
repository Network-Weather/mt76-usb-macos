# Firmware and PHY reconnaissance: energy-domain instruments

Status: spikes, unproven. Fresh as of 2026-09-03.

## Why

Everything this driver measures today comes from frames it successfully demodulated. That
biases every result toward the part of the radio environment that is healthy enough to
decode. A channel can be unusable for reasons a sniffer cannot see: a microwave oven, a
non-Wi-Fi FHSS device, an AP so far away its beacons never resolve, a hidden node whose
collisions register only as lost airtime. "I heard 4 frames here" and "this channel is
quiet" are different claims, and the driver currently cannot tell them apart.

The chip can. The MT7921 hardware maintains energy-domain counters that are independent of
demodulation, and the firmware implements more of them than the Linux driver exposes:

- `mt792x_regs.h` defines CCA busy, TX airtime, RX airtime, and OBSS airtime counters, and
  `mt792x_mac.c:226 mt792x_phy_update_channel()` reads all four for `cfg80211` survey dump.
  Every one is a flat register read that our USB `rr()` can already issue.
- `mt792x_mac.c:216 mt792x_phy_get_nf()` is `return 0;` — upstream mt7921 reports **no**
  noise floor. The sibling AP driver derives one at `mt7915/mac.c:1200` from an 11-bin
  Idle Power Indicator histogram in the PHY block, which mt7921 never touches.
- The MT7921 firmware ships with debug strings intact and contains `rdmGetIpiHist`,
  `rdmSetIpiHist`, `EdccaDetectIpiEnable`, `IpiDutyCycle`, per-band/per-bandwidth EDCCA
  thresholds, RDD radar-pulse control, and `Wifi-spectrum is enable`.

Upstream leaves these unexposed because a station driver has no use for them. A measurement
instrument does.

## What the images are made of

Measured 2026-09-03 by `scripts/fw_triage.py`. A firmware image is not one thing: it is
several regions with separate load addresses, and they differ from each other far more than
the two chips' images differ. The whole-file numbers that opened this investigation
(6.03 bits/byte for the MT7921, 7.96 for the MT7925) turned out to be averages hiding the
structure, and the structure is the useful part.

Encryption is not inferred from entropy. Each RAM region declares it in `feature_set` bit 0,
`FW_FEATURE_SET_ENCRYPT` (mt76 `mt76_connac_mcu.h:9`), which the loader reads to pick a
download mode. Patch sections declare the same fact in the top byte of `sec_key_idx`, via
`PATCH_SEC_ENC_TYPE_MASK` (`mt76_connac_mcu.h:31`).

| | region | load | size | entropy | declared | kind |
|---|---|---|---|---|---|---|
| MT7921 | patch s0 | `0x00900000` | 92 KB | 6.506 | PLAIN | code |
| | RAM r0 | `0x00915000` | 364 KB | 6.874 | OVERRIDE_ADDR | code |
| | RAM r1 | `0x02015c00` | 272 KB | 2.548 | — | **text** |
| | RAM r2 | `0x00404400` | 15 KB | 3.953 | — | table |
| | RAM r3 | `0xe0270000` | 52 KB | 6.799 | — | code |
| | RAM r4 | `0x00000000` | 88 KB | 7.951 | NON_DL | not downloaded |
| MT7925 | patch s0/s1 | `0x00900000`, `0xe0002800` | 39 / 148 KB | ~8.0 | **AES** | encrypted |
| | RAM r0–r3 | `0x0090d000` … | 77–595 KB | ~8.0 | **ENCRYPT** | encrypted |
| | RAM r4 | `0x00000000` | 297 KB | 7.465 | NON_DL | not downloaded |

Consequences that shape everything downstream:

- **Nothing in the MT7921 image is encrypted.** Not the patch, not any RAM region. The
  strings survive because the vendor left them in, not because anything was defeated.
- **Every executable region of the MT7925 image is AES-encrypted by declaration.** Its ~2600
  apparent "strings" are coincidental ASCII runs in ciphertext. A symbol's absence there is
  not evidence the firmware lacks the feature, and no amount of reading changes that.
- **All the text lives in one region.** MT7921 RAM r1 holds 1457 strings at 5.35 per KB
  against 0.62 in the code regions, including every IPI, EDCCA, RDD and MIB string found so
  far. Code is r0 and r3; r1 is what the code points at.
- Both images end with a `NON_DL` region at load address 0 that is never sent to the chip.
  It is packed, and it is not firmware in any executable sense.

So the string-reading route works on the MT7921 and cannot work on the MT7925. Any result
recovered by reading MT7921 firmware has to be re-established on the MT7925 some other way,
or scoped to the MT7921 alone.

Roadmap context: [ROADMAP.md](../ROADMAP.md). Chip-generic results land in
[TESTING.md](TESTING.md); disproven ideas land in [NEGATIVE_RESULTS.md](../NEGATIVE_RESULTS.md).

## What the MT7921 image says about itself

The image carries its own `__FILE__` paths: 60 source files from MediaTek's build tree,
which map the firmware's modules far better than symbol names do. The IPI, RDD and EDCCA
strings come from `wifi/core/wificore/rlm/rdm_phy.c`, alongside `rlm_phy.c`, `cnm_radio.c`,
and a `hal_cal_flow.c` reached through a build path naming the project
`wifi_mobile_ram_ccn16`.

**The instruction set of the code regions is unidentified.** Signature sweeps for ARM Thumb,
ARM A32, MIPS, RISC-V, Xtensa, ARC and NDS32 across regions r0, r3 and the patch section all
returned densities at or *below* what uniform-random bytes would produce -- ARM Thumb
`push {…,lr}` appears 0.49 times per KB in r0 where chance alone predicts about 2. The
regions are not encrypted (the header says so, and the string region beside them is plainly
readable), so they are plaintext code in an ISA not yet named. Identifying it is a
prerequisite for any disassembly and is not currently blocking anything else.

Direct string cross-referencing also failed: of 874 words in r1 pointing inside r1's own
declared address range, only 8 land on a string start. The logging format
(`%06d& SCHEING Hit& %s,L%d,…`) suggests an indexed logging scheme rather than pointer-based
format strings, so recovering call sites will not be as simple as following pointers.

## The better lead: these are named MCU commands

Disassembly turned out not to be the shortest path. mt76 already names the command
interface, and the MT7921 firmware answers to it:

- `MCU_EXT_CMD_GET_MIB_INFO = 0x5a` (`mt76_connac_mcu.h:1292`) takes an array of
  `{band, offs}` pairs and returns 64-bit counters. The offsets are an enum in
  `mt7915/mcu.h:186`, and it includes **`MIB_NON_WIFI_TIME`** -- time the medium was busy
  with energy that is not Wi-Fi at all. That is the interference measurement this whole
  investigation was reaching for, already exposed through a command our driver can frame.
- `MCU_EXT_CMD_PHY_STAT_INFO = 0xad` (`mt76_connac_mcu.h:1309`) takes a one-byte `category`
  from the `MCU_PHY_STATE_*` enum (`mt76_connac_mcu.h:1199`), of which only five values are
  named upstream. Whether the firmware answers more categories is a question a probe can
  settle.
- The firmware's own strings corroborate that both are enumerable rather than fixed:
  `CmdMibInfo,event packet alloc fail.` and `%s: MIB counter index = %d not supported.` --
  the second is an out-of-range reply, which means unsupported indices are *refused* rather
  than answered with garbage.

This is a bounded, read-only, passive probe over an interface the driver already speaks, and
it does not require knowing the MCU's instruction set. It supersedes Spike B as the cheapest
route to a noise/interference figure; Spike B remains the fallback if the firmware refuses
every interesting index.

## Where the work happens

Worktree `~/dev/mt76-usb-macos-firmware-recon`, branch `spike/firmware-recon`, tracking PR
on `Network-Weather/mt76-usb-macos`. These are spikes: they answer questions and stay in
the repo as reproducible diagnostics. Nothing here changes the capture path, and no result
is promoted to a documented capability without a dated hardware entry in TESTING.md.

## The three spikes

Ordered by confidence, cheapest first. Each is independently useful; B and C do not depend
on each other.

### Spike A — channel occupancy from MIB counters (`scripts/mib_survey.py`)

Confidence: high. Every register is defined in mt7921's own header and is inside the
address space the chip already exposes.

Read, per dwell: `MT_MIB_SDR9` bits 23:0 (CCA busy µs), `MT_MIB_SDR36` (TX airtime µs),
`MT_MIB_SDR37` (RX airtime µs), `MT_WF_RMAC_MIB_AIRTIME14` (OBSS airtime µs), after arming
`MT_MIB_SCR1` TXDUR_EN|RXDUR_EN and clearing via `MT_WF_RMAC_MIB_TIME0`/`AIRTIME0` bit 31.

**What must be true to call this working:**

1. The four registers read back plausible values — not all-zero, not all-`0xffffffff`.
2. Busy time is monotonically non-decreasing across reads within one dwell, and the
   clear-on-read reset returns it toward zero.
3. Busy µs never exceeds wall-clock dwell µs by more than the counter's own resolution.
4. Ordering holds: a channel with a known-busy neighbour reports higher busy fraction than
   an empty channel in the same band, in the same run.
5. Busy time is greater than airtime attributable to decoded frames on a channel where the
   driver decodes little — i.e. the counter sees something the sniffer does not. This is the
   whole point; if it fails, Spike A measures nothing new.

### Spike B — IPI/IRPI histogram, a real noise floor (`scripts/ipi_probe.py`)

Confidence: unknown, and now the fallback rather than the main route -- Spike D reaches a
comparable measurement through a documented command interface. Keep it for the case where
the firmware refuses the interesting MIB indices.

`MT_WF_IRPI_BASE` is `0x83000000` and `MT_WF_PHY_BASE` is `0x83080000` on mt7915. No
`0x83xxxxxx` region appears anywhere in mt7921's headers or its PCI `fixed_map`, so we do
not know whether the mt7921 PHY lives there, lives elsewhere, or is unreachable from the
USB register window. The probe is read-only and reports what it finds without asserting a
mapping.

**What must be true:** reads in the region return varied, non-constant data (a region that
is entirely `0x00000000` or `0xffffffff` is unmapped, not a histogram); and 11 consecutive
words behave like bin counts — non-negative, growing while receiving, resettable. Only then
is applying mt7915's `nf_power[]` table meaningful.

**Explicitly out of scope:** writing to any `0x83xxxxxx` address until reads have
established what is there. The probe does not enable `IPI_EN` on a register block it has
not identified.

### Spike C — firmware image triage (`scripts/fw_triage.py`)

Offline; no adapter, no network. Parses the connac trailer, maps entropy by section,
extracts strings, and classifies each blob as readable or opaque. Establishes what is worth
disassembling before anyone spends time disassembling it.

**What must be true:** the trailer parse agrees with the file's own build-date string; the
readable/opaque classification is reproducible across the four pinned blobs; the RF-relevant
symbol inventory is regenerable rather than hand-copied.

Done, 2026-09-03. Findings are in the two sections above. The disassembly follow-on it was
meant to scope is **not** the next step: the MCU command interface below reaches the same
measurements without needing the ISA.

### Spike D — MIB and PHY stats over the MCU (`scripts/mcu_stats.py`)

Confidence: high for `GET_MIB_INFO`, unknown for the unnamed `PHY_STAT_INFO` categories.

Queries `MCU_EXT_CMD_GET_MIB_INFO` for both published offset schemes at once — mt7915's
81/82/86/87/88 and mt7916's 6/8/490/491 — reading every offset twice around a dwell, because
a counter that does not move is not a live measurement. `--sweep LO:HI` widens the search
when neither published scheme answers. `MCU_EXT_CMD_PHY_STAT_INFO` categories are then swept
past the five named upstream, to see whether the firmware answers any others.

Two details that decide whether the output means anything:

- **The reply preamble length is unknown.** mt7915 skips 20 bytes before the counter array
  and mt7916 skips none (`mt7915/mcu.c:3241`); MT7921's is published nowhere. So the parser
  searches the reply for each echoed `{band, offs}` pair and reads the counter beside it,
  which works whatever the preamble turns out to be and fails visibly rather than
  misaligning by 20 bytes and reporting plausible nonsense.
- **A refusal is a real answer.** The firmware carries
  `%s: MIB counter index = %d not supported.`, so an out-of-range index is rejected rather
  than answered with zeros. An offset that is not echoed back is reported as `not_echoed`
  rather than as a zero counter.

**What must be true:** the firmware answers the command at all on an MT7921U; supported
indices return counters that grow with dwell time while unsupported ones are refused rather
than answered with zeros (the `MIB counter index = %d not supported` string says refusal is
implemented, but that it is *reachable* is the thing to confirm); and a non-Wi-Fi time
counter reads higher near a known non-Wi-Fi emitter than on a quiet channel.

**Out of scope:** any command that sets rather than gets. This sweep reads.

## Scope boundaries

- Nothing here transmits. Spike A and B are register reads; C touches no hardware.
- No survey orchestration, no place or room naming, no verdict rules. This repo is the
  instrument. Evidence stays chip-generic.
- No new documented capability without dated hardware evidence in TESTING.md, per the
  ROADMAP decision rules.
- MT7925 support for A and B is untested and unclaimed; its register map differs and its
  firmware is opaque.
