# MT7961 PHY diagnostic CN/EVM fields

For the newly resolved normal-mode in-band/wideband register and frame-associated
FAGC fields, see [in-band / wideband signal provenance](INBAND_WIDEBAND_SIGNAL.md).

The firmware's diagnostic output exposes a **nine-bit CN field and two EVM
bytes** from one PHY register. This is a new raw observation surface, not yet
calibrated channel quality, per-packet EVM, or a validated condition-number scale.
The labels below are the firmware's names; units and validity rules remain open.

## Pinned firmware mapping

In the MT7961 image pinned in [PHY_RX_COUNTERS](PHY_RX_COUNTERS.md), diagnostic
`0x00962578..0x009625c8` calls `0x00942d38` with band, a CN output pointer,
an EVM output pointer and count2. That wrapper calls `0x00936fda`.
The low-level routine reads **`0x83086088`** for band0 (`0x83096088` for band1,
not tested), then extracts:

| Output | Register field | Firmware stores |
|---|---|---|
| CN | bits15:7, unsigned9 | halfword at CN output+0 |
| EvmRx0 | bits31:24 | byte at EVM output+0 |
| EvmRx1 | bits23:16 | byte at EVM output+1 |

The order of EVM bytes is reversed relative to a low-to-high byte array.
CN extraction uses32-bit `<<16` then `>>23`; the discarded high bits matter.
The diagnostic prints CN and EVM as hexadecimal; that does not define signedness,
dB/percent units, normalization, chain calibration, or instantaneous freshness.
Only the fixed register is exposed by `research/evm_cn_probe.py`.

## Passive controls

`python research/evm_cn_probe.py --channel 1` (or36/149) performs ten50ms
passive windows, samples the register after each, and normally reloads firmware.
No transmitter, explicit receiver-register write, RF-test mode, or calibration
command is used. Only aggregate good-FCS PHY counts and register fields leave
the receive loop; ambient identities and frame contents are not exported.

All three fresh boots initially read `0x8181ff80`: CN511, EVM129/129. On channel1,
the second window included one decoded OFDM frame and28 CCK frames; the register
changed to `0x2120ff80` (CN511, EVM33/32). It then held that value through the
remaining windows, including CCK-only traffic and empty windows. This is evidence
of a **latched, PHY-dependent observation**, not an always-fresh sample for every
received frame. The temporal co-occurrence does not uniquely attribute it to that
one frame. Channel36/149 received no frames and retained the initial word.

`0x8181ff80` is an observed reset-like value, **not a proved universal invalid
sentinel**. Do not turn CN511 into a channel-rank conclusion or EVM129 into a
physical signal measurement. Both alive checks and normal reloads passed; no
transfer ceiling was reached.

[Sanitized passive evidence](../research/evidence/evm-cn-passive-2026-09-05.json).

## Controlled two-stream update and CCK hold

`research/evm_cn_stimulus_probe.py --acknowledge-experimental-transmit` sends
exactly12 source-defined no-ACK probes from MT7925 on channel1/20MHz: four CCK
1Mbps, four HT MCS8/NSS2, four CCK1Mbps. Frames carry a fresh private nonce and
must match completely with good FCS on MT7961. The register is read after a
matching receipt, but **the USB read is not atomic with that frame**; ambient or
undelivered PHY events can intervene. Only receiver reads and established
transmitter rate-table operations occur, followed by normal reload on both radios.

The first run received4/4 in every phase. After the four HT2SS receipts, CN values
were **9,12,12,11**, with EVM byte pairs31/25,31/31,32/32,29/29. The later four
CCK receipts all left CN11/EVM29/29 unchanged. Thus CN does update away from its
initial511 and the signal fields have a controlled live-update path, but they
are not fresh values for each subsequent packet. During the initial CCK phase,
EVM changed to35/34 while no good-FCS OFDM frame was delivered, so do not claim
that only successfully decoded OFDM frames can refresh it.

A second fresh-boot/nonce run again received4/4 in all three phases. Its HT
receipt snapshots returned CN12 each, with EVM34/35,31/30,33/32,34/34. All four
later CCK receipt snapshots held12/34/34, but the final phase-end read reverted
CN to511; three ambient OFDM frames were decoded in that phase. This reinforces
the mode/eligibility and intervening-traffic limitation, rather than establishing
an immutable CN value for the link. Both runs reloaded both radios successfully,
and all twelve expected frames were received in each. One initial CCK collection
in the second run hit the128-transfer ceiling; its receive window was shortened.
The HT and later CCK collections did not hit that ceiling.

[Sanitized stimulus evidence](../research/evidence/evm-cn-stimulus-2026-09-05.json).
No conversion to dB, percent, a matrix condition number, physical distance or
link capacity is validated. The two EVM indexes follow the diagnostic's Rx0/Rx1
labels, not an independently established antenna-versus-spatial-stream mapping.
