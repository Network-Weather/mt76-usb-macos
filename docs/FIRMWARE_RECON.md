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

**The code regions are Tensilica Xtensa LX**, 32-bit little-endian, with Code Density, the
Windowed ABI, and vendor TIE extensions. Verified here by decoding the entry point: region 0
begins `46 00 09`, which as a little-endian 24-bit word is `0x090046` -- `op0 = 6`, `n = 0`,
`imm18 = 9217`, so `j PC + 4 + 9217` = `j 0x00917405`, an ordinary unconditional jump.

A first signature sweep wrongly concluded no ISA matched, because it scanned on 2-byte
alignment. Xtensa instructions are 2 or 3 bytes and **byte**-aligned, so an aligned scan
cannot see them; the density figures it produced were meaningless for every candidate.

Direct string cross-referencing does not work: of 874 words in r1 pointing inside r1's own
declared address range, only 8 land on a string start. Recovering call sites will not be as
simple as following pointers.

Disassembly proper is not attempted here. Roughly a quarter of instructions use undocumented
MediaTek TIE encodings that stock Ghidra, Capstone and LLVM mis-decode, so it needs the
vendor-specific processor definition described in
[RELATED_WORK.md](../RELATED_WORK.md#mediatek-connac2-re).

## What the dispatch tables say, without disassembling anything

Command dispatch tables are plain data in the rodata region, so which commands a firmware
implements can be read straight out of the image. A slot is `{u32 handler, u32 cid}`, and
`scripts/fw_triage.py --command-map` scans every region for that shape at 4-byte alignment,
accepting a slot only when the handler points into an address range the image itself declares
as code.

The evidence is asymmetric and the asymmetry decides how to read the output. A hit is weak:
a code-shaped address can sit beside a small integer by chance, and `CHANNEL_SWITCH` -- a
command this driver uses successfully on hardware -- produces nine. Zero hits across every
region is the stronger claim.

Measured on the MT7921 image, 2026-09-03:

- **`GET_MIB_INFO` (0x5a) is implemented**, one slot, handler `0xe02767c0` in region 3's
  IRAM. Spike D's primary command exists in this firmware.
- **`PHY_STAT_INFO` (0xad) has no slot in any region.** Also absent: `SET_RADAR_TH` (0x7c)
  and `SET_FEATURE_CTRL` (0x38).
- `SET_RDD_CTRL` (0x3a), `SET_RDD_TH` (0x9d) and `SET_RDD_PATTERN` (0x7d) are all present,
  so radar-pulse detection is implemented even though no mt7921 driver drives it.
- `RX_AIRTIME_CTRL` (0x4a) is present, which is how per-station airtime accounting is armed
  on the AP parts. Not yet investigated.

The MT7925 image's regions are encrypted, so none of this can be repeated there.

Cross-checks against the independent analysis cited in RELATED_WORK.md, both read from the
image here rather than taken on trust: the region map agrees byte-for-byte on every offset,
load address and size; the module descriptor at `0x02022cbc` reads `0x00916478`; the stride-8
EXT table at `0x02022ce0` has cid `0x01` handled at `0x0091837e`; and UNI cid `0x23`
(`GET_STAT_INFO`) dispatches to the shared TLV handler `0x009182ae`. The large-cid stride-16
table at `0x02018c98` that carries `GET_MIB_INFO` is not described there.

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

### Spike B — IPI/IRPI histogram, a real noise floor (`research/ipi_probe.py`)

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

The dispatch-table scan above already settles half of this offline: `GET_MIB_INFO` is
implemented and `PHY_STAT_INFO` is not, so the PHY category sweep is expected to be refused
and its refusal is not a bug. It is kept because a refusal measured on hardware is worth more
than an absence inferred from a table, and because it costs one command per category.

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

## Hardware results, 2026-09-03

Reference MT7921U (ALFA AWUS036AXML, `0e8d:7961`), pinned firmware, passive throughout.
Full detail and the "not ruled out" lists are in
[NEGATIVE_RESULTS.md](../NEGATIVE_RESULTS.md); the short version:

| | predicted | measured |
|---|---|---|
| `PHY_STAT_INFO` (0xad) | not implemented (no dispatch slot) | **confirmed** — refused, all 16 categories |
| `GET_MIB_INFO` (0x5a) | implemented (slot at `0xe02767c0`) | **confirmed dispatched**, but returns a zeroed echo |
| `RX_AIRTIME_CTRL` (0x4a) | implemented (has a slot) | **wrong** — refused outright |
| MIB duration counters (registers) | should read occupancy | **all zero**, on every channel |
| MIB counters over the MCU | mt7915/mt7916 offsets | **wrong offsets** — this chip has its own 19, and they are live |

The offline dispatch-table prediction held for `PHY_STAT_INFO`. Nothing else worked, and the
two failures turn out to be the same failure.

**The MIB block is alive and arming is not the problem.** `MT_MIB_SCR1` reads `0x00f8c311`
before any write, so `TXDUR_EN | RXDUR_EN` are already set at bring-up, and `MT_MIB_SDR3`
(FCS errors) moves freely between reads. The block is mapped, readable and counting; only the
duration counters stand still. A counter that is not running reads zero through the MCU
exactly as it does through the registers, which is why `GET_MIB_INFO` returns zeros too.

### The refusal reply, and what it settles

Sending `MCU_EXT_CMD_RX_AIRTIME_CTRL` (0x4a) — the command `mt7915_mcu_init_rx_airtime()`
uses to arm airtime accounting, and which no mt7921 driver sends — returned
`4a000000 fe000000`. Sixteen bytes: the echoed ext_cid, then `0xfe`.

That turned out to be the more valuable result, because it is the firmware's
**unsupported-command reply**, and it is calibrated in both directions:

| command | reply | |
|---|---|---|
| `THERMAL_CTRL` (0x2c) | 1128 B, temperature 32 °C | implemented |
| `EFUSE_ACCESS` (0x01) | 32 B, `valid=1` | implemented |
| `SET_RADAR_TH` (0x7c) — no dispatch slot | `7c000000fe000000` | refused |
| `SET_FEATURE_CTRL` (0x38) — no dispatch slot | `38000000fe000000` | refused |
| `PHY_STAT_INFO` (0xad) — no dispatch slot | `ad000000fe000000` | refused |
| `RX_AIRTIME_CTRL` (0x4a) — **has** a slot | `4a000000fe000000` | **refused** |
| `GET_MIB_INFO` (0x5a) — has a slot | 40 B zeroed echo, *not* the refusal | dispatched |

Two things follow, one of which corrects an earlier claim here.

**A dispatch slot does not mean a command is implemented.** `RX_AIRTIME_CTRL` has exactly one
slot — the same evidence strength as `GET_MIB_INFO` — and is refused at dispatch, before any
handler runs. The command map narrows candidates; only the hardware settles them.
`scripts/mcu_stats.py` now recognises the refusal, so this is asked rather than inferred.

**`GET_MIB_INFO` is genuinely dispatched**, since it alone does not produce the refusal. Its
handler runs and returns zeros. So the counters are dead behind a live handler, and the
airtime-enable theory above is dead with it: the command that would arm them does not exist
on this chip.

### The counters are there, under their own numbering

Sweeping every offset from 0 to 127 settled it. **Exactly 19 are accepted** — 0-12, 14, 17
and 20-23 — and every other offset returns no reply at all. None of the published values
(81/82/86/87/88 for mt7915, 490/491 for mt7916) is in that set, which is why the first
hardware run read nothing: it asked for offsets this chip does not have.

The reply shape is also its own. Instead of filling the entry's `data` field, the firmware
returns 24 bytes of header plus a zeroed copy of the request, with the counter as a 32-bit
word at **byte 28**.

Reading the accepted offsets twice around a dwell, on four channels, alongside the decoder's
own frame count and summed airtime (6 s per channel, 2026-09-03):

| channel | frames decoded | decoded airtime | offs 2 | offs 11 | offs 14 |
|---|---:|---:|---:|---:|---:|
| 5 GHz 36 | 602 | 132,658 µs | **604** | 124,864 | 136,007 |
| 5 GHz 149 | 28 | 992 µs | **28** | 5,374 | 47,432 |
| 2.4 GHz 6 | 209 | 485,615 µs | **209** | 573,949 | 575,313 |
| 5 GHz 100 | 129 | 62,267 µs | **130** | 64,750 | 64,750 |

- **`offs 2` is an RX frame counter**, matching the decoder to within one frame on all four
  channels.
- **`offs 11` and `offs 14` are microsecond airtime counters**, and on every channel they are
  **greater than or equal to the airtime of the frames that were decoded**. That gap is the
  thing this whole effort was after: on 2.4 GHz channel 6, 88 ms of occupancy per 6 s window
  that the sniffer cannot see; on the near-empty 5 GHz 149, 5.4× the decoded airtime.
- `offs 0` advances at millions per second and does not correlate with traffic — a clock of
  some kind, not occupancy. `offs 3` reads exactly 65535 on every channel and is not a
  counter. The remaining accepted offsets sat at zero throughout.

### The full accepted set, and what it confirms

All 19 accepted offsets, read around 12 s dwells with the sniffer running (2026-09-03):

| offs | vendor name | 2.4 GHz ch6 | 5 GHz ch36 |
|---|---|---:|---:|
| 0 | `MIB_CNT_RX_FCS_ERR` | 7,995,805 | 51,315,872 |
| 1 | `MIB_CNT_RX_FIFO_OVERFLOW` | 0 | 0 |
| 2 | `MIB_CNT_RX_MPDU` | 414 | 1,184 |
| 3 | `MIB_CNT_CHANNEL_IDLE` | 65,535 | 65,535 |
| 4–6, 8, 10 | vector drop, delimiter fail, vector mismatch, PF drop, A-MPDU RX | 0 | 0 |
| 7 | `MIB_CNT_MDRDY` | 539 | 1,966 |
| 9 | `MIB_CNT_LEN_MISMATCH` | 3 | 7 |
| 11 | `MIB_CNT_P_CCA_TIME` | 1,184,019 (9.79%) | 276,630 (2.30%) |
| 12 | `MIB_CNT_S_CCA_TIME` | 0 | 1,298 |
| 14 | `MIB_CNT_CCA_NAV_TX_TIME` | 1,186,364 | 299,091 |
| 17, 20–23 | `BCN_TX`, `TX_BW_20/40/80/160MHZ` | 0 | 0 |

Two things fall out that were not designed for.

**The TX counters are a free consistency check.** `BCN_TX` and all four `TX_BW_*` counters
read exactly zero on both bands, which is what must happen in a receive-only driver that
never transmits. Nothing forced that; it is the enum mapping confirming itself.

**`offs 0` does not behave like its name.** `MIB_CNT_RX_FCS_ERR` at 666k/s on 2.4 GHz and
4.3M/s on 5 GHz is not a plausible FCS error rate, and the value scales with band rather than
with traffic. The name is recorded as unverified: whatever offset 0 is on this part, the
sweep evidence does not support calling it an FCS error count, and it is not used.

`band_idx = 1` is accepted by the firmware. The USB parts are single-band, so what it reports
is not investigated.

### The measurement, working end to end

`scripts/mib_survey.py` now takes its occupancy from the MCU rather than the dead registers
(`--registers` still reads those, so that negative result stays reproducible). An 8 s dwell
per channel, 2026-09-03:

| channel | dwell | busy | decoded airtime | occupancy the decoder missed |
|---|---|---:|---:|---:|
| 2.4 GHz ch6 | 8 s | 10.03% | 641,536 µs | **+165,303 µs** |
| 2.4 GHz ch6 | 12 s | 9.07% | 938,308 µs | **+150,142 µs** |
| 5 GHz ch36 | 8 s | 2.34% | 197,163 µs | −9,607 µs |
| 5 GHz ch36 | 12 s | 2.35% | 264,371 µs | +18,331 µs |

Decoded airtime is aggregation-aware, so an A-MPDU costs one preamble rather than one per
subframe. That made no measurable difference in these captures — every frame came back flagged
`non_ampdu`, and 0 of 400 sampled frames were A-MPDU subframes — but the naive sum inflates
decoded airtime severalfold on aggregated traffic, which would mask the gap entirely.

The 2.4 GHz result is the durable one: roughly a sixth of that channel's occupancy never
becomes a frame this driver can show you, on both dwells.

**On 5 GHz the residual is noise around zero**, −9,607 µs on one dwell and +18,331 µs on the
next, about ±5% of the decoded total in each direction. The reading is that the decoder
accounted for essentially all the occupancy there, and what is left is the difference between
a hardware measurement and a model: `rxd.airtime_us` estimates preamble plus payload at the
decoded rate. The sign of that residual is not stable across runs, so it carries no
information about the channel and should not be read as one.

### The counters have real names

The numbering was then corroborated against MediaTek's own `ENUM_MIB_COUNTER_T`
([RELATED_WORK.md](../RELATED_WORK.md#mediatek-mt_wifi-driver-headers)), which numbers the
same quantities identically. The tie is not just that the names fit: the enum is **undefined
at 13, 15 and 16**, and those are exactly the offsets below 17 that returned no reply here.

| offs | vendor name | measured behaviour |
|---|---|---|
| 2 | `MIB_CNT_RX_MPDU` | matched the decoder's frame count to within one, four channels |
| 3 | `MIB_CNT_CHANNEL_IDLE` | exactly 65535 everywhere; not a usable counter |
| 7 | `MIB_CNT_MDRDY` | ~2× the delivered MPDU count — preambles detected, not delivered |
| **11** | **`MIB_CNT_P_CCA_TIME`** | **primary-channel CCA busy time, µs** |
| 12 | `MIB_CNT_S_CCA_TIME` | 512 µs at 20 MHz against 3224 and 3772 at 80 MHz |
| 14 | `MIB_CNT_CCA_NAV_TX_TIME` | µs, tracks 11 and exceeds it |

`offs 14` is **not** settled. It runs consistently above `offs 11` by 9-15% of the dwell on a
busy channel, which fits its name — CCA plus NAV plus TX against primary CCA alone — but nothing
here isolates which term accounts for the difference. A transmit experiment on `spike/cross-measure`
did not separate them: the NAV component, set by other stations, dominates.

`offs 12` was a falsifiable prediction and it held: a *secondary*-channel counter must stay
near zero without a secondary channel, and it rose six- to sevenfold when the sniffer moved
from 20 MHz to 80 MHz.

So **`offs 11` is the channel-occupancy measurement** this effort was for, and `offs 7`
against `offs 2` is a second, independent view of the same blind spot: the PHY detects
roughly twice as many preambles as it delivers frames.

This satisfies acceptance criteria 4 and 5 for Spike A's measurement, by a different route
than Spike A proposed. The MIB *registers* remain dead; the MCU path reaches live counters.

## Capability map

MediaTek's `mt_wifi` headers list 127 `EXT_CMD_ID` values against mt76's 52
([RELATED_WORK.md](../RELATED_WORK.md#mediatek-mt_wifi-driver-headers)). Cross-referencing
that list against the dispatch tables in the MT7921 image: **57 of the 127 have a slot**. The
measurement-relevant ones, with what hardware said where it was asked:

| id | command | slot | hardware, asked 2026-09-03/04 |
|---|---|---|---|
| `0x5a` | `GET_MIB_INFO` | `0xe02767c0` | **working** — live counters, this chip's own numbering |
| `0x2c` | `THERMAL_CTRL` | — | **working** — the driver uses it |
| `0x01` | `EFUSE_ACCESS` | `0x0091837e` | **working** — the driver uses it |
| `0xa3` | `RDD_IPI_HIST_CTRL` | `0x00961422` | accepted; returns the documented 56-byte histogram under QUERY, all bins zero |
| `0x9d` | `SET_RDM_RADAR_THRES` | `0x009616d0` | accepted, status 0 |
| `0x1c` | `GET_TX_POWER` | `0x00967a0c` | answers, but not the question — see below |
| `0x3a` | `RDD_ON_OFF_CTRL` | `0x0095c90e` | **silent** — neither answered nor refused |
| `0x56` | `WIFI_SPECTRUM` | `0x009214c8` | **silent** |
| `0x4a` | `RX_AIRTIME_CTRL` | `0x009241a2` | refused |
| `0x30` | `GET_TX_STATISTICS` | `0x009175b4` | refused |
| `0xb0` | `GET_STA_TX_STAT` | `0x00951f00` | refused |
| `0x70` | `EDCCA_CTRL` | `0x00955968` (null handler) | refused |
| `0xad` | `PHY_STAT_INFO` | none | refused |
| `0x7c`, `0x38` | radar threshold, feature control | none | refused |

Three states, and the third is the one worth naming. **Refused** is a dispatch-level rejection
with a known signature. **Silent** is neither: `RDD_ON_OFF_CTRL` and `WIFI_SPECTRUM` produce no
reply at all, repeatably, on channels where every other command answers. Both are RDD-family
commands, and `WIFI_SPECTRUM` is an opmode of `EXT_CMD_RF_TEST` (`OPERATION_WIFI_SPECTRUM = 4`)
rather than a standalone command, so the likely explanation is that they require the firmware to
be switched into RF-test mode first — a much larger state change than anything attempted here,
and one that stops normal capture.

`GET_TX_POWER` deserves its own note because "answered" flattered it. It replies eight bytes and
is never refused, but the reply does not vary with the tuned band, the tuned channel, or the
`u1PowerCtrlFormatId` field: it returns `04 00 24 00 …` whenever the requested channel is zero
and `04 00 23 00 …` whenever it is not, and nothing else moves it. Whatever that is, it is not
per-channel transmit power, and it is not used. A command that replies is not a command that
answers, which is why the probe records the reply bytes rather than a verdict.

Command names beyond those measured are not transcribed into this repository; the header they
come from is proprietary. They are recorded here as observations about what the interface
contains, with the citation, so the next session knows where to look.

### The IPI histogram is reachable, and specified

This is where the investigation started — `rdmGetIpiHist` in the firmware strings, and
`mt792x_phy_get_nf()` returning a hardcoded 0 — and the interface turns out to be fully
specified in the vendor header, as `EXT_CMD_ID_RDD_IPI_HIST_CTRL` (0xa3), which mt76 does not
mention at all.

The command takes an index, a band, a set flag and four idle-power parameters. The reply event
carries **12 counters plus a TX-assert time in microseconds**, and the header documents each
bin as a power range: `<= -92 dBm`, then `-92..-89`, `-89..-86`, `-86..-83`, `-83..-80`,
`-80..-75`, `-75..-70`, `-70..-65`, `-65..-60`, `-60..-55`, `> -55`, and an eleventh entry
that is a free-running counter incrementing once per 8 µs — the denominator that turns bin
counts into dwell fractions. Those boundaries are exactly mt7915's `nf_power[]` table, which
is what confirms the two are the same instrument reached by different routes.

**Measured 2026-09-03.** The command is accepted, and **the reply arrives on the command
itself when the QUERY bit is set** — no asynchronous event to catch. Without the bit it
returns a 16-byte acknowledgement, `a3000000 00000000`, status zero, which is categorically
different from the `0xfe` refusal `RX_AIRTIME_CTRL` and `PHY_STAT_INFO` return. *With* the
bit it returns exactly 56 bytes: `sizeof(EXT_EVENT_RDD_IPI_HIST)`, with `ipi_hist_idx`
correctly echoed in byte 0 for every index 0-14 tried, `band_idx` in byte 1, the twelve
counters at byte 4 and the TX-assert time at byte 52.

So the transport is solved and the reply layout is confirmed against the vendor struct.
**The sampling engine is not running:** every bin reads zero, and so does the free-running
counter that should tick once per 8 µs regardless of what the radio hears. Three ways to
start it were tried and none worked:

| attempt | result |
|---|---|
| `RDD_SET_IPI_CR_INIT`, then `HIST_RESET` | accepted, no effect |
| `RDD_SET_IDLE_PWR` with threshold −92, max count 0xffff, duration 100000 | accepted, no effect |
| `RDD_ON_OFF_CTRL` (0x3a) `RDD_START`, on a DFS channel and a non-DFS one | **no reply at all** — neither answered nor refused |
| `EDCCA_CTRL` (0x70) `EDCCA_CTRL_EN` | **refused** |

The `EDCCA_CTRL` refusal is a second successful offline prediction: the command-map scan found
its dispatch slot handler reads `0x00000000`, a null pointer, and the hardware refuses it.

What is left is a genuine unknown rather than one more parameter to try. Candidates, in the
order worth attempting: `RDD_ON_OFF_CTRL`'s silence may mean it needs a longer timeout or a
different `rdd_idx`/`rx_sel` than 0, and the whole IPI block may be gated behind that; the
`set_val` and `idle_pwr_cmd_type` fields may not carry the set type the way this attempt
assumed, since all three set forms were accepted without complaint and none changed anything;
or the sampler may need a PHY register poked directly, which is where Spike B's
`MT_WF_PHY_RX_CTRL1_IPI_EN` comes back into scope — now with a documented reply format to
verify against, which is what it lacked before.

If that works it is a real noise floor on a part whose driver reports none.

### Spike B, run: the window is mapped, the histogram is not there

Run for the first time 2026-09-03, and it answered the question it was written for. The USB
register window **does** reach `0x83xxxxxx`: 64 words at `0x83000000` returned 48 distinct
values with no errors, and `0x83080000` likewise. So "can we reach the PHY register space
over USB at all" is settled, yes.

The histogram is not at mt7915's address. The 1024-word window at
`MT_WF_IRPI_NSS(0, 0)` = `0x83006000` reads as a single value, `0x00000000`, and both chains'
bins are zero. Nor does `0x83000000` look like a register block on this part: its live words
are dominated by `0x35353535`, which is ASCII `5555` — mapped memory holding something else.
`0x83080000` reads more like registers (`0x1000`, `0x3800`, `0xfffcfffc`).

That makes the spike's remaining value concrete rather than speculative. A write to
`MT_WF_PHY_RX_CTRL1_IPI_EN` was previously untestable, because there was no way to check
whether it had done anything. There is now: `RDD_IPI_HIST_CTRL` returns a documented 56-byte
histogram whose bins and free-running counter are all zero, so a write that starts the
sampler would be visible immediately. The probe still refuses `--enable`; lifting that is a
deliberate step, taken with a verification path in hand.

## How to hunt a command

The four instruments built here compose into a loop that takes an hour and needs no
disassembly. It is written down because every lead below runs through the same steps.

1. **Is it in the image?** `scripts/fw_triage.py --command-map` scans the rodata dispatch
   tables. Zero hits across every region is a real absence; a hit only makes it a candidate.
2. **Does the firmware admit to it?** Send it and check for the refusal:
   16 bytes, echoed ext_cid, `0xfe`. `scripts/mcu_stats.py` recognises this. Calibrate against
   a control that works (`THERMAL_CTRL` 0x2c returns a temperature) so a broken send is not
   mistaken for a refusal.
3. **What does it accept?** Sweep the parameter with a short timeout and record which values
   reply and which go silent. The accepted set is usually its own numbering, and its *gaps*
   are the fingerprint that identifies it.
4. **What does it mean?** Read twice around a dwell across several channels and bandwidths,
   beside a quantity you already trust — the decoder's frame count and summed airtime. Name
   counters by what they track, then look for a vendor header that numbers the same
   quantities with the same gaps.

Step 4 before step 3's fingerprint is what makes the naming safe: `MIB_CNT_S_CCA_TIME` was a
prediction that survived a 20 vs 80 MHz test before it was a name.

## What to hunt next

Ranked. Each has a dispatch slot in the MT7921 image *and* a matching firmware string, which
is the cheapest evidence that something is there; none has been sent to hardware.

1. **Start the IPI sampler.** Transport, reply layout and command acceptance are all solved
   (above); only the engine is idle. `RDD_ON_OFF_CTRL` (0x3a) not answering is the most
   suspicious thread — every other command either answers or refuses. Failing that, Spike B's
   `MT_WF_PHY_RX_CTRL1_IPI_EN` write, which is now worth much more than it was because a
   documented 56-byte reply exists to verify it against. Highest-value lead by some distance.
2. **`EXT_CMD_ID_WIFI_SPECTRUM` (0x56)** — handler `0x009214c8`, and the image carries
   `%s : Wifi-spectrum is enable !!`. Nothing in mt76 drives it. If it does what its name
   says, it is a spectrum view rather than a single occupancy scalar, which is a different
   class of instrument from anything here.
3. **`EXT_CMD_ID_EDCCA_CTRL` (0x70)** — 24 EDCCA strings in the image, including per-band
   per-bandwidth thresholds (`B%d_EdccaTh:BW20=...`). Reading the threshold tells us what
   "busy" *means* for `P_CCA_TIME`, which currently has no calibration at all. Note its
   dispatch slot handler reads `0x00000000`, so expect a refusal.
4. **The accepted MIB offsets that stayed at zero** — 1, 4, 5, 6, 8, 9, 10, 17, 20-23. They
   reply, so they exist; they were simply quiet in monitor mode on the channels tried. Free
   to check, since the sweep already runs.
5. **RDD pulse reporting, `RDD_ON_OFF_CTRL` (0x3a) with `SET_RDM_RADAR_THRES` (0x9d)** — radar pulse detection is
   implemented and undriven. Raw pulse reports are a non-Wi-Fi energy source, useful well
   beyond DFS.
6. **`MIB_CNT_P_ED_TIME`** — primary-channel energy-detect time, the direct non-Wi-Fi
   interference figure. This firmware refuses its offset; worth re-checking on the MT7925 or
   a newer MT7921 build, though the MT7925's encrypted image means the offline half of the
   loop does not run there.

Out of reach for now: anything needing the MT7925's dispatch tables, and anything needing
real disassembly of the Xtensa code regions.

## Scope boundaries

- Nothing here transmits. Spike A and B are register reads; C touches no hardware.
- No survey orchestration, no place or room naming, no verdict rules. This repo is the
  instrument. Evidence stays chip-generic.
- No new documented capability without dated hardware evidence in TESTING.md, per the
  ROADMAP decision rules.
- MT7925 support for A and B is untested and unclaimed; its register map differs and its
  firmware is opaque.
