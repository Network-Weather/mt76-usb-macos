# Fixed PHY-rate transmit exploration

Measured 2026-09-04 Pacific (2026-09-05 UTC), macOS 26.6.1, Python 3.14.7,
MT7961 ALFA `0e8d:7961` and MT7925 A9000 `0846:9072`. Research-only additions;
neither production injection APIs nor C parity claims change. Firmware hashes and
redacted observations are in [evidence](../research/evidence/phy-transmit-2026-09-04.json).

## New on-air capabilities

**Later width breakthrough:** MT7925 HT8/2SS/40MHz is independently received
2/4 then4/4 with exact payloads and40MHz RX metadata. See the
[receive-path controls](#ht40-payloads-received-before-the-extra-receive-path-command).
This is bounded format validation, not stable wideband operation or throughput.

The second dongle matched each received probe's complete bytes, with valid FCS,
and reported its PHY independently. Channel 36, 20 MHz, one stream:

| Transmitter / variant | OFDM before | HT MCS 0 | HT MCS 7 | VHT MCS 0 | HE-SU MCS 0 | OFDM after |
|---|---:|---:|---:|---:|---:|---:|
| MT7925 initial, 5 per phase | 5 | 5 | 5 | 5 | 0 | 5 |
| MT7961, 10 per phase | 10 | 10 | 10 | 9 | 10 | 10 |
| MT7925 explicit fixed-20-MHz flag, 10 per phase | 9 | 10 | 10 | 10 | 0 | 10 |

Receiver rates: OFDM 6, HT0/VHT0 6.5, HT7 65, HE0 8.6 Mbps. These are
descriptor-derived PHY rates, not throughput. All observed candidate packets used
one stream, 20 MHz, GI code 0, and no LDPC. No claim about ACK, association,
aggregation, sustained operation, interoperability of these management frames,
other widths, or more distant links.

MT7925 reported successful no-ACK TX status for the initial HE packets even though
MT7961 decoded none. Setting connac3 `MT_TXD6_FIXED_BW` did not resolve this.
This is **no independent decode**, not proof that HE cannot transmit or that no
energy was emitted. PHY construction, receiver acceptance, and hidden table fields
remain candidates. Both radios answered afterward and transmitter firmware reload
succeeded on all three runs.

## Protocol pointers and reproduction

The [explicit MT7925 spatial-table control](FIXED_RATE_TABLE.md#explicit-spatial-path-selection-wtbl-is-not-path0)
now distinguishes the default WTBL selector from explicit indices0/1/24.
Indices1 and24 each receive4/4 one-stream HT probes in two fresh runs;
index0 is weak. This is a bounded transmit-path control, not calibrated antenna
selection, a power gain or restored RF health.

### Higher modulation: accepted TX requests, no good-FCS high-rate receipt yet

`--suite high-mcs --transmitter mt7925 --channel 6 --per-phase 4 --tx-timing`
uses six phases at20MHz: HT8 / HT15 / HT8, then HE0 / HE11 / HE0, all with
two streams. HT uses BCC/GI0; all three HE phases use LDPC/GI0/LTF1 so coding
does not change within the HE triplet. The pinned Connac3 rate fields encode
HT15 as`0x48f` and HE11/NSS2 as`0x60b`. The
[HE-SU configuration reference](https://www.mathworks.com/help/wlan/ref/wlanhesuconfig.html)
identifies HE11 as1024-QAM/5/6 and excludes BCC for MCS10/11; the helper
therefore rejects HE11 without the tested LDPC/LTF combination.

Two fresh24-frame runs receive **4/0/4/4/0/4** and **4/0/4/4/0/3** exact
good-FCS frames. All24 TX statuses per run report the requested rate,
single attempt, zero error bits and unchanged raw power36. HT15's64-QAM
and HE11's1024-QAM requests are accepted, but neither high-rate phase has a
verified payload receipt. That does not establish absence of RF energy or
lack of chipset support. Receiver filtering, decoding failures and the weak
current link remain relevant; these tests do not calibrate RSSI or link margin.
Both alive checks and transmitter reloads pass. No power increase, association,
aggregation or sustained throughput test was performed.

[Sanitized high-MCS controls](../research/evidence/high-mcs-2026-09-05.json).

### First40MHz control: status width works, independent reception does not

Historical negative: later receive-path controls below receive HT40 payloads.
HE40 remains without an independently decoded payload.

The later stable channel6 HT8/HE2SS narrow controls justified one bounded width
test. `--suite bandwidth --transmitter mt7925 --channel 6 --per-phase 4
--tx-timing --acknowledge-experimental-transmit` configures both radios to
primary6/center8/40MHz, then sends HT20/HT40/HT20 and HE20/HE40/HE20.
All24 frames remain synthetic, no-ACK and50ms paced; power is unchanged.
Connac3 TXD6 bit25 selects fixed bandwidth; bits24:22 select0/1 for20/40MHz.
Only bit22 changes between each narrow/wide/narrow triplet. TXS0 bits31:29
provide an optional independent **transmitter-reported** bandwidth code.

| Fresh trial | Exact receipts, six phases | TX statuses |
|---|---|---|
| Initial BCC | 4/0/4/4/0/4 | HE40 missing |
| BCC repeat with width decoding | 4/0/4/4/0/4 | 20/24; HT40 reports width1 |
| Corrected HE LDPC | 4/0/4/4/0/4 | 24/24; both wide phases report width1 |
| Fresh HE LDPC repeat | 4/0/4/4/0/4 | 24/24; both wide phases report width1 |

The first HE40 request was not a qualified HE-SU format: full40MHz requires
LDPC. [MathWorks' HE-SU configuration](https://in.mathworks.com/help/wlan/ref/wlanhesuconfig.html)
limits BCC to RU sizes at most242 tones, and
[Rohde & Schwarz's signal-generation note](https://scdn.rohde-schwarz.com/ur/pws/dl_downloads/dl_application/application_notes/1gp115/1GP115_0E_Generating_WLAN_11ax_Signals.pdf)
specifies LDPC above20MHz. The corrected suite uses LTF1/GI0/LDPC1 for **all
three HE phases**, so its width comparison does not also change coding.
HT retains LTF0/GI0/BCC. The original BCC-wide variant is not a CLI option.

Changing to LDPC restores the missing HE40 TX statuses twice. Every observed
status reports format0, transmit count1 and no error bits16..22; neither this
nor the width code proves a decodable transmission. **No40MHz frame was
independently received**, while all16 narrow controls arrive in each run.
The corrected HE20 receipts independently report LDPC=true. RF/receiver-width
configuration and wide PHY construction remain unresolved; no power, antenna,
factory-calibration or unknown table-field sweep followed. Both alive checks
and both normal reloads pass, returning each radio to channel6/20MHz.
[Sanitized width evidence](../research/evidence/bandwidth-transmit-2026-09-05.json).

#### Error-delivery and PHY-detection follow-up

The later [FCS-filter breakthrough](ERROR_FRAME_CAPTURE.md) permits a stronger
test than simply waiting for good frames. With both radios still configured
primary6/center8/40MHz, clear only the MT7961 MAC FCS-drop bit, retain normal
sniffer drop_err1, and add a known HT15/20MHz failed-frame control. Seven
four-frame phases are HT20, HT15/20, HT40, HT20, HE20, HE40, HE20. HE keeps
GI0/LTF1/LDPC1. No power or calibration changes.

An initial immediate-readback guard stopped **before any TX** because the
asynchronous filter bit had not changed; both radios reloaded. Applying the
already established50ms settle interval verifies`RFCR201002→201000`.

| Trial | Exact good receipts, seven phases | Wide failed metadata / MAC FCS |
| --- | --- | --- |
| Open filter, no PHY enable | 3/0/0/4/3/0/4 | Neither wide phase produces failed frames or MAC errors |
| Open filter + known PHY enable | 3/0/0/4/4/0/4 | Neither wide phase produces failed frames or MAC errors |
| Fresh published reproducer | 3/0/0/4/4/0/4 | Same |

All28 TX statuses arrive in each completed run, format0/count1/no reported
errors; wide phases report bandwidth1. The failed HT15 control yields three
HT15 metadata records plus one unrelated/unverified OFDM-named record in the
first run, then four HT15 failed records and four MAC FCS samples`[1,0]` in
each PHY-enabled run. Failed payload identity is never claimed.

The two PHY-enabled runs use only the already qualified`0x83082004` mask`0xe00`,
clear then`0xa00`. **All16 combined HT40/HE40 windows have zero OFDM PD and MDRDY
increments**, no SIG/tag-error increments, no MAC FCS increment and no failed
frame delivery. Each HT15 control window increments PD/MDRDY by1; narrow good
controls also increment these fields (one extra PD in one window is retained).
Thus the wide negative is not explained by the FCS filter hiding otherwise
normal failed payloads. It still does not prove absence of RF energy: transmitter
PHY construction, frequency placement, receiver configuration and sensitivity
remain possible causes. The PHY FCS latch is not treated as an accumulating count.

The pinned [vendor TXD header](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic/nic_connac3x_tx.h)
describes DW6 bandwidth as bits25:22; its
[descriptor builder](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_txd_v3.c)
uses literal8 for fixed-rate packets. This agrees with our working fixed20
setting, but does not independently qualify9 as working40 on this firmware.
The generic `FIX_BW_20=4` enum belongs to another abstraction and was not blindly
substituted into this field. No bandwidth-nibble sweep was performed.

Reproducer: [`width_error_probe.py`](../research/width_error_probe.py), requiring
TX, error-capture and counter-write opt-ins. Filter/counter bits and both normal
reloads are verified. [Sanitized evidence](../research/evidence/width-error-controls-2026-09-05.json)
contains bounded status, counter and anonymous PHY observations, not failed
frame bytes or ambient identifiers. Production defaults remain unchanged.

#### Secondary-channel detections follow the TX bandwidth setting

The zero-PD result above is specific to the receiver configured at40MHz.
Two fresh `--suite frequency` runs retain TX primary6/center8/40MHz and put
RX at20MHz on primary6, center8, secondary10, then primary6 again, bracketed
by HT8/20MHz controls. All four secondary-channel HT40 windows in each run
increment OFDM PD and MDRDY by1, yet the return-primary HT40 windows increment
neither. Narrow before/after controls each deliver4/4 exact good frames.
Initial-primary and center detections vary; retune history remains a confounder.

`--suite secondary` removes that confounder from the width comparison: hold
RX at channel10/20MHz through four consecutive HT8 phases, with requested TX
widths20/40/20/40. Only the TX descriptor bandwidth changes between these
phases; the fixed-rate table is reprogrammed with identical contents. Primary6
HT20 controls bracket the sequence. Each phase has four no-ACK synthetic frames.

| Fixed-secondary trial | OFDM PD increments in middle four phases | Exact good primary controls |
| --- | --- | --- |
| Initial | 0/4/0/4 | 4/4 before and after |
| Published reproducer | 0/5/0/4 | 4/4 before and after |

Every one of the16 wide windows across both trials has an OFDM detection;
all16 narrow secondary windows have none. MDRDY increments in8/8 wide
windows initially and7/8 in the repeat (15/16 combined); the missing window has
an OFDM SIG error. The repeat also retains one extra PD and unrelated CCK
activity. No wide exact payload or failed-frame metadata arrives in either
fixed-secondary run. All24 TX statuses per run report count1/no errors and
the requested bandwidth; both filter/counter restoration and normal reloads pass.

This supports a width-dependent RF effect independently detected by the other
radio, **not** validated40MHz packet transmission, calibrated occupied bandwidth,
or authenticated ownership of individual PHY counter increments. The receiver
at40MHz and its tuning history now deserve specific attention. Linux's sniffer
encoding intentionally uses bandwidth0 for both20 and40MHz, with secondary
channel offset distinguishing40; changing it to the80MHz enum is not a fix.
[Pinned sniffer encoding](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mcu.c#L1181).
[Sanitized four-run evidence](../research/evidence/width-frequency-controls-2026-09-05.json).

#### HT40 payloads received before the extra receive-path command

The pinned [Linux startup path](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/main.c#L226)
sends EXT`0x4e` SET_RX_PATH in addition to ordinary channel switching. Our
normal monitor initialization does not. `width_error_probe.py --suite rxpath`
tests that difference with16 no-ACK HT8 frames: HT20, HT40, the source-shaped
receive-path request at primary6/center8/40MHz, HT40 again, then HT20.
The request uses RX antenna mask3 rather than CHANNEL_SWITCH's stream count2;
this distinction follows the [request builder](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mcu.c#L885).
No power, calibration or RF-test changes are made.

| Fresh run | Exact HT20 before | Exact HT40 before RX_PATH | Exact HT40 after RX_PATH | Exact HT20 after |
| --- | --- | --- | --- | --- |
| Prototype | 3/4 | 0/4 | 0/4 | 4/4 |
| Published reproducer | 3/4 | **2/4** | 0/4 | 4/4 |
| Fresh repeat | 3/4 | **4/4** | 0/4 | 4/4 |

All six good wide receipts independently report **HT/MCS8/NSS2/40MHz/GI0/BCC**,
match the complete fresh-nonce synthetic frame and have no FCS error. Their TX
statuses report code`0x488`, width1, count1, no errors. This establishes that
the existing fixed-width descriptor can produce decodable HT40 packets;
no descriptor change was needed for the breakthrough. Reliability across
initialization states remains unresolved, and prior negative runs are retained.

Before RX_PATH, OFDM PD/MDRDY increments occur in3/4,3/4,4/4 wide windows.
After RX_PATH, **all12 wide windows have zero PD/MDRDY**, while all narrow
after-controls arrive. The known filter/counter bits remain intact. That
repeatable transition argues against treating the extra startup command as a
wide-reception fix; it does not establish a Linux regression or silicon defect.
All16 statuses and both normal firmware reloads succeed in each run.

A separate channel36/center38/40MHz28-frame test has no good narrow or wide
receipts and zero OFDM PD throughout. A12-frame follow-up holds RX36/20MHz
and sends only HT8/20 while changing TX channel context20/40/20; its narrow
controls also fail. **These5GHz runs are not usable width comparisons.** The
subsequent2.4GHz runs above retain positive controls, so firmware-alive status
is not being substituted for RF health. No power increase or calibration write
was attempted. [Sanitized evidence and sniffer code-hash provenance](../research/evidence/width-rxpath-and-sniffer-2026-09-05.json).

### HE extended-range SU is received, but not yet a robust link

`--suite he-er --transmitter mt7925 --channel 6 --per-phase 4` uses five
20MHz phases with LTF1/GI0/LDPC0 and unchanged power: HE2SS, ordinary HE1SS,
HE-ER1SS, HE-ER1SS/DCM, HE2SS. Rates`0x240` and`0x250` encode mode9 and its
DCM bit4; NSS stays1 and no upper106-tone, STBC or beamforming setting is used.
This follows the existing pinned mt76 enum/header, not a guessed command.

| Fresh run | HE2SS before | HE1SS | HE-ER1SS | HE-ER/DCM | HE2SS after |
|---|---|---|---|---|---|
| Default receiver,4 per phase | 4/4 | 1/4 | **1/4** | 0/4 | 4/4 |
| Group5 receiver,6 per phase | 5/6 | 2/6 | **1/6** | 0/6 | 6/6 |

Both exact ER receipts independently decode as **HE-ER-SU, MCS0, NSS1/NSTS1,
20MHz, GI0, no LDPC/DCM/STBC**,8.6Mbps calculated rate. The Group5 receipt also
reports LTF1 at the independently validated word0 location; the shifted Linux
pointer candidate reports3 and is not interpreted as LTF. This establishes a
transmit format, **not extended usable range, reliable delivery, or a power gain**.
Ordinary one-stream controls are also weak. DCM remains unreceived, not proven
incapable of transmitting. No further stream/power sweep was performed.

Both alive checks and transmitter reload pass. The Group5 run additionally
restores the exact receiver report register and reloads the receiver successfully.
[Sanitized HE-ER evidence](../research/evidence/he-er-transmit-2026-09-05.json).

### 2.4GHz follow-up: usable forward direction, reverse still unverified

`--suite lowband --channel 1 --per-phase 4` uses six bounded phases at20MHz:
OFDM6, HT0/1SS, HT8/2SS, HE0/1SS, HE0/2SS, OFDM6. It excludes VHT and all
wider bandwidths; the existing60-packet ceiling,50ms spacing, no-ACK policy,
fresh private nonce and independent whole-frame/FCS/PHY checks remain. Only
channels1/6/11 accept this suite and the later CCK/preamble, STBC, HE-coding,
HT/HE-table, HE-ER, HE-coding-LTF, HE-Group5-cycle and timing-burst suites;
baseline/streams/spatial require36/149.

Two fresh MT7925-transmitter runs at12:00:43 and12:01:34 UTC on2026-09-05
each submitted24 frames. The MT7961 receiver independently reported:

| Setting | Run1 exact receipts | Run2 exact receipts | Verified receive PHY |
|---|---:|---:|---|
| OFDM before | 4/4 | 4/4 | OFDM6,1SS,20MHz |
| HT0 | 4/4 | 4/4 | HT MCS0,1SS,20MHz |
| HT8 | 4/4 | 4/4 | HT MCS8,2SS,20MHz |
| HE0,1SS | 1/4 | 0/4 | One HE-SU MCS0,1SS receipt only |
| HE0,2SS | 4/4 | 4/4 | HE-SU MCS0,2SS,20MHz |
| OFDM after | 4/4 | 4/4 | OFDM6,1SS,20MHz |

This establishes a reproducible **2.4GHz forward probing path** for OFDM,
HT1/2SS and HE2SS. HE1SS remains unreliable. Raw receiver signal values were
roughly−94..−92, so these successes do not establish restored RF power or a
healthy long-range link. No throughput/interoperability claim is made.

A reciprocal MT7961-transmitter run at12:01:06 UTC submitted24 frames but the
MT7925 independently received none. Both radios remained alive after all three
runs, and each transmitter's normal firmware reload succeeded. The reverse RF
problem remains unresolved; no additional power, antenna, factory calibration
or nonvolatile writes were attempted. The receiver stayed in normal monitor
mode; the cleanup evidence specifically covers the transmitter reload, not a
claimed second receiver reload inside this older probe.
[Lowband evidence](../research/evidence/lowband-transmit-2026-09-05.json).

### CCK rates and selectable preambles

`--suite cck` and `--suite preamble` use only channels1/6/11,20MHz, with the
same60-frame limit,50ms spacing, synthetic no-ACK probes, nonce matching and
independent good-FCS receive evidence. Protocol values come from pinned mt76
`mt76.h` `CCK_RATE`, `mac80211.c` `mt76_rates` / `mt76_get_rate`: mode0,
indices0/1/2/3 mean1/2/5.5/11Mbps; bit2 selects short preamble. The preamble
suite compares codes1/5 and3/7. No short-preamble1Mbps variant is attempted.

MT7925 forward TX, four frames per phase on2026-09-05:

| Run | OFDM before | Four CCK phases | OFDM after |
|---|---:|---|---:|
| ch1 CCK rates | 4/4 | 1/2/5.5/11Mbps long:4/4 each | 0/4 |
| ch1 preambles | 4/4 | 2-long/2-short/11-long/11-short:4/4 each | 1/4 |
| ch6 preambles | 0/4 | 2-long/2-short/11-long/11-short:4/4 each | 0/4 |

Receiver mode was CCK and rate/index matched each requested value, including
raw indices5/7 for short preambles. These are independently received PHY
controls, not inferred from successful TX status. All three fresh-nonce runs
submitted24 frames and passed both alive checks and transmitter normal reload.
No control used a power change. The weak/missing OFDM controls and roughly
−101..−100 raw signal on ch1 mean **RF recovery and general mode-switch health
are not established**. Successful CCK reception does not qualify throughput,
range, or calibrated airtime; the existing analytical airtime estimate still
uses a fixed long-CCK preamble and is not a preamble-duration measurement.

A source-defined CCK-only hypothesis for the failed reverse direction was also
tested: MT7961 submitted24 ch1 frames with OFDM controls and1/2/5.5/11Mbps CCK,
but MT7925 independently received none. Both alive checks and transmitter reload
passed. CCK did not restore the reverse path; no further power/calibration sweep
was performed.

[Sanitized CCK evidence](../research/evidence/cck-transmit-2026-09-05.json).

### Two-stream follow-up (2026-09-05 UTC)

**MT7925 two-stream HT, VHT and HE-SU reached the other dongle**, with exact
complete-frame matches, valid FCS and independent PHY metadata on channel 36,
20 MHz. The first run received 6/6 of each; a second run used a fresh per-run
vendor-IE nonce and received 4/4 of each, ruling out old buffered probes matching.

| Requested setting | Rate code | Independent MT7961 PHY report |
|---|---|---|
| HT MCS 8, 2 streams | 0x488 | HT, MCS 8, NSS 2, 20 MHz, GI 0, no LDPC |
| VHT MCS 0, 2 streams | 0x500 | VHT, MCS 0, NSS 2, 20 MHz, GI 0, no LDPC |
| HE-SU MCS 0, 2 streams | 0x600 | HE-SU, MCS 0, NSS 2, 20 MHz, GI 0, no LDPC |

Source: `mt7915_mac_write_txwi_tm` at c5a3bd91 derives HT NSS from MCS/8 and
encodes NSS-1 in the rate field; the shared connac headers define the bit ranges.
The MT7925 fixed-rate-table mechanism is unchanged. Run `phy_tx_probe.py` with
`--suite streams`; the six phases and 60-packet ceiling remain bounded.

**Controls are currently poor, so this is capability evidence, not a link-quality
or throughput result.** The fresh-nonce run received only 1/4 OFDM before, 1/4
HT0 and 0/4 OFDM after. Its reported signal values were around -103 to -98.5,
far weaker than earlier experiments (units remain device-reported, uncalibrated).
Both directions' one-stream controls failed on channel 149 in this follow-up.
MT7961 TX was not independently received in the initial and repeated stream runs.
MT7925 still received 173–288 ambient frames during the later MT7961 TX runs, so
its receiver was not simply silent. No ambient frames/identifiers were retained.

An explicit MT7961 test-mode exit and a forced whole-WFSYS reset were tried;
both reloaded successfully, but neither restored the reverse-direction control.
The forced reset changed firmware state from 3 to 0 before successful reload.
The cause of this RF-performance change is unresolved; **alive/reload success
does not prove restored RF performance**. Wider-band tests were deferred at this
point; the later stable channel6 controls permit the bounded40MHz test above.
No physical power-cycle or antenna adjustment
was performed. [Sanitized runs](../research/evidence/spatial-stream-transmit-2026-09-05.json).

### Spatial-path and firmware-table controls (2026-09-05 UTC)

`--suite spatial --transmitter mt7961` changes only Connac2 TXD word 7 bits
15:11, leaving the existing word-6 selector bit 10 zero. Five OFDM6 phases use
SPE indices `0,1,0,24,0`; power, 20-MHz channel 36, no-ACK and the private
per-run frame nonce are unchanged. The vendor gen4m source at `8fddb9d7`
(`wlanAntPathFavorSelect`, `wlan_def.h`, `nic_connac2x_tx.h`) names indices 0/1
as WF0/WF1 and 24 as duplicated one-stream selection. Upstream mt7915 test
descriptors likewise set the DW7 index without setting DW6 bit 10. These names
are source intent, not independently verified physical antenna routing here.

All 30 submissions produced TX statuses (raw power 44, OFDM6, no ACK-error bits),
but **zero exact frames arrived in any phase**. MT7925 received 202 unrelated
frames during this run; those frames were discarded, not saved. Both alive
checks and transmitter reload passed. Spatial index changes did not restore
the reverse-direction baseline; a silent RF path and ineffective descriptor
selection remain distinguishable possibilities, not resolved causes.

A separate **no-transmission** MT7925 test tried the upstream `UNI 0x40` fixed
rate-table command: tag 0, length 16, slot 18, OFDM6, WTBL selection, no
LDPC/beamforming/dynamic BW. Both zero GI/LTF and exact upstream GI/LTF=1/1
returned command-result **0xc0000001** with matched sequence. This is a
rejected request, not proof the entire command family is absent. The working
direct ITDR table-programming route is unchanged. Each trial reloaded normally.

Follow-up [ROM tracing and a corrected slot25 control](FIXED_RATE_TABLE.md)
establish that UNI40 works, but has an odd-index gate, a validation check after
the hardware write, and an apparently uninitialized low-nibble field. The same
trace unlocks independently received short-GI and LDPC HT transmission through
the existing deterministic direct-table route.
Subsequent HE tests independently receive GI1/GI2 when paired with the
corresponding LTF codes, and receive HE LDPC. Initial default-receiver trials
lacked full-group5 LTF metadata. A later [Group5-origin control](HE_LTF_RX_ORIGIN.md)
independently verifies the LTF codes on48/48 frames using the correct field origin.

[Sanitized evidence](../research/evidence/spatial-path-controls-2026-09-05.json)
contains all three trials. No power increase, calibration writes, association,
profile writes or beamforming/sounding transmission occurred.

### MT7925 HT STBC is independently received

`--suite stbc --transmitter mt7925 --channel 1 --per-phase 4` sends20 paced,
synthetic no-ACK Probe Requests with a fresh private nonce. Five phases use
HT8/two-stream, HT0/one-stream, HT0/STBC, HT0/one-stream, HT8/two-stream.
Only the established fixed-rate table changes; power,20MHz bandwidth, GI and
LDPC remain unchanged. The suite is low-band-only and chip-guarded.

The STBC rate is **`0x4480`**: Connac3 STBC bit14, space-time-streams-minus-one
field1 at bits13:10, HT mode2 at bits9:6, MCS0. Connac2 uses a different STBC
bit13 and is explicitly rejected for this code. The two-space-time-stream
encoding follows the upstream test-mode convention, not an assumption that
STBC means two independent spatial data streams.

| Fresh channel1 run | HT8 before | HT0 before | HT0 STBC | HT0 after | HT8 after |
|---|---|---|---|---|---|
| First | 4/4 | 2/4 | **4/4** | 1/4 | 4/4 |
| Repeat | 1/4 | 0/4 | **1/4** | 1/4 | 2/4 |

Every exact STBC receipt decodes as **HT MCS0, NSS1, NSTS2, STBC=true**,20MHz,
GI0, LDPC=false. Neighboring controls report STBC=false; HT8 has NSS2/NSTS2,
and ordinary HT0 has NSS1/NSTS1. The receiving radio's PHY/FCS/full-frame
checks establish the format, not the transmitter's status alone. The generic
TX-status rate field does not include its separately encoded STBC indicator,
so it is not used as STBC proof.

The fresh repeat confirms the format despite poorer reception in every phase.
This is **not a diversity-gain, calibrated power, throughput, or restored-link
claim**. Device-reported RSSI remains roughly−101..−102 and the link is variable.
Both alive checks and transmitter normal reload pass after both runs. The
existing probe reloads only the transmitter; it does not claim a receiver reload.

[Sanitized STBC evidence](../research/evidence/stbc-transmit-2026-09-05.json).
Primary source at mt76 commit`c5a3bd91aa735b669618610d5f0ebfa5786845a6`:
[Connac3 rate fields](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac3_mac.h),
[upstream STBC/NSS test encoding](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7915/mac.c).

### Initial HE coding negatives (LTF0)

The [LTF1 follow-up](FIXED_RATE_TABLE.md#he-stbc-unlocked-by-changing-ltf-alone)
subsequently receives HE STBC3/4 then2/4 with good HE2SS controls, while DCM
remains unreceived. Exact PHY reports are HE-SU/MCS0/NSS1/NSTS2/STBC=true.

The newer-chip-only `--suite he-coding` uses five four-packet phases at20MHz:
HE0/NSS2 before, HE0/NSS1, HE0/DCM/NSS1, HE0/STBC/NSS1, HE0/NSS2 after.
Candidate rates are`0x210` (HE mode8 plus DCM bit4) and`0x4600` (HE mode8,
two space-time streams, STBC bit14), from the same Connac3 header. Power, GI,
LDPC and the established descriptor/table mechanism are unchanged.

The linked LTF1 follow-up establishes HE STBC reception. These original
LTF0 observations remain valid, but are not the current capability limit.

| Fresh run | HE2SS before | HE1SS | DCM | STBC | HE2SS after |
|---|---|---|---|---|---|
| Channel1 | 1/4 | 0/4 | 0/4 | 0/4 | 0/4 |
| Channel6 | **4/4** | 2/4 | **0/4** | **0/4** | **4/4** |

Channel1 has an inadequate after-control. Channel6 brackets both candidates
with good HE reception, yet no exact candidate frame arrives. Its four DCM
statuses preserve rate`0x210`, report one transmission and no error bits;
those statuses do not establish correct RF emission. The STBC bit is separate
from the TX-status raw-rate field, so raw rate`0x600` cannot distinguish that
candidate from ordinary two-stream HE. Neither candidate is advertised as a
working format, and the negative does not establish silicon-wide absence.
Both radios remain alive and the transmitter reloads after each trial.
[Sanitized HE coding evidence](../research/evidence/he-coding-transmit-2026-09-05.json).

### Initial one-stream method (historical baseline)

All rate/descriptor facts come from mt76 baseline `c5a3bd91`:

- `mt76.h`, `enum mt76_phy_type`: HT=2, VHT=4, HE-SU=8.
- `mt76_connac2_mac.h` / `mt76_connac3_mac.h`: rate mode bits 9:6,
  index bits 5:0; tested codes `0x80`, `0x87`, `0x100`, `0x200`.
- Connac2 puts the code directly in TXD word 6 bits 29:16.
- Connac3 puts **table slot 18**, not the PHY code, in TXD word 6;
  `mt7925_mac_set_fixed_rate_table` writes the PHY code through ITDR0/ITDR1/ITCR.
  `DIS_MAT` preserves the synthetic frame. Optional `FIXED_BW` is word-6 bit 25.

With `MT76_FW_DIR` pointing at the pinned firmware directory, use the project venv:

```sh
python research/phy_tx_probe.py --transmitter mt7925 --acknowledge-experimental-transmit
python research/phy_tx_probe.py --transmitter mt7961 --per-phase 10 --acknowledge-experimental-transmit
python research/phy_tx_probe.py --transmitter mt7925 --per-phase 10 --fixed-bw --acknowledge-experimental-transmit
```

The tool ceilings are 60 packets total, 50 ms spacing, no ACK, channel 36 or 149;
tests above used 36 only. Firmware reload in `finally` removes table changes.
Only exact synthetic-frame metadata and TX statuses are emitted, never ambient
frame bytes or identifiers. Offline fixtures cover rate encoding, fixed-BW isolation,
allowlists, exact matching, duplicate counting, and FCS rejection.

## Receive-stat lead: AP interface is refused, station interface remains open

**Follow-up:** the [station testmode experiment](STATION_TESTMODE.md) unlocked
MT7961's CE queries after idle mode entry. A subsequent explicit RX-path write
activated live counters and signal words; their units and probe-specific effects
remain unvalidated.

`research/rx_stat_query.py --usb-id 0e8d:7961` tested EXT `0xa4` QUERY,
four-byte payloads `00 00 00 00`, `03 00 00 00`, `04 00 00 00`,
`05 00 00 00`, `06 00 00 00`. All five yielded the existing calibrated
16-byte dispatch refusal signature. Full firmware reload and alive check passed
after each request. No matching `{handler,cid}` slot was found in any extracted
MT7961 firmware region. Request shapes are independently constructed from protocol
facts in the reference-only vendor header described in [RELATED_WORK](../RELATED_WORK.md#mediatek-mt_wifi-driver-headers).
This is not an enum/code transcription and is not a claim about MT7925 UNI.

More promising next measurement route: station-specific CE `TEST_CTRL` (`0x01`)
on MT7961, and UNI `TESTMODE_CTRL` (`0x46`)/`TESTMODE_RX_STAT` (`0x32`) on
MT7925. Upstream `mt7921/testmode.c`, `mt7925/testmode.c`, and their `mcu.h`
provide wrappers, but not the complete statistics selectors. MT7925 testmode
requires special UNI option bytes 0x02 (query) / 0x06 (set); the current generic
Python UNI helper does not implement that special case. Do not mistake a generic
ACK or a malformed request for a working statistics interface.

## Die-temperature control after the RF change

Three read-only observations after fresh normal boots returned **28 C on MT7961**
and **42 C on MT7925**, each stable across the three queries. These observations
do not point to current extreme die heating, but do not establish the earlier
one-stream/TX performance change's cause or exclude past/localized thermal issues.
No TX was performed; reload/alive checks passed on both devices.
[Evidence](../research/evidence/die-temperature-control-2026-09-05.json).

Queries match `mt7921_mcu_get_temperature` / `mt7925_mcu_get_temperature` in
mt76 `c5a3bd91`: MT7961 EXT 0x2c with eight zero bytes; MT7925 UNI 0x35 QUERY
with reserved4 + tag0/length8 + zero4. MT7925 returned EID 0x35 with matching
sequences, a 16-byte body, tag0/length12, category0, temperature u32 at body+12.
The production MT7925 temperature method remains explicitly unported; this is
a research validation of the upstream request, not a claim of API parity.
