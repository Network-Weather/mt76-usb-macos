# MT7961 HE-LTF metadata: validated origin and an upstream pointer lead

**Group5 word0 bits18:17 independently track transmitted LTF codes0/1/2.**
Two fresh controlled runs receive48/48 frames, and every value matches the
requested training-field setting. The different location reached by current
MT7921's HE-radiotap pointer produces mostly3 and sometimes2, unrelated to the
known phase. This is a useful concrete maintainer-facing finding, not a claim
that we ran the Linux driver or completed an upstream fix.

## Source-defined alternatives, not an arbitrary byte search

Pinned gen4m commit`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`,
[nic_connac2x_rx.h](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic/nic_connac2x_rx.h),
defines `HAL_MAC_CONNAC2X_RX_VT_GET_LTF` at Group5 vector word0 bits18:17.
The neighboring definitions put GI at14:13, PHY mode at7:4 and STBC at1:0.
Only the two source-defined LTF positions were compared here; no vector-word sweep.

The local mt76 pin`c5a3bd91` and current upstream master, checked2026-09-05 at
**`be5ce7910521492d4a2e4ce7ee3843680a46c047`**, have the same relevant path:

- [mt7921/mac.c](https://github.com/openwrt/mt76/blob/be5ce7910521492d4a2e4ce7ee3843680a46c047/mt7921/mac.c#L330)
  sets`rxv` to Group3, consumes its two words, then on Group5 skips six words
  and reassigns`rxv` for the monitor RCPI read (line355).
- The later call (line435) passes that reassigned pointer to
  [mt76_connac2_mac_decode_he_radiotap](https://github.com/openwrt/mt76/blob/be5ce7910521492d4a2e4ce7ee3843680a46c047/mt76_connac_mac.c#L879).
  Its LTF expression reads`rxv[2]` bits18:17 and adds1 for radiotap encoding.

| Origin | Relative to Group5 | Meaning in this test |
|---|---|---|
| Vendor `u4RxVector[0]` | byte0 | Verified LTF code |
| Original Group3 pointer + `rxv[2]` | byte0 | Same verified location |
| Reassigned MT7921 monitor pointer + `rxv[2]` | byte32 / word8 | Does not follow the LTF setting |

The likely issue is **reusing the RCPI pointer as the HE-vector origin**.
A maintainer can evaluate preserving the original Group3 pointer for the
shared HE decoder and guarding extended-field reads on actual Group5 presence.
This is a suggested review direction, not a supplied patch or release-level
validation. Other HE fields and absence-of-Group5 behavior need their own audit.
No issue/email or external maintainer message was sent; this note is the gift
of documentation, reproducible controls and pointers requested for the roadmap.

## Receiver report switch and a non-repeating negative

The experiment reuses the already tested MT7961 Group5 report switch:
`0x820e7000` bit23, from `MT_DMA_DCR0_RXD_G5_EN`. It changes the descriptor
report, not RF channel/power/calibration. Upstream's initialization disables it
with a hardware-issues comment, so it remains **opt-in research** here.

`phy_tx_probe.py --suite he-table --transmitter mt7925 --channel 6 --per-phase 4
--receiver-g5 --acknowledge-experimental-transmit` checks the original word,
sets only bit23, verifies it, and always restores the exact original word.
For this option the probe additionally reloads **both** radios afterward.
Before/enabled words are`0x02773400/0x02f73400`; all restoration, alive and
both-reload checks pass in the five recorded runs.

The first all-enabled trial had0/24 exact receipts, although95 other decoded
frames arrived. A subsequent constant-format `--suite he-g5-cycle` gives
**4/4 off,4/4 on,4/4 off**, with Group5 present only in the on-phase.
The all-enabled HE table repeat receives22/24. Thus the first negative is not
promoted to a repeatable HE-suppression effect. The RF link is variable.

## Independent LTF observations

The final two runs compare both origins on each exact fresh-nonce frame with
valid FCS, using MT7925 TX and MT7961 RX, channel6/20MHz. Both receive4/4 in
every phase. GI and LDPC below come independently from the ordinary Group3
decoder; LTF comes from the newly validated Group5 location.

| HE-SU MCS0/NSS2 phase | Requested GI/LTF/LDPC | Group3 GI | Group5 word0 LTF | Exact frames, two runs |
|---|---|---|---|---|
| Baseline before | 0/0/0 | 0 | 0 | 8/8 |
| Paired1.6µs /2x-LTF | 1/1/0 | 1 | 1 | 8/8 |
| Paired3.2µs /4x-LTF | 2/2/0 | 2 | 2 | 8/8 |
| LTF-only change | 0/1/0 | 0 | 1 | 8/8 |
| LDPC | 0/0/1 | 0 | 0 | 8/8 |
| Baseline after | 0/0/0 | 0 | 0 | 8/8 |

The shifted-pointer field is3 in all GI1 frames, and mostly3 elsewhere with
occasional2. It is not a credible LTF readout. The two correct origins agree
by construction; the independent evidence is the receiving chipset's reports
matching controlled transmitter changes, including LTF-only changes at fixed GI.
This verifies decoded format codes, not an oscilloscope measurement of duration,
coding gain, calibrated power or range. No production decoder/API changed.

Early research output named the shifted candidate`he_ltf_size_raw`. The current
output explicitly separates`he_ltf_mt76_pointer_raw` from
`he_ltf_vendor_word0_raw`; do not reinterpret historical values as validated LTF.
The evidence normalizes the old candidate name to the explicit pointer label.
Missing/truncated Group5 yields null, never an invented zero.

[Sanitized evidence](../research/evidence/he-ltf-origin-2026-09-05.json).
No raw vectors, ambient identifiers, payloads or firmware bytes are included.

## Follow-up: more fields affected, no passive validation sample yet

The same vendor header defines Group5 word12 bits5:0 as BSS color and12:6 as
TXOP, word9 bits11:8 as spatial reuse1, and word0 bit31 as uplink. The shared
Linux HE decoder's original Group3-relative indices14/11/2 resolve to those
same locations. With MT7921's reassigned RCPI origin, they instead resolve to
Group5 words20/17/8. **Word20 is outside the18-word Group5 block**; it must
not be interpreted as an HE field. This is source-level offset arithmetic,
not an observed Linux output or a memory-safety/exploit demonstration. The
research extractor never follows that shifted address into frame content.

`rx_vector_probe.he_fields` now recognizes the exact Connac2 two-word Group3 /
18-word Group5 shape and uses the vendor origins for these four fields. The
existing Connac3 layout remains separate; truncated and mixed layouts return
unknown. This extends research extraction only, not production radiotap.

A passive8-second channel6/20MHz window receives419 good-FCS frames with
Group5 but no HE candidates. A following8-second channel36/80MHz window
receives no frames. Consequently **no BSS-color/direction/TXOP/spatial-reuse
measurement is validated by this trial**; do not infer zero values or feature
absence from the empty counters. Exact register restoration, alive check and
normal firmware reload succeed. No host transmission, BSS-color setting,
association, identifiers or payloads are saved.
[Sanitized passive evidence](../research/evidence/he-metadata-passive-2026-09-05.json).
