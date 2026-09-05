# MT7961 in-band / wideband signal fields

Two additional raw signal surfaces are now resolved: a live normal-mode PHY
register, and four frame-associated FAGC fields in the ordinary Group5 receive
vector. These are the firmware's names and signed integer encodings, **not
calibrated dBm, an interference score or independently identified antennas**.
No normal-mode CFO/SNR enable is implied; those P-RXV2 fields remain a separate
[mode-dependent surface](LEGACY_ICS.md).

## Register source and statistics provenance

Pinned RAM SHA256 is
`b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`,
runtime GP02003000 and EX9 table0096c7bc. CE1 GET50 dispatch at009336d8
reaches00933b18 →00943f18 →00968e1a. It reads **830003e0** for argument0
or **830103e0** otherwise, then copies the complete word into the reply.
The neighboring00968e30 clears that register; this investigation never invokes
that operation or writes either signal register.

The CEc8 statistics builder00931212 reads both registers through the same
wrapper at00931238/00931240. Its extraction at0093135e..009313be and
0093178e..00931812 independently establishes the meaningful upper bytes:

| Source | Firmware signed extraction | CEc8 zero-based words |
| --- | --- | --- |
| 830003e0 bits23:16 | wideband bank0, signed8 | 10 and38 |
| 830003e0 bits31:24 | in-band bank0, signed8 | 11 and34 |
| 830103e0 bits23:16 | wideband bank1, signed8 | 12 and39 |
| 830103e0 bits31:24 | in-band bank1, signed8 | 13 and35 |

The statistics names include `WB_RSSI0/1`, `IB_RSSI0/1`, `InstRssiIBR0/1`
and `InstRssiWBR0/1`. The getter selects register banks using the RF-test band
argument; this does **not** independently identify physical antenna0/1. The
lower16 bits are not decoded as additional RSSI fields. Earlier low-to-high
byte/signed-byte candidates remain in the evidence for audit.

Two normal-mode twelve-frame tests send known HT8 traffic at TX descriptor
offsets0/−8/0 and0/−4/0. Both zero-offset brackets receive4/4 each. The
attenuated windows receive0/4 and2/4 respectively; TX status independently
reports powers36→28→36 and36→32→36. The register changes repeatedly during
normal reception; bank0 wideband stays−68 in these trials while in-band varies.
Only18/24 full packets are received overall. Polling and after-receipt reads
are **not atomic with a packet**, so these runs do not calibrate the sensor or
establish a clean power-response curve. Both radios reload after both runs.

## Frame-associated FAGC fields

The same statistics builder extracts these fields at009316c0..00931778 from
band0 cached C-RXV words7/8 (02040824/02040828). The normal RX Group5 block
contains the same18-word C-RXV. The formula is identical at either origin:

| Firmware field | C-RXV bits | Normal ICS byte location | CEc8 word |
| --- | --- | --- | --- |
| FAGC in-band index0 | word7 bits7:0, signed8 | 44 bits7:0 | 26 |
| FAGC in-band index1 | word7 bits15:8, signed8 | 44 bits15:8 | 27 |
| FAGC wideband index0 | word8 bits12:5, signed8 | 48 bits12:5 | 30 |
| FAGC wideband index1 | word8 bits21:14, signed8 | 48 bits21:14 | 31 |

The firmware reconstructs some9-bit quantities then logically shifts right1
before signed8 conversion. The fractional bits are therefore discarded, not
sign-extended first. [Independent formula implementation](../research/legacy_signal_fields.py)
and tests preserve this order. These indices follow the firmware's labels;
physical antenna calibration and the actual wideband measurement bandwidth
remain unverified. A difference between in-band and wideband values is not yet
a validated adjacent-channel or non-Wi-Fi interference metric.

Two receive-only fresh-boot cross-checks each query normal mode, two RF RX
windows and two stopped windows. All32 nonzero FAGC comparisons across the
eight RF/stopped replies match the cached-field formulas. The four stopped
replies match **48/48 selected statistics words**, including the duplicated
instantaneous fields. Live instantaneous reads sometimes disagree even when
the before/after endpoints are equal; matching endpoints do not prove an
unchanging interval. Those mismatches are retained. Normal CEc8 replies contain
zero statistics despite live nonzero signal registers, so CEc8 is not the
normal-mode readout route. Both runs stop and reload successfully; no TX occurs.

Normal Group5+ICS controls then send16 known frames each:

| Requested PHY | Full good-FCS packets | Own ICS headers | Paired signal-field evidence |
| --- | --- | --- | --- |
| HT8, two streams | 16/16 | 8/8 enabled | C-RXV words7/8 match ordinary Group5 |
| HE2SS MCS0, LTF0 | 0/16 | 8/8 enabled | Header evidence only; not good-FCS validation |
| CCK1 | 16/16 | 8/8 enabled | Ordinary Group5 pairing succeeds |
| HE2SS MCS0, LTF1 | 16/16 | 8/8 enabled | Ordinary Group5 pairing succeeds |

The three qualified PHY runs receive48/48 complete packets and24/24 enabled
headers with populated FAGC values. The failed HE LTF0 control remains separate;
do not treat a matching ICS header as a full-payload/FCS verdict. All64 submitted
frames have TX status, all four ICS masks restore and both radios reload.
The probe records rate/LTF settings explicitly for subsequent runs.

A fifth HT trial directly extracts the fields from all16/16 ordinary Group5
receipts. The eight enabled-phase ICS records agree with those ordinary
fields exactly. The eight receipts in the two **ICS-off** windows also contain
populated FAGC values: **ICS is not required for this measurement when Group5
is enabled**. This trial restores all masks and reloads both radios. Across
all five format/direct-extraction trials,80 TX statuses are observed;64 full
packets arrive, with the16 HE LTF0 misses retained separately.

## Reproduction and boundaries

`research/wideband_signal_probe.py --acknowledge-experimental-transmit`
uses normal mode and reads only830003e0. `--attenuation 4` selects the smaller
bounded negative offset; no positive offsets or arbitrary registers exist.

`research/signal_field_crosscheck_probe.py` performs the receive-only five-query
comparison. CEc8 may drain statistics, so it needs exclusive ownership. It
exports only identified scalar fields, never raw vectors or heard identities.

`research/legacy_ics_own_probe.py --activate-legacy-rmac-ics
--acknowledge-experimental-transmit --enable-group5 --phy ht8` emits the four
FAGC fields for own ICS headers and ordinary Group5 receipts. Other fixed
choices are `cck1`, `he2ss0` and `he2ss0-ltf1`; the LTF0 failure is not hidden.
Raw captures remain in memory only. No production Python/C API is changed.

[Complete sanitized trials](../research/evidence/inband-wideband-signal-2026-09-05.json).
Primary protocol names come from pinned Motorola gen4m8fddb9d7:
[rftest.h](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/rftest.h),
[gl_qa_agent.h](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/os/linux/include/gl_qa_agent.h),
[QA field projection](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/os/linux/gl_qa_agent.c).
Register locations and bit formulas are established by this firmware's trace,
not copied from the sibling-chip addresses in public headers. No vendor code
or firmware bytes are redistributed.
