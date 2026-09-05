# Per-rate power reports and stale width rows

Both dongles expose source-defined per-rate power reports in normal monitor
mode. **MT7925's inactive-width rows retain earlier channel values**, so a report
must not be presented as a fresh power plan for every displayed width. These
are firmware table observations, not measured radiated power or a diagnosis of
the current weak reciprocal link.

## Exact read interfaces

Pinned mt76`c5a3bd91aa735b669618610d5f0ebfa5786845a6` supplies both requests:

| Device | Read operation | Request | Observed response |
| --- | --- | --- | --- |
| MT7961 | [mt7921_get_txpwr_info](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mcu.c#L1128) | CE`0xd0`, eight zero bytes, normal SET/ACK envelope | EID`0xd0`,494-byte body |
| MT7925 | [mt7925_get_txpwr_info](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7925/mcu.c#L2207) | UNI`0x2b`, four reserved bytes, tag7/length8, bytes`0,2,0,0`; option7 | EID`0x2a`,849-byte body |

The envelope's SET flag does not make these payloads power setters: they are
the exact Linux report operations. No adjacent rate/percentage/limit controls
are sent. The gen4m [report bridge](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_uni_cmd_event.c#L6680)
and event enum separately identify this read surface; UNI response ID differs
from command ID. The first metadata-only diagnostic observed EID0x2a rather
than the provisional command-ID expectation and deliberately did not parse its
table until the event ID was checked against source.

MT7961 body layout from [mcu.h](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mcu.h#L62)
and [mt7921.h](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7921/mt7921.h#L177):
version/action0, u16 length494, channel plus three reserved bytes, then three
162-byte planes. Each plane has a channel byte and161 u8 rate values across
CCK/OFDM/HT/VHT/HE. Plane names are USER, EEPROM and MAC; reading the
EEPROM-named report plane is **not an EEPROM programming operation**.

MT7925 layout from [mcu.h](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7925/mcu.h#L64)
and [mt7925.h](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7925/mt7925.h#L229):
four reserved bytes, tag5, length841, then category5/band0/channel-band/format1,
834 signed bytes representing417 rates × two firmware-band columns, and three
tail bytes. **The observed TLV length841 excludes its four-byte tag header**;
do not apply the request's include-header convention blindly. The strict parser
accepts only this observed shape, matching sequence/type/EID and declared DMA
length, and ignores USB transfer padding. It exports the requested band0 column
by rate group and summarizes distinct values in the other column.

The last byte, called reserved in Linux's structure, follows the configured
**center channel** in all13 controlled MT7925 samples, including8 and38 at40MHz.
It remains named`tail_byte_raw` in the tool because source does not name it.
MT7961's top-level and plane channel bytes likewise follow center, not primary.
MT7925 channel-band byte is0 on2.4GHz and1 on5GHz here; the requested firmware
band index remains0. These two kinds of band index must not be conflated.

## Width history is visible in MT7925's report

Baseline order is6/20 →6(center8)/40 →6/20 →36/20 →149/20 →6/20.
HT20 values are all36 on channel6 and26 on36/149. HT40 initially reads all0,
becomes all36 after40MHz configuration, and **stays36 at5GHz/20MHz** while
HT20 correctly changes to26. HE484 rows similarly retain their earlier values.

A fresh boot with reversed width/channel order discriminates retained state
from a fixed per-width difference:

| Primary / center / width | HT20 row values | HT40 row values | Raw tail byte |
| --- | --- | --- | --- |
| 6 / 6 / 20 | 36 | 0 | 6 |
| 36 / 36 / 20 | 26 | 0 | 36 |
| 36 / 38 / 40 | 26 | 26 | 38 |
| 6 / 6 / 20 | 36 | **26 retained** | 6 |
| 6 / 8 / 40 | 36 | 36 | 8 |
| 36 / 36 / 20 | 26 | **36 retained** | 36 |
| 6 / 6 / 20 | 36 | 36 | 6 |

This demonstrates width-dependent refresh/history for the probed monitor setup.
It does not establish the writer's exact code path, prove stale values are used
for transmission, or claim a bug in Linux's live networking workflow. Linux's
[debugfs printer](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7925/debugfs.c#L118)
is a concrete consumer for maintainers to review alongside these qualifications.

All selected-band entries are reported as raw signed codes, not dBm. The other
firmware-band column stays0. Tail max/min fields stay63/−128, whose operational
limit/sentinel meanings are not validated. A zero inactive-width row is not
proof of zero RF power;127 is treated as N.A by the source debugfs printers.

## MT7961 supplies distinct table planes

USER entries are127 apart from zero-valued slots in the VHT rows. EEPROM and MAC planes are nonuniform
per-rate curves and change with channel family. Examples at channel6/20:
OFDM EEPROM values39/38/37 and MAC42/41/40; HT20 EEPROM40..36 and MAC43..39.
On36/149, OFDM EEPROM includes40/37/36 and MAC44/41/40. Full per-rate arrays
are retained in the evidence; ranges here are not a conversion formula.

Unlike the MT7925 report, the inspected MT7961 HT40/HE484 rows refresh with
channel-family changes even while configured20MHz. This difference is useful
for interpreting each device, not a claim that either table measures antenna
output. MT7925's36/26 baseline codes are consistent with earlier TX statuses,
but those agreement checks alone do not explain the degraded link.

## Reproduce and scope

[`txpower_info_probe.py`](../research/txpower_info_probe.py) runs six passive
channel/width settings per device;`--suite width-cache` runs the seven-step
reversed sequence. It performs no TX, direct register reads, explicit power
programming, nonvolatile writes or ambient frame export. Both radios finish in
normal monitor mode on channel6/20MHz after firmware reload. All26 controlled
queries and all alive/reload checks pass. Offline tests cover exact request
bytes, layout sizes/order, signed versus unsigned values, alternate USB lengths,
wrong sequence/type/shape rejection and the bounded channel plans.

An additional instrumented normal reload confirmed that the existing
`bringup()` USB-reset call returns success on both dongles. USB reset was already
part of every normal reload; this was not a new recovery action, hub reset or
physical power cycle. It does not establish restored RF performance.

[Sanitized evidence](../research/evidence/txpower-table-state-2026-09-05.json)
contains both query sequences and the reset outcome. Production Python/C APIs
and passive defaults are unchanged.
