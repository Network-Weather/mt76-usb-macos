# ALFA calibration enablement check, 2026-09-08

The suspected missing step is real: `set_eeprom()` sends the existing
`EFUSE_BUFFER_MODE` command, which tells firmware to use factory calibration.
It does **not** program the physical efuses. The upstream reference is
`mt7921/mcu.c:mt7921_mcu_set_eeprom` at `c5a3bd91`; this checkout's normal Python
and C bring-up already execute it. `MT_SWDEF_MODE=0` is written before firmware
download, not used as a general runtime recovery command.

**Result: neither reissuing calibration nor restoring monitor/sniffer settings
recovers the impaired high-band receiver.** A traced ordinary bring-up also
executes both required steps successfully without restoring reception. The
[PR32 merge hold](R32_MERGE_CHECK.md) remains; the result rules out a simply
omitted enablement call, not ineffective/cached calibration or retained PHY state.

[Redacted evidence](../research/evidence/r32-calibration-reapply-2026-09-08.json)
contains the five retained runs, timestamps and diagnostic source hash. No new
physical power cycle, TX, physical efuse write or arbitrary register experiment
occurred. Production source remains `cbf01c1`; changes add a research diagnostic,
offline tests and documentation, not an automatic-recovery implementation.

## Separate interventions in the retained state

One process owns ALFA, a second owns the Netgear sham reference. Each sweep
requests channels1/36/53 at20MHz, discards a bounded250ms transition interval,
then listens3s per channel. There is also a3s measurement immediately after the
intervention on channel53 **without retuning**. No firmware reload occurs in
these four runs. They overlap but their per-channel dwells are not synchronized.

| ALFA intervention | Before frames ch1/ch36/ch53 | Immediately after, ch53 | After sweep ch1/ch36/ch53 |
| --- | --- | ---: | --- |
| Factory-calibration load |270 /0 /1|0|238 /0 /0|
| Monitor filters + sniffer enable |272 /0 /0|1|348 /0 /0|

Neither intervention restores high-band beacons. Netgear remains healthy:
after-sweep counts334/194/516 in the first paired run and377/234/367 in the
second, with management/beacon traffic on all bands. ALFA command waits discard
only1/0 ordinary frames and report no stale events; there is no evidence here
that large command-wait frame losses explain its silent high-band dwells.

The calibration request bytes are `00 01 00 00`. Its matched response arrives
in2.554ms: declared length44, body length8. The recorded SHA-256 exactly matches
the little-endian words `[0x21, 0]`. This establishes the observed zero-result
reply, **not that the firmware successfully recalibrated the RF path**. The
upstream generic response parser likewise does not establish effective RF health.

Reproduce the bounded retained-state check only after this driver's ordinary
capture process has released the device:

```sh
<project-python> research/efuse_reapply_probe.py --usb-id 0e8d:7961 \
  --action efuse --acknowledge-retained-state
<project-python> research/efuse_reapply_probe.py --usb-id 0846:9072 \
  --action sham --acknowledge-retained-state
```

The separate ALFA `--action monitor` uses existing monitor/sniffer helpers.
Exit0 means the diagnostic completed, not that reception recovered. This is
not public session warm adoption; the tool refuses absent firmware or missing
EP4 event routing, never silently brings the device up, and leaves the tested
runtime configuration available for further diagnosis after closing USB.

## Traced ordinary bring-up

After both comparisons, one standard ALFA `bringup()` was instrumented at the
existing `wr()` and `mcu_cmd_word()` boundaries; no new command or register value
was introduced. The trace preserves:

- Normal-mode pre-download write: requested0, immediate readback0.
- Bring-up calibration request: same four bytes, matched8-byte `[0x21,0]` result.
- Monitor filters, sniffer enable and20MHz tuning then execute normally.
- Post-bring-up frames on1/36/53:311/0/1. No high-band beacons; aliveness passes.

An initial diagnostic preflight had refused the ALFA because `MT_SWDEF_MODE`
read `0x820f3000`, unlike Netgear's0. That check was an over-strong assumption:
the trace proves the0 write lands before download, while the register reads
`0x820f3000` again by the end of bring-up. Its runtime meaning is not established.
The probe now records rather than interprets that post-boot value. **Do not write
it back to0 on a running device as a speculative repair.** The refused attempt
made no MCU/tune/write changes; its negative result is retained in the evidence.

## Next discriminating step

A physically recovered ALFA is needed for a matched sequence: passive-only
bring-up/retuning, then session/query-only, then a minimal legacy histogram
guard without extra diagnostic reads. Measure high-band beacons after each step,
with Netgear as an independent reference, and stop at the first degradation.
Do not repeat the full experiment batch or turn repeated zero-result replies
into a recovery claim. Calibration-table edits or new RF-test commands are not
justified by this result. No release or merge was performed.
