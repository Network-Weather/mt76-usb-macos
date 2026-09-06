# MT7925 signed PHY comparison inputs in normal mode

**A new raw PHY input changes during normal2.4GHz reception without enabling
CSI or test mode.** Firmware compares two signed bytes with two signed
thresholds. This is not calibrated RSSI, a per-packet measurement, or an
interference verdict. Its5GHz freshness control fails: input0 holds despite
normal reception, and input1 stays−127 on both channels.

Device0846:9072, RAM build20260813113118, SHA256
`23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`.
Two fresh receive-only boots on2026-09-06 UTC use channel6→36→6,20MHz,
ten100ms windows per dwell. No threshold/selector changes, TX, CSI activation,
RF-test mode, NVM writes or ambient identities. Both normal reloads pass.

## Exact source chain

The pinned loaded-image getter and consumer independently establish these
band0 fields; addresses are not transferred from another chip by analogy.

| Role | Location | Traced operation |
| --- | --- | --- |
| Input0 | `830a6090[7:0]` | Getter`e005a338`, output pointer0 |
| Input1 | `830a6094[7:0]` | Same getter, output pointer1 |
| Threshold0 | `8308838c[31:24]` | Getter`e005a36e` |
| Threshold1 | `8308838c[23:16]` | Same getter, separate register read |
| Selector | `8308863c[21:18]` | Getter`e005a406` |

The input getter accepts band0/1; band1 selects bits15:8 of the **same two input
registers**, not a guessed+0x10000 bank. Band1 is not sampled here. Threshold and
selector getters instead use band1 siblings+0x10000. The two inputs are not
independently identified as antenna0/1 or in-band/wideband power.

Threshold getter substitutes **−51 for each zero threshold byte**; a zero input
does not receive this fallback. Consumer`e0078f2e` reads thresholds, then selector,
and requires **selector exactly3**. Other values write false to the output but
return an error-class result: report unavailable, not valid false detection.

At`e0078f62`, the consumer reads the inputs, then uses signed byte loads and
comparisons at`e0078f66..7a`: output is true if **either input is greater than or
equal to its corresponding effective threshold**. It returns its prior success
result on this path. The probe reproduces that formula in software; it does not
invoke the internal helper or claim to read an actual hardware CCA flag.
Caller`e0034a58` consumes this boolean and calls further control helpers; those
control effects are not activated or interpreted here.

The threshold address also occurs in the older firmware's
[histogram decision consumer](LEGACY_PHY_HISTOGRAM.md#firmwares-own-histogram-interpretation).
That corroborates a decision-threshold role, not a physical power calibration or
permission to transfer the older input register layout.

## Live controls and limitations

Each dwell has20 snapshots, before/after ten receive windows. Counts below are
ordinary good-FCS records, not packets attributed to a PHY-register sample.

| Boot / channel | Good records | Input0 observed range | Input1 | Threshold pair | Selector3 snapshots /20 |
| --- | ---: | --- | --- | --- | ---: |
| First /6 | 53 | −104…−63 | −127 | −51/−51 | 16 |
| First /36 | 116 | holds−100 | −127 | −56/−56 | 19 |
| First /6 return | 53 | −100…−41 | −127 | −51/−51 | 15 |
| Repeat /6 | 61 | −104…−46 | −127 | −51/−51 | 16 |
| Repeat /36 | 110 | holds−77 | −127 | −56/−56 | 20 |
| Repeat /6 return | 50 | −104…−63 | −127 | −51/−51 | 13 |

Input0 changes between before/after samples in39/40 channel6 windows and
0/20 channel36 windows. Thresholds reverse consistently with tuning. Selector
values3/7/8/9 occur;21 non3 snapshots remain unavailable. Of99 selector3
snapshots, the software comparison is true three times. This is not3% occupancy
or a detection probability: selection, interval, non-atomic reads and unknown
hardware validity prevent that interpretation.

The repeat's channel36 value−77 equals the preceding channel6 ending value and
the first returning channel6 value. The first boot changes to−100 around the
retune before holding. **Neither5GHz dwell establishes fresh signal sampling**
despite226 good records there. Constant input1−127 is not a calibrated noise
floor, a proven invalid sentinel, or evidence an antenna is broken.

Four sequential USB reads are not an atomic snapshot. Host order also differs
from the internal consumer's threshold→selector→input order. Selector3 at the
final read cannot prove earlier input validity. Read-clear/latched/continuous
semantics and exact update eligibility remain unqualified; no background reset
or measurement activation is attempted.

## Reproducer and retained evidence

[`mt7925_phy_compare_probe.py`](../research/mt7925_phy_compare_probe.py) verifies
the pinned image, three exact instruction windows and the4096-byte Andes table
before sampling only the four listed registers. Live code hashes match in both
boots. RX windows are bounded by100ms/256 attempts; no transfer ceiling is hit.
The device is normally reloaded and released afterward.

[Sanitized evidence](../research/evidence/mt7925-phy-comparison-2026-09-06.json)
includes all observed input pairs, per-window good counts, first/last values,
selector availability, hashes and cleanup. Twelve synthetic tests pin signed
comparisons, equality, fallback semantics, selector gating and register scope.
Production Python/C APIs are unchanged. Next: trace input update/validity,
not assign dBm or interference labels from numerical plausibility.
