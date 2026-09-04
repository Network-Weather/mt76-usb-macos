# MT7925 transmit exploration, 2026-09-04

Research-only reverse direction of the [receiver-evidence experiments](RECEIVER_EVIDENCE.md).
The production `Mt7925uDevice.inject()` remains deliberately unsupported.
Redacted [hardware evidence](../research/evidence/mt7925-transmit-2026-09-04.json)
preserves all three initial runs, including the insufficient first matcher.

## Source-derived experiment

[`research/mt7925_tx_probe.py`](../research/mt7925_tx_probe.py) transcribes the bounded
injected-management subset of `mt7925_mac_write_txwi`, `mt7925_mac_write_txwi_80211`,
and `mt7925_usb_sdio_tx_prepare_skb` from openwrt/mt76
`c5a3bd91aa735b669618610d5f0ebfa5786845a6`, plus that revision's
`mt76_connac3_mac.h`, `mt7925/init.c`, and `mt792x_regs.h`.
The source files carry BSD-3-Clause-Clear; the MediaTek copyright is retained.
This is an upstream-derived mechanism, not an independently invented transmitter.

Important differences from the working MT7961 experiment:

- TXWI word 1 has a fixed-rate flag, different header geometry, and no connac2
  LONG_FORMAT flag. The numerical bit 31 now means fixed rate.
- Word 6 supplies a six-bit **rate-table index**, not the connac2 inline PHY rate.
  The probe programs volatile table slot 18 to OFDM 6 Mbps (`0x4b`), exactly the
  upstream basic-rate initialization entry `MT792x_BASIC_RATES_TBL + 4`.
- Multicast/BCM is in word 3 bit 4; word 6 includes one MSDU and DAS.
- TX status has a four-word prefix and twelve-word records, not two/eight.
- Word 6 bit 3, `MT_TXD6_DIS_MAT`, is a candidate control for preserving raw
  injected addresses. The upstream non-MLD vif path sets it.

No association, keys, firmware patch, persistent configuration, rate increase,
deauthentication, or ACK solicitation is used. The rate-table write is followed
by firmware reload and a monitor-mode reconfiguration in cleanup. Read-back of the
staging register is not proof of rate-table contents; independent receive is the
acceptance criterion. Both radios' register-alive checks are recorded.

## Initial hardware result

Test bed: attached A9000 `0846:9072` transmitting, ALFA MT7961 `0e8d:7961`
receiving, macOS host, checksum-pinned firmware recorded in each JSON output.
Both are tuned to channel 36 / 20 MHz. Directed Probe Requests use a synthetic
SSID and source address; no ambient addresses or payloads are serialized.

```bash
./.venv/bin/python research/mt7925_tx_probe.py --channel 36 --count 10 \
  --acknowledge-experimental-transmit --output /tmp/mt7925-tx36.json
```

First run: ten TX status records, all OFDM `0x4b`, PID 3, raw power 26, no ACK
error bits. A source-address-only receive matcher found zero frames. This was
**not** sufficient evidence of transmit failure.

Second run: match the synthetic directed SSID and sequence instead of requiring
the submitted source address. **10/10 distinct sequences were independently
decoded at OFDM 6 Mbps**, median receiver RSSI -48. All ten had a rewritten source
address. TX status reported one transmission each, with error bits 16:22 clear.
Both radios stayed alive, and transmitter firmware reload succeeded.

Thus MT7925 transmit works in this bounded configuration, but the initial raw-frame
path does not preserve the requested source address. The replacement address is
not logged. The first negative result was an observation-matcher failure, not an
established RF failure. `--disable-mat` tests the upstream flag separately.

Third run: add `--disable-mat --count 20`. **20/20 received frames match the
submitted bytes exactly**, including source address, sequence, and payload.
The only descriptor change is word 6 bit 3. All 20 TX statuses report OFDM 6 Mbps,
one transmission, and zero error bits. Both chips remain alive and firmware cleanup
succeeds. This validates DIS_MAT for byte-preserving Probe Requests on this setup.

The tool returns 2 for no independent decode, 1 for observed execution/cleanup
errors, and 0 for independent receipt. A zero exit code does not promise complete
delivery, arbitrary frame types, auto-ACK, absolute power calibration, or regulatory
enforcement. The CLI permits only channels 36/149, 20 MHz, at most 60 frames and
50 ms spacing. Offline tests cover descriptor geometry, bounded codes, exact
rate-table write order, and connac3 TX-status record sizes.
