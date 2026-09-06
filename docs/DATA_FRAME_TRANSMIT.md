# Synthetic data and QoS transmit controls

MT7925 transmits independently decoded ordinary Data and QoS Data frames at
HT8/two streams/20MHz on channel6. Both classes receive **4/4 in two fresh
runs**, with complete fresh-nonce payload matches and good FCS. This supplies
a new controlled frame-class stimulus, not a networking driver or associated
link. No IP traffic, authentication, association or packet forwarding is used.

[`data_frame_probe.py`](../research/data_frame_probe.py) has exactly five
four-frame phases: Probe Request / Data / Probe Request / QoS Data / Probe
Request. Destinations are broadcast, transmitter/BSSID are synthetic local
addresses, duration is zero and both descriptor and QoS policy specify no ACK.
Data uses LLC/SNAP local-experimental EtherType`0x88b5` plus a private nonce,
not IPv4, IPv6 or EAPOL. There is no A-MSDU, BA setup, power change or sustained
transmit loop. Both radios receive normal reloads in cleanup.

| Transmitter / rate | Probe before | Data | Probe middle | QoS Data | Probe after |
| --- | --- | --- | --- | --- | --- |
| MT7925 HT8, initial | 3/4 | **4/4** | 4/4 | **4/4** | 3/4 |
| MT7925 HT8, fresh repeat | 3/4 | **4/4** | 4/4 | **4/4** | 4/4 |
| MT7961 CCK1, reverse control | 0/4 | 0/4 | 0/4 | 0/4 | 0/4 |

All20 TX statuses arrive in each run. MT7925 reports the requested code`0x488`,
count1 and no error bits; MT7961 reports CCK code0 and no ACK-error bits.
The Connac2 sequence is extracted from TXS1 bits31:20, allowing sequence/PID
matching instead of treating a window's arbitrary status as the current packet.
Status success is not substituted for independent RF reception.

The reverse test fails even its Probe Request controls. It therefore cannot
establish Data/QoS failure specifically, and **does not provide the missing
controlled stimulus into MT7925's CSI receiver**. Forward MT7961 reception
qualifies the frame generator but not data-frame CSI. No CSI control was sent
in these trials; the receive-side gate in [STATION_CSI](STATION_CSI.md#receive-side-eligibility-gate-beyond-the-frame-selector)
remains unresolved. All alive/reload checks pass.

## Protocol and descriptor pointers

At mt76`c5a3bd91aa735b669618610d5f0ebfa5786845a6`,
[MT7925's 802.11 TX builder](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7925/mac.c#L676)
sets the actual MAC header length divided by2, frame type/subtype and fixed-rate
selection for multicast traffic. The [Connac2 builder](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt76_connac_mac.c)
also populates USB TXD8's duplicate type/subtype. The bounded generator preserves
the existing fixed20MHz path and changes these source-defined descriptor fields;
QoS header length is26 bytes instead of24.

Linux`8ab1afb2eb246ab15b301cd255b5943d208a93c1` defines
[QoS NoAck policy`0x20`](https://github.com/torvalds/linux/blob/8ab1afb2eb246ab15b301cd255b5943d208a93c1/include/linux/ieee80211.h#L246)
and [local-experimental EtherType`0x88b5`](https://github.com/torvalds/linux/blob/8ab1afb2eb246ab15b301cd255b5943d208a93c1/include/uapi/linux/if_ether.h#L95).
Tests verify length/type agreement, QoS header placement, no-ACK/no-NAV policy,
bounded sequences and refusal of other frame classes before USB access.

[Sanitized evidence](../research/evidence/data-frame-transmit-2026-09-05.json)
contains receipt counts, PHY metadata, TX statuses and firmware hashes, never
ambient frames or identifiers. Production injection APIs and C parity remain
unchanged; this is a research-only capability.
