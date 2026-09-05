# Firmware exploration continuation — 2026-09-05

Tracking [PR #31](https://github.com/Network-Weather/mt76-usb-macos/pull/31).
User-authorized autonomous measurement/TX exploration; not a networking driver.
No merge, nonvolatile firmware writes, host-memory DMA, raw ambient captures, or
calibrated claims by inference. Results below extend [station testmode](STATION_TESTMODE.md).

**Remaining RF-init controls narrowed; PHY counters do not fill P-RXV2:**
[Exact field maps and accessor correction](LEGACY_ICS.md#remaining-rf-init-fields-and-phy-counter-control)
show GP+10820 is a writer, not a getter. Several RF-init values already match
normal operation; other fields are MDP header translation/deaggregation and
MAC setup, not activated speculatively. A16/16-good normal ICS trial with the
known PHY counter enable still has8/8 sentinel vectors; restoration/reloads pass.
Next target: GET50 wideband/in-band signal fields and their hardware source.

**Traced RF DMA setup also fails to recover normal CFO/SNR:**
[Read-only staged comparison and two fixed controls](LEGACY_ICS.md#rf-dma-setup-matches-the-trace-but-is-insufficient-in-normal-mode)
confirm all five820e7050 field values at RF entry. Combined DMA/RMAC/RXV
activation receives8/8 good packets but retains sentinel CFO/SNR. A lone
post-restoration populated header lacks ordinary good-FCS reception and does
not repeat; it remains unexplained, not a working recipe. All44 TX statuses,
mask restoration and both-radio reloads pass.

**RF-init RMAC bit0 is not sufficient for normal CFO/SNR:**
[One-bit and combined RXV controls](LEGACY_ICS.md#rf-init-rmac-bit0-does-not-fill-normal-p-rxv2)
receive24/24 exact packets and24/24 own ICS headers across two complete runs;
all CFO/SNR fields remain−1/63. A failed3/4 prerequisite is retained separately.
All28 TX statuses and candidate/RXV/ICS restorations plus reloads pass. The
next source-derived target is RF-init's five fields at820e7050, not a sweep.

**Normal RXV START does not fill CFO/SNR; source quiesce is reversible:**
[Pinned old-chip ROM mapping and controls](LEGACY_ICS.md#normal-rxv-start-is-insufficient-quiesce-is-a-separate-operation)
resolve820e3014 bits8/7/4/2/0. Both activated START windows retain all-one
CFO/SNR while normal packets arrive. The actual quiesce routine clears both
start bits and handshakes bit2: ordinary delivery stops, but4/4 newly submitted
headers still appear in ICS; normal RX resume restores delivery and all masks.
The initial argument0-as-STOP interpretation was wrong and is explicitly
corrected; its failed masked cleanup needed reload. A repeat failed the normal
prerequisite and made no RXV writes. All radios reloaded successfully.

**Staged RF entry brackets availability without overclaiming causality:**
[Two20-frame runs](LEGACY_ICS.md#staged-entry-brackets-stream-availability-not-the-filling-bit)
receive8/8 normal controls, then7/8 RF START headers with populated CFO/SNR.
Entry-only, configured-before-START and stopped windows have no records even
with ICS enable readback. Forty TX statuses, all restoration/reloads pass.
The empty intermediate stages cannot identify the filling bit; static tracing
now identifies two specific old-chip vector-control wrappers to resolve next.

**RF-mode ICS exposes populated CFO/SNR beyond the five-record log cap:**
[Three successful controls](LEGACY_ICS.md#rf-mode-ics-streams-populated-cfosnr-beyond-the-finite-log-cap)
receive12/12 exact normal prerequisites and20/20 known RF headers. Each final
record exactly matches the stable72-byte C-RXV and16-byte P-RXV2 cache; CFO/SNR
are populated at104/108 in RF mode, unlike normal all-one fields. Two eight-frame
runs stream every own header while the finite log stays capped at5, no resets.
RF headers are not full-payload/FCS verdicts; no calibrated units. Failed ch36
prerequisite retained; all activated masks and both-radio reloads pass.

**Known HT traffic qualifies legacy Group5 plus ICS coexistence:**
[Three bounded controls](LEGACY_ICS.md#known-ht-stimulus-qualifies-simultaneous-group5-reception)
receive48/48 exact packets. Two Group5 runs prove16/16 full72-byte C-RXV copies
at ICS offset16, paired by known payload/header. Earlier passive misses remain
unexplained, not universal incompatibility. A guessed extra CFO/SNR placement
at104/108 returns all-one fields on24/24 normal-mode own packets and is rejected
for those captures (RF-mode filling is established above). All cleanup
passes; no raw vectors or ambient exports.

**Legacy CE93 opens RMAC diagnostics on MT7961 too:**
[Pinned handler and live controls](LEGACY_ICS.md) produce272-byte/count3 records
alongside normal CCK RX. Two runs give37 unique-header pairs: header120, RCPI40,
clocks12/92/164; all differ from the newer layout. Shared cleanup also needs
`820e0004` bits9/2. Group5-enabled passive controls lack paired ordinary RX;
the default-setting repeat recovers. Five runs pass masks and normal reload.

**RMAC ICS now has an in-memory bridge to ordinary receive metadata:**
[Four passive controls](ICS_CAPTURE.md#receive-records-can-be-paired-without-publishing-traffic)
locate24-byte header copies at144 and yield sixty unique-header pairs in three
mapping runs. RCPI word/byte copies and three relative clocks repeat across ch6
and ch36; C-RXV words0..21 match,22/23 fail. No traffic/identifiers/raw vectors
are exported. Two post-stop windows retain2/3 diagnostics despite cleared masks;
stop is not an immediate empty-queue guarantee. All restoration/reloads pass.

**ICS GI/LDPC controls narrow the noncontiguous TX-vector mapping:**
[Five coding runs](ICS_CAPTURE.md#guard-interval-and-coding-narrow-the-split-layout)
receive20/20 enabled-phase packets independently,48/60 overall. Changed patterns
qualify source-style GI at36 bits27:26 and LDPC at88 bit7; contiguous GI at28
fails. LDPC also changes offset48 bit12, so its low16 is not an unrestricted
length. HT normal/short-GI values fit the L-SIG model, without calibration claims.
All sixty TX statuses, control restores and both-radio reloads pass.

**ICS fields are PHY-format dependent; source-style TX-vector masks help:**
[Four CCK/HT/HE controls](ICS_CAPTURE.md#hthe-counterexamples-and-split-tx-vector-fields)
receive48/48 independently. Shape/sequences/clocks persist, but CCK length/rate
equivalences fail HT/HE: HT offset48 matches an L-SIG-length model, HE length
fields remain unresolved. TXV0 mode/power masks at24 and TXV2 rate/NSTS masks
at88 match known PHYs; a contiguous three-word cast at24 fails. No generic
decoder/calibrated-duration claim; all control restores and reloads pass.

**TMAC diagnostic filtering is traffic-class selective:**
[Five bounded filter controls](ICS_CAPTURE.md#tmac-filters-select-traffic-classes-not-smaller-subrecords)
map the highest request bit to hardware bit12. It suppresses probe reports but
retains data/QoS reports, repeated with24/24 independent mixed-frame receptions.
Both sequence and length copies identify the retained reports. All-five also
suppresses probes; first-bit alone does not.58/60 receptions overall; all filter,
enable and normal-reload cleanup passes. No smaller subrecord isolation claim.

**TMAC ICS power/rate fields survive independent controls:**
[Two negative-power and two CCK-rate runs](ICS_CAPTURE.md#power-and-rate-differentials)
locate offset24 bits23:16 matching TXS power36/32 and offset88 low14 matching
CCK codes0/1. Independent reception23/24 and24/24 respectively. Grouped versus
alternating rates reject two length-derived false positives. No calibrated-power
claim, positive offset or opaque export; all controls/reloads pass.

**TMAC ICS adds per-transmit diagnostic records with candidate fields:**
[Four off/on/off runs](ICS_CAPTURE.md#own-transmit-diagnostic-fields) produce
sixteen288-byte/frame-count2 aggregates only for the sixteen enabled-phase
submissions.43/48 packets independently received; all48 matched TX statuses.
Three differential runs map two sequence and two FCS-inclusive length candidates;
two clock fields exactly follow TXS inter-packet deltas in two runs, without an
absolute-clock/PPDU-boundary claim. No opaque record export; all cleanup passes.

**RMAC ICS opens another USB diagnostic stream:**
[Two off/on/off controls](ICS_CAPTURE.md#mac-receive-aggregates) produce20/21
type12 aggregates only while enabled, all384 bytes with declared frame-count3.
Four off windows have none; ordinary RX remains visible throughout. Start/stop
ACKs, two traced control bits, masked restores and normal reloads all pass.
Only aggregate shape/counts exported; inner records and measurements not decoded.

**A separate raw-PHY ICS path programs capture, but does not yet complete:**
[UNI49 capture](ICS_CAPTURE.md) exposes a repeating sixteen-chunk callback,
device SRAM export, concrete trigger/status fields, and a shared prerequisite
that is already set after normal monitor setup. Two bounded activations program
both rings/triggers but heads stay zero and no capture event arrives. Firmware
stop leaves index1 triggered; explicit both-index cleanup, thirteen masked
restorations and normal reload all pass. No raw sample export or working-sampler
claim; capture-source setup remains an investigation target.

**Histogram acquisition coexists with own TX, with a coverage caveat:**
[Four quiet/TX/quiet controls](NOISE_SELF_TRANSMIT.md) independently receive78/79
synthetic CCK1 frames. Two long bursts reduce sample totals and quiet-after
recovers; ambient activity outweighs a short burst in the retained final
counterexample. No high-bin pileup or calibrated correction claim. CCK payload
length adds exactly1024 MAC2PHY ticks per128 bytes. All masks/reloads pass.

**The vendor noise-average getter is not a measurement on these images:**
[Exact GET_NOISE queries](NOISE_AVERAGE_GETTER.md) find MT7925's QUERY branch
explicitly zeroing the reply data, with no PHY read. Twelve queries across two
6→36→6 runs return zeros; live code hashes match. MT7961 returns query ID0 and
fails correlation. No noise/gain setters; both radios remain alive and reload.

**Firmware-timed noise events now work:**
[UNI36/tag2](MT7925_NOISE_HISTOGRAM.md#one-shot-firmware-event-now-works) resets
and starts both control indices, then emits two11-bin arrays in512–515ms.
Three fresh boots on6→36→6 reproduce channel-dependent distributions and exact
event/stopped-register agreement. Both controls stop automatically; all four
masked restorations and normal reloads pass. No TX or calibrated dBm claim.

**Rejected engineering/statistics/RTT requests have no dispatcher entries:**
The [live61-entry UNI table](MT7925_UNI_DISPATCH.md) lacks0x32/0x46/0x5d, and
the verified dispatcher miss path emits`0xc00000bb`. Working MIB, power, CSI,
thermal and noise handlers match earlier pointers. No discovered command is
invoked. The buffer trace also places noise tag2 at the normal first-TLV offset.

**Short RTS/CTS/ACK transmit capability works:**
[two CCK1 controls](CONTROL_FRAME_TRANSMIT.md) each receive4/4 of all three
classes with exact16/10-byte headers and zero Duration. Probe controls3/4 and4/4
bracket both runs. Unique status PIDs handle control headers without sequence
fields. OFDM fails probes too, so is not a control-specific negative. No actual
peer handshake or ACK timing; all filters already open, all restorations/reloads pass.
Reverse CCK1 short frames still give0/4 for every class including both probes,
with20 matched statuses. No usable reverse CSI stimulus or RF-cause claim.

**MT7925 has a working multi-bin PHY histogram:**
[firmware-traced controls](MT7925_NOISE_HISTOGRAM.md) establish reset, timed
accumulation and stopped stability in two band0 register views. Four fresh boots
show channel6 concentrated in bins7–8, channel36 in bin0, then a return to the
channel6 distribution. Both views have identical totals but differing bins in
all eight windows. No calibrated noise floor or chain labels claimed. No TX or
UNI36 activation; only two traced volatile masks, all restorations/reloads pass.
The [four-view follow-up](MT7925_NOISE_HISTOGRAM.md#four-view-comparison-counter-indices-are-not-interchangeable-with-controls)
finds three active distributions with exactly equal totals under index0 control,
while the ordinary index1 bank stays zero. The extra timer view is concentrated
in bin6 on channel6, versus bins7–8 in the first timer view. Control index1 stays
disabled. Raw indices replace provisional RF-band labels; physical chain/stage
mapping is not yet established.
Additional1→11→6 controls change distributions within2.4GHz, with long-window
totals98,177/64,592/106,713 despite similar dwell times. Sample fractions are
not automatically full-dwell coverage; idle/busy gating remains to be tested.
The subsequent MCU-MIB crosscheck does not support a simple8µs-per-sample plus
1µs-per-primary-CCA-tick wall-time identity. Raw query windows/counters are kept;
coverage and physical power calibration remain unqualified, not fitted away.

**Per-rate power reports work, but MT7925 inactive-width rows retain history:**
[both source-defined report interfaces](TXPOWER_TABLE_STATE.md) answer26
controlled queries. Reversed order shows HT40 retaining26 from5GHz when current
HT20 is36 on2.4GHz, then retaining36 when returning to5GHz/20. These are table
states, not a current all-width RF power plan. MT7961 exposes distinct user,
EEPROM-derived and MAC curves. Existing USB reset also returns success on both;
it was already part of normal reload, not a newly tested recovery mechanism.
Follow-up [firmware and register provenance](TXPOWER_TABLE_STATE.md#mt7925-report-reads-hardware-not-just-a-retained-report-cache)
shows the report refreshing RAM from hardware registers `820e4140..820e42e7`.
All417 selected rate values agree with independent register reads before and
after three queries. Retained HT40 values therefore exist in the hardware table,
not just a stale report cache; their use for transmission remains unproven.
The query does internally write scratch/report RAM. No host power setter or
direct register write, and all verification/reload checks pass.

**Negative power offsets expose a two-stream observation boundary:**
[HT8 follow-up controls](PHY_TRANSMIT.md#negative-power-offsets-expose-a-two-stream-reception-boundary)
extend the earlier OFDM power mechanism to the currently weak channel6 link.
Both runs receive4/4 at−4,0/4 at−8, and4/4 after restoring zero; all TX statuses
track36/32/36/28/36 exactly. No positive offset, calibrated sensitivity or
original-degradation diagnosis is claimed. Raw own-packet RCPI is retained.

**CSI input is an internal timing report:** [the provenance trace](STATION_CSI.md#csi-input-comes-from-the-internal-timing-report-path)
follows packet-type bits31:27 through the firmware classifier and type4 branch
into the CSI entry. The gate is not parsing a normal RXD: its unnamed flags are
DW0 bits25/26 and subtype-shaped nibble DW1 bits25:22. Fixed live code/table
hashes match the retained image. No packet-buffer reads or new ranging claim;
this gives a precise next target for the unresolved data/control-frame gate.

**TX width and duration counters validated:** [bounded controls](TX_AIRTIME_COUNTERS.md)
map nine source-named UNI fields through live firmware/ROM. Short/long/short
reversals repeat303–304 additional MAC2PHY ticks for four packets, matching
the304us data-symbol difference.20/40 reversals move all four packets between
the corresponding width counters and reduce duration. Later wide reception
still fails while identical transmitter counts continue; this is not RF-success
proof. No direct consuming reads or enable writes; all radios reload normally.

**Ordinary Data and QoS Data transmission demonstrated:**
[bounded synthetic frame controls](DATA_FRAME_TRANSMIT.md) receive4/4 of each
class in two fresh MT7925→MT7961 HT8 runs. No association/IP/ACK/BA setup.
Reverse MT7961 CCK fails all classes including probe controls, so it cannot
yet supply the controlled data stimulus into MT7925 CSI. Both radios reload.

**HT40 payload transmission demonstrated:** [receive-path controls](PHY_TRANSMIT.md#ht40-payloads-received-before-the-extra-receive-path-command)
receive exact HT8/2SS/40MHz frames2/4 then4/4. Adding Linux's source-shaped
SET_RX_PATH command removes wide PD/MDRDY in12/12 windows across three runs,
while narrow after-controls stay4/4. Initialization dependence remains unresolved;
no descriptor/power change explains the breakthrough.5GHz tests fail their
narrow controls and cannot qualify wide behavior. Both radios reload normally.
Matched [stability controls](PHY_TRANSMIT.md#wide-reception-also-declines-without-a-receiver-command)
also lose wide reception without RX_PATH or high-rate errors. A quiet gap causes
the same loss; transmitter-only reload yields1/4 wide receipts, receiver-only
reload0/4 in small sequential trials. Do not attribute the failure solely to
RX_PATH. Additional exact wide receipts confirm the format, not robustness.
Source-traced receiver RAM fields now read back primary, secondary offset and
sniffer width through20/40-above/40-below/20 controls. Early HE40 still has no
exact payload, but3/4 then1/4 windows produce PD/MDRDY plus MAC FCS errors;
the receiver's firmware state remains40-above. Software state is not RF proof.

**Ignored sniffer FCS byte explained in firmware:** [the tag1 trace](ERROR_FRAME_CAPTURE.md#firmware-explains-the-ignored-sniffer-error-byte)
reads channel fields but never TLV+12, the advertised drop-error byte. A bounded
live pointer/code-hash check matches the pinned firmware; only hashes/pointers
are exported. This complements the verified MAC-filter workaround for maintainers.

**Wide TX has an independent secondary-channel RF signature:**
[fixed-secondary width reversals](PHY_TRANSMIT.md#secondary-channel-detections-follow-the-tx-bandwidth-setting)
produce OFDM detections in16/16 wide windows and0/16 narrow windows, with the
receiver held on channel10/20MHz. Exact primary-channel controls are4/4 before
and after both runs. No wide payload is decoded; a40MHz-configured receiver's
earlier zero-PD result is not global absence of RF emission. All controls restored.

**Read-only thermal telemetry:** [MT7925 UNI35 analog-die queries](THERMAL_TELEMETRY.md)
return45/45°C around raw ADC68, then45/47°C with the strict reproducer. The
existing MT7961 path returns32°C. Digital-die sensor0 gives no result, including
bounded two-endpoint polling between positive analog controls; sensor absence
is not inferred. No protection/throttle/power changes and all reloads pass.

**NAV, per-subchannel ED and idle-slot measurements:** [source-selected UNI queries](SUBCHANNEL_MEASUREMENTS.md)
expose live NAV time and multiple ED values at80/160MHz. Source/ROM mapping
corrects the earlier tentative names:17 primary CCA,18 secondary CCA,19 CCA+NAV+TX.
Width-invalid secondary counters resemble100% busy and must be excluded;
eight ED indices are not yet verified absolute channel labels. The16-bit idle
counter works at short cadence and saturates on long dwells, explaining its
old constant65535 result. No TX, direct counter reads or production-default changes.

**MT7925 MIB addresses independently resolved:** [the UNI22-to-ROM trace](MT7925_MIB.md)
maps offset0 to full32-bit `0x820ed7f0` and offset2 to`0x820ed9a8`, matching
related MT7992 FCS/MPDU names. Alternating passive reader order proves that raw
reads consume samples before firmware can accumulate them: direct-first MPDU
samples105/97/97 leave UNI deltas0, whereas firmware-first deltas101/114/111
match decoded frames. No counter-enable writes, no TX, normal reload passes.
The vendor header's per-rate names do not match observed1SS CCK/OFDM traffic;
do not promote that map into per-rate telemetry. Defaults remain UNI-only.

**Failed-frame PHY capture unlocked:** [FCS filter controls](ERROR_FRAME_CAPTURE.md)
show that clearing only MAC RFCR bit1 exposes CRC-failed HT15/2SS metadata;
sniffer drop_err0 alone does not. A factorial test and two same-rate reversals
separate the controls, retaining only anonymous diagnostics. The source-named
PHY FCS field remains1 across multiple failed frames, so it must not be used
as an accumulating error count under the current enable recipe. Original
filter/counter bits and both firmware reloads are verified; defaults unchanged.
The distinct [MAC FCS counter](ERROR_FRAME_CAPTURE.md) now passes read-clear
single-packet and two/four-packet batch controls, including with normal error
filters and no PHY counter-enable writes. It counts errors hidden from USB;
background errors, shared read-clear ownership and denominator limits remain.

**New GI/LDPC transmit controls:** [MT7925 fixed-rate ROM mapping](FIXED_RATE_TABLE.md)
locates GI and LDPC bits, and the second dongle independently receives HT8 with
short GI and with LDPC coding. A corrected UNI40 request also works, but exposes
post-write validation and an apparently uninitialized configuration byte; the
on-air probes retain our deterministic direct-table path.
The same mapping now produces independently received HE GI1/GI2 and LDPC.
GI-only HE requests failed; paired GI/LTF settings work. LTF was initially
unverified because full-group5 LTF metadata was unavailable.
Changing only LTF0→1 also unlocks **HE STBC**, independently received3/4 then2/4,
with HE2SS controls4/4 before/after both runs. DCM remains unreceived; no gain claim.

**Validated HE-LTF readout and a maintainer pointer:** enabling the already tested
Group5 report and following the vendor header yields LTF codes0/1/2 matching
**48/48** independently received controlled frames. The source-derived location
used by current MT7921's reassigned radiotap pointer instead mostly yields3.
[HE_LTF_RX_ORIGIN](HE_LTF_RX_ORIGIN.md) records current upstream source pointers,
the small reproducer and sanitized evidence. No Linux implementation or external
maintainer message was sent; this is the concrete documentation gift.

**HE extended-range SU format received:** [HE-ER TX controls](PHY_TRANSMIT.md)
yield one independent exact receipt in each of two fresh runs, with the second
also validating LTF1 via Group5. One-stream controls remain weak and ER/DCM
has no receipts; this is format evidence, not a range or reliability claim.

**New STBC transmit format:** [MT7925 HT0/STBC](PHY_TRANSMIT.md) is independently
received as NSS1/NSTS2/STBC=true, four exact frames and then one on a fresh repeat.
HT controls bracket both trials; the degraded/variable link prevents a gain claim.
The source-mapped rate is4480, not the older chip's different STBC encoding.

**New TX timing telemetry:** [MT7925 TX-status fields](TX_STATUS_TIMING.md) expose
live timestamp/front-time/delay values. Across48 no-ACK packets at five rates
and two lengths, a1µs/32µs clock model plus nominal packet airtime leaves a
per-boot offset with29–32µs spread. This is a promising delay observation, not
yet calibrated contention time or interference attribution.
Two subsequent eight-frame burst controls receive8/8 before/during/after;
every next front-time equals previous front+delay. Since all host submissions
finish in1.3–1.6ms while service spans17–22ms, these fields do not include all
earlier FIFO waiting. The evidence supports a serial service-boundary reading.

**Spatial-reuse queries:** [UNI25 capability/indicator replies](SPATIAL_REUSE.md)
work on MT7925 through unsolicited sequence-zero events. Two fresh-band controls
return stable configuration flags, but all eight counters remain zero despite
normal reception. This adds a query surface, not yet OBSS activity inference.
Following the getter into ROM subsequently unlocked three **live read-clear RMAC
counters**: direct inter-BSS-named values match decoded frame counts in five ch36
windows while the separate software accumulator stays zero. BSS attribution is
not yet qualified; the useful hardware source and its read-clear hazard are now
documented and probed without direct writes.

**Latched CN/EVM fields:** [a single MT7961 PHY register](PHY_SIGNAL_FIELDS.md)
updates during controlled two-stream HT reception in two fresh runs. Its values
then persist across CCK packets, so they must not be attached blindly to each
received frame. Units and physical interpretation remain unvalidated.

**Station radar detector:** [MT7925 UNI19 STOP/START/STOP](RADAR_DETECTOR.md)
returns success after correcting quiet-endpoint receive throttling. Three short
post-START windows yield no pulse reports. Independent ROM mapping now confirms
MT7925 mode0→5→0 and a512-byte ring at00416000, with169 normal OFDM frames
received during arming; its producer remains idle and reload restores all reads.
MT7961 CE8F stays silent on USB, but a later traced RAM-state read follows
STOP/START/STOP as0/0x101/0x100 and reload restores0, proving handler execution.
Its on-chip capture buffer is allocated. Follow-up ROM-derived reads now confirm
hardware detector mode0→5→0 and a512-byte capture ring installed. The producer
does not advance in the quiet trial; no usable pulse measurement is claimed.

**Timing/ranging frontier:** [RTT capability queries](TIMING_MEASUREMENTS.md)
are explicitly refused on both builds. MT7925 nevertheless advertises a ToA
engine in its LOCATION capability, unlike MT7961. This is a static capability
lead, not an exposed timestamp stream or a working ranging implementation.

**New MT7925 route:** [loaded plaintext code is USB-readable](MT7925_LOADED_FIRMWARE.md)
despite the encrypted container. Repeated entry reads establish RV32 startup, and
a bounded instruction-table read supports an experimental Andes-style expansion.
This does not establish a complete decoder.
Follow-up ROM startup establishes MT7925 GP `0x02212800`, corroborated by live
registration-table pointers; decryption occurs between the pre-start and running
read controls. Its 30-slot dispatcher is now identified as UNI 0x33 beamforming:
[PFMU tag and profile-data reads work](BEAMFORMING_PROFILES.md), with correctly
predicted unsolicited sequence-zero events. This is not yet usable CSI.

**CSI readout unlocked:** [MT7925 station UNI 0x4a](STATION_CSI.md) now yields
live I/Q reports after tag2/index0/value0x20 frame selection on band0. Two runs
validate 114/116 reports with 64 I and 64 Q values each, distinct payloads and
paired RX indices0/1. A firmware-specific 36-byte zero tail is explicitly checked.
No sample arrays or transmitter identities are retained, and calibration/topology
interpretation remains future work. Band1 stays silent in the current setup.

The initial [MT7925 station UNI 0x4a control lead](STATION_CSI.md)
acknowledges stop/start and maximum-chain tags with status zero. Both band
selectors were tested; no CSI sample events were seen. MT7961's legacy CE 0x4c
route returns the source-defined command-not-found event. No-ACK silence and
transfer-limited windows are explicitly separated from negative results.
Follow-up loaded-code tracing identifies both the control and report constructors.
ROM-derived MMIO controls now show that stop/start/stop really changes the selected
band's hardware at `0x820e5060` / `0x820f5060`, leaving the other band unchanged.
Reload restores the baseline. Zero USB RAM snapshots do not negate that result;
At that checkpoint CSI events were still absent; the nonzero frame selector
subsequently unlocked the readout above. No calibration capability is claimed.

**Major static-analysis correction:** [NDS32, not Xtensa](NDS32_RECON.md).
Startup exposes the EX9 table, and a GP candidate recovers meaningful string
references. A later [table-order correction](COMMAND_TABLES.md) explains the
apparent internal-tag mismatch: the old scanner read handler-then-next-CID instead
of CID-then-handler. Corrected mappings match independent CSI/BF/RDD controls.

## ICAP: capture start changes state, node-0 completion not observed

`research/icap_capture_probe.py` sends a bounded EXT 0x04 SET with action 1,
function 11, and the 80-byte capture union documented in the pinned station
`wlan_oid.h` / `wlan_oid.c` references in STATION_TESTMODE. Explicit settings:

- Trigger 1, ring 0, free-run event 0, candidate node 0.
- Capture length and stop cycles each 64 or 256, never the zero/default size.
- Architecture 0 (on-chip), PHY/band/BW 0, all source/EMI addresses zero.
- No capture-to-host-memory/EMI configuration and no transmitter command.
- Stop uses the same request with trigger 0, then full firmware reload.

**Node 0 is only a candidate**, from the QA legacy default; its meaning on MT7961
is not established. The phone-driver helper normally chooses architecture 1;
that streaming setup is deliberately not transplanted onto a USB device.

Three runs, all MT7961 on the existing pinned firmware:

| Setup | Requested samples | Status before | Three post-start status replies | Recovery |
|---|---:|---:|---|---|
| ICAP mode only | 256 | done=1 | done=0, 0, 0 | reset/alive pass |
| Known RX-path activation before ICAP entry | 256 | done=1 | done=0, 0, 0 | reset/alive pass |
| Explicit ICAP channel preparation after entry | 64 | done=1 | done=0, 0, 0 | reset/alive pass |

Explicit channel preparation is band 0, RX mask `3 << 16`, frequency 5180000 kHz,
20 MHz and CE test function 1/value 13 (`CH_SWITCH_FOR_ICAP`). This is not TX-start.
Each status collection is 0.3 seconds; these runs establish lack of completion in
the tested short window, not permanent inability to complete. No samples were
retrieved. Requested retrieval was skipped unless completion was observed.

The retrieval builder is offline-tested only: function 17, address 0, increment 4,
bank 1, explicit one-KiB bank size, chain/IQ selector 0. That bounded shape must be
validated against an actual completed capture before claiming usable IQ. Summaries
emit only count/range/cardinality, never sample arrays. Raw IQ is not saved.

[Sanitized evidence](../research/evidence/icap-capture-2026-09-05.json).

```sh
python research/icap_capture_probe.py
python research/icap_capture_probe.py --prepare-rx --retrieve
python research/icap_capture_probe.py --samples 64 --icap-channel --retrieve
```

## MT7925 engineering queries: separate interface, same nonzero status

UNI 0x46 tag 0, length 92, GET_AT_ENG action 4, selectors 0/46/50 each returned
a 32-byte command-result reply echoing CID 0x46 with status `0xc00000bb` after
an idle test-mode entry attempt. No version/RSSI scalar was returned. Each query
used special UNI option 0x02 and fresh firmware boot/reset. All cleanup checks passed.

This follows the pinned vendor bridge's GET_AT=2 to GET_AT_ENG=4 mapping; it is
not a repeat of UNI 0x32 receive statistics. Mode entry itself was not established
on MT7925. No conclusion about different firmware images or all possible commands.
[Evidence](../research/evidence/mt7925-engineering-2026-09-05.json).

```sh
python research/station_testmode_probe.py --chip mt7925 --test-mode --engineering --selector 0 --selector 46 --selector 50
```

## Active next leads

- ICAP: establish capture node/clock prerequisites or a different supported on-chip
  request path; do not keep repeating the same incomplete node-0 request.
- Legacy CE `ACCESS_RX_STAT` 0xc8: source identifies its separate eight-byte query
  and event 0x45. Investigate richer RX error/signal statistics with the live sampler.
- Isolate RX-chain signal-word packing and compare controlled traffic/attenuation
  while preserving aggregate-vs-packet distinctions.
- Continue bounded independently observed transmit capabilities where source-backed
  descriptor fields offer a useful new measurement control.

## Legacy CE 0xc8 exposes a richer live block, with read side effects

**Later correction:** the initial eight-byte request below omitted an explicit
band word read by this pinned firmware. The current probe sends12 bytes and calls
the reply's third word `reported_band_u32`, not status. See the
[dispatcher trace and corrected request](FREQUENCY_OFFSET.md#complete-ce-0xc8-request-and-the-apparent-status-correction).
The historical observations below preserve the original experiment; values2/100
are now identified as invalid band arguments, not status codes.

`research/legacy_rx_stats_probe.py` queries CE 0xc8 with two little-endian u32s:
sequence 1..5 and count 72. Normal mode and activated RF RX both return matched
EID 0x45 / 300-byte bodies. Normal-mode statistics stay zero; live RX changes
many fields. Three fresh-boot runs established the reply shape; the final run
added RX-stop controls. All reload/alive checks passed. No transmission was used.

The pinned public header expects eight header bytes and big-endian statistics.
**That interpretation does not fit this firmware.** Observed replies fit a
12-byte header followed by 72 little-endian u32 words. Header words 0/1 echo
sequence/count; word 2 is initially 100 in normal mode and 2 in RF RX, then 0.
Its meaning is not established (`candidate_status_u32` in evidence). Initial
responses contain no statistics; later RF RX responses populate the block.

Interpreting the subsequent words with source-derived field positions yields
coherent counters and sign-extended signal values. Strong cross-checks:

| Candidate index / source name | First stopped query | Second stopped query |
|---|---:|---:|
| 0 / MAC_FCS_Err | 16 | 0 |
| 1 / MAC_Mdrdy | 125 | 0 |
| 3 / FCSErr_OFDM | 59 | 59 |
| 5 / OFDM_PD | 526 | 526 |
| 15 / PhyMdrdyOFDM | 461 | 461 |
| 16 / DriverRxCount | 353 | 353 |
| 17,18 / RCPI | 30,27 | 30,27 |
| 20,21 / RSSI signed candidates | -93,-95 | -93,-95 |
| 49 / SNR0 | 17 | 17 |

Index 16 exactly matches scalar selector 34's stopped value (353). Index 0
matches scalar selector 35 immediately before the first stopped query (16);
selector 35 reads 0 after the richer queries. Thus **the richer query drains at
least some counters**, while other fields are cumulative or last-sample values.
Do not mix this command into acquisition without accounting for its read effects.
No calibrated RSSI/SNR/frequency-offset units, non-Wi-Fi discrimination, packet
attribution, or validity of every source-derived field name is claimed.

Follow-up: [frequency-offset provenance](FREQUENCY_OFFSET.md) now traces word19's
signed20 assembly and integer conversion, plus word49's direct six-bit SNR export.
Two fresh boots exactly match nonzero cached-vector inputs to returned values;
a third zero-cache control establishes an important limit. Subsequent dispatcher
tracing corrected the apparent-status interpretation and incomplete request.

[Sanitized evidence](../research/evidence/legacy-rx-stats-2026-09-05.json) retains
the candidate 66-word prefix and control observations. The tool retains both
layout hypotheses; the candidate interpretation does not silently replace the
reference format. Validation checkpoint: 618 Python tests passed.

## Individual RX masks identify signal-word byte positions

The existing paired-radio receiver probe was repeated with masks 1 and 2. Each
run submitted 12 monitor controls and 36 synthetic no-ACK probes at 50 ms spacing;
monitor controls decoded 11/12 and 12/12 respectively. RX counters changed with
either single-chain mask and froze after stop. Both radios reloaded/alive afterward.

| RX mask | Selector 46 byte 0, signed | Selector 46 byte 1, signed | Selector 50 |
|---|---|---|---|
| 1 | changes: -94,-93,-92 | constant -109 | changes |
| 2 | constant -109 | changes: -95,-96,-89 | fixed 0x80804040 |

This supports selector 46's low two bytes being chain-0 and chain-1 signal
readouts, respectively, with -109 a disabled-chain value in these runs. It does
not calibrate their RF units or prove -109 is a universal sentinel. Selector 50
does **not** behave like a whole-radio signal readout: it remains at the same word
with only chain 1 active. Treat it as chain-dependent until firmware decoding
establishes more. The aggregate signal does not show a reliable 0/-16/0 probe
attenuation pattern; ambient traffic still dominates last-sample observations.

[Sanitized chain-isolation evidence](../research/evidence/testmode-rx-chains-2026-09-05.json).

## ICAP: firmware-backed event-gate and node follow-up

Corrected disassembly identifies the actual ICAP dispatcher at 0x00933d86:
mode checks, action 1, functions 11/12/17 and the expected request length agree
with the working command. Start routes through 0x00964d5c → 0x0095c678 →
0x0095c630. In the chip routine at 0x0096c562, event -1 clears register bit 19
instead of enabling an event selector. Thus the earlier label “free-run” for
event 0 was not established by the firmware. The tool now labels the alternative
`--no-event-gate`, not “working free-run.”

Two further bounded 64-requested-sample, on-chip-only runs with explicit channel
preparation used event 0xffffffff: first node 0, then node 0x49. The latter is the
pinned QA mapping for node 8, also selected by the original
[MtkICAPtool](https://github.com/MtkWifiRev/MtkICAPtool/tree/d829596a88e66382b3afe0f6be1de0c15ff88037)
on a different chip; it remains a candidate here. Both runs again gave pre-start
done=1, then 0/0/0. No data retrieval was requested and reset/alive checks passed.
[Evidence](../research/evidence/icap-trigger-node-2026-09-05.json).

The start/status path calls through ROM-table words at 0x00823000 and 0x00823014.
Their actual targets are a new read-only lead. Sample length remains a requested
software parameter, not proof of a hardware-enforced ADC sample ceiling; captures
are additionally bounded by ring-off, on-chip storage and short stop/reset windows.

The bounded USB read check succeeded: 0x00915000 returns 0x15090046 and
0x0096c7bc returns 0x00000c46, matching known image bytes. ROM-table words
0x00823000 and 0x00823014 return **0x008322da** and **0x00832344**, respectively.
Both targets lie in the expected ROM range. Only four words were read; firmware
reload/alive checks passed. This establishes a viable targeted-ROM-inspection
route, not permission or need to dump unrelated memory. Checkpoint: 620 tests pass.

## Histogram compact setter: corrected layout is not enough

### Later static correction: legacy CE ICAP setters are absent

The public `rftest.h` names CE1 SET selectors80/81/82/83/84 as ICAP
content/mode/start/size/trigger offset, and112 as ICAP ring control. These names
do not imply implementation on this pinned MT7961 firmware. SET dispatch at
`0x00931b2c` takes the selector's low byte. Selectors80..84 (also85) follow
`0x00931c36 → 0x00931c44 → 0x00931c5e → 0x00931c6e → 0x00931c76`, then the
default EX9 jump at`0x00931c7e` directly to the return at`0x00933110`.
Selector112 similarly defaults via`0x00931d42..0x00931d52`. Neither route
applies capture configuration. No live writes were needed to establish this.
This closes the proposed legacy-setter alternative for this image, not the
separately implemented EXT04 functions11/12/17 or other firmware builds.

The actual IPI dispatcher is 0x009616d0, not the same-numbered internal table
tag previously used as a shortcut. Its SET path passes the payload start to
`rdmSetIpiHist` at 0x00961618. That function consumes bytes 0/1 as type/value,
with PHY and band zero, then calls 0x0096bd20. The earlier AP-shaped request
placed value in byte 2. Thus an important request-layout assumption was wrong.

`research/ipi_compact_probe.py` compares the old and compact layouts across fresh
boots, with type 0/value 1 and three 0.5-second-spaced ALL queries. Both normal
monitor mode and the activated RF receiver were tested. All bins and free-run
values remained zero for both layouts. RF-mode SET replies echoed CID 0xa3 and
status 0, so no dispatch refusal was observed there. All cleanup checks passed.
This corrects the layout without claiming a working histogram or noise floor.
[Sanitized evidence](../research/evidence/ipi-compact-2026-09-05.json).

The low-level routine uses abstract register-field access callbacks with selector
keys 0x260000/1/2; the read path uses keys based on 0x13004 shifted by five.
Resolving those callbacks is a better next step than repeating initialization.

## Runtime data relocation and shared field access

The 256-byte ICAP ROM window (local-only SHA-256
`b109e321be83821b4bd7fe0bb4a5c183250b3ce727ed1f7468324f38dfa006ae`)
decodes as NDS32. Start at 0x008322da writes field key 0x5a0013 through a
GP-relative callback; status at 0x00832344 reads the same field. Both use the
same field-access family as IPI. No ROM bytes are included in the repository.

The first attempt to read the callbacks used the file-layout GP surrogate and
returned all ones. A CE 0xc0 QUERY control at known code address 0x00915000
raised McuError; cleanup passed, and that route was not used to infer memory.
USB reads of known data words instead exposed **runtime relocation by +0x44c**.
Startup disassembly and four live table/string-word controls agree. All extracted
regions still exactly match the pinned image; see [NDS32_RECON](NDS32_RECON.md).

Corrected **runtime GP 0x02003000** resolves the callbacks:

| GP offset | Live slot | Target |
|---|---|---|
| 0x10800 | 0x02013800 | 0x00826c7e |
| 0x10808 | 0x02013808 | 0x00826ca2 |
| 0x1080c | 0x0201380c | 0x00826b70 |

[Sanitized relocation/pointer evidence](../research/evidence/firmware-relocation-2026-09-05.json).
These are pointer reads, not host function calls. Both device checks and full
reload cleanup passed. Next: decode this narrowly scoped ROM accessor family
to resolve the field keys to actual register locations.

## Concrete IPI and ICAP hardware field maps recovered

Following the shared ROM accessors resolves the actual registers and bit ranges;
see [FIRMWARE_FIELD_MAPS](FIRMWARE_FIELD_MAPS.md). The IPI GET path reads twelve
23-bit values at 0x830af0a8 through 0x830af0d4, not the older sibling-chip address.
ICAP active is bit 1 of 0x80021090. Field keys index a ROM description; their low
five bits are not bit positions. An independent bounded table resolver and unit
tests reproduce the mappings without redistributing ROM bytes.

Separate live register checks preserve the previous outcomes but narrow them:
IPI initialization still leaves its resolved control and counters reading zero,
with both request layouts in normal/RF RX. ICAP control changes 0x400 → 0x4f3
on start and 0x4f3 → 0x4f1 on stop, exactly matching its active/status semantics.
Three short post-start polls remain incomplete. All firmware reloads pass.
[Command/register evidence](../research/evidence/field-register-controls-2026-09-05.json).
Next: trace capture setup and IPI access gating from these concrete locations.

Follow-up controls confirm the PHY USB window changes as predicted, while one
exact reversible IPI initialization write still reads back zero. A packed ICAP
node predicts both mux and stop-count changes correctly but still does not finish.
Starting RX after ICAP mode does not resolve that in this run. Details and dated
evidence are in [the field-map activation section](FIRMWARE_FIELD_MAPS.md#activation-controls-and-remaining-limits).
These narrow the hardware questions without promoting idle registers to working
measurements. Next bounded surface: spatial-stream and bandwidth transmit controls
with independent second-radio decoding; keep capture-clock/legacy-route leads open.

## Two-stream transmit capability and an RF-performance caveat

MT7925 transmitted independently decoded HT MCS8, VHT MCS0 and HE-SU MCS0 at
two streams/20 MHz: 6/6 each, then 4/4 each with fresh per-run payload nonces.
This establishes an HE transmit case beyond the earlier one-stream negative.
However one-stream controls are now weak/absent and MT7961 TX has no independent
decode. Normal-mode exit and forced WFSYS reset/reload did not restore that
control; alive checks alone are insufficient RF recovery evidence. See
[PHY_TRANSMIT](PHY_TRANSMIT.md#two-stream-follow-up-2026-09-05-utc) for the exact
counts and limitations. Wider-band TX tests are deferred until controls recover.
Next independent lead: whether bounded live instruction reads can expose the
MT7925's loaded code despite its encrypted firmware container.

The public-source revision remains Motorola gen4m `8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`;
no vendor implementation/header or firmware blob is included in this repository.

First checkpoint: 615 Python tests passed; targeted ruff format/lint, local
documentation/JSON checks, and whitespace checks passed. Hardware cleanup passed
for all runs above. Investigation continues; this is not a release qualification.
