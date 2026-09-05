# Fixed HT/VHT/HE transmit exploration

Measured 2026-09-04 Pacific (2026-09-05 UTC), macOS 26.6.1, Python 3.14.7,
MT7961 ALFA `0e8d:7961` and MT7925 A9000 `0846:9072`. Research-only additions;
neither production injection APIs nor C parity claims change. Firmware hashes and
redacted observations are in [evidence](../research/evidence/phy-transmit-2026-09-04.json).

## New on-air capabilities

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
