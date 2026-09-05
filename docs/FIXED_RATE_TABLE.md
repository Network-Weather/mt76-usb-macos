# MT7925 fixed-rate table: ROM mapping and command hazards

Pinned station RAM firmware SHA256
`23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`,
2026-09-05. This is a research interface, not a networking-driver API.
No ROM bytes or ambient packet content are distributed.

## Recovered path

The live CID/handler table at`0x0221c08c` contains CID`0x40` then handler
`0xe0097a40`. Known UNI19 and CSI4a entries establish record parity. Tag0 calls
`0xe00979ee`; its helper`0xe0083e62` calls ROM through slot`0x00828cd8`,
observed target`0x0083c0ac`. The command gate at`0x0222e1b0` reads1.
These were bounded read-only pointer/code checks, followed by normal reload.

The tag payload resembles upstream MT7996's packed20-byte request, but its
validation is peculiar on this MT7925 build:

1. Tag handler loads the first payload byte as index and rejects bit0 clear.
   Thus the earlier **slot18 request is rejected before the ROM call**.
2. The helper calls ROM with that full index. ROM masks it to six bits and
   writes the hardware table.
3. **Only afterward**, caller type5 checks index24..63 and ROM return status.
   Failure here returns`0xc0000001`, despite the earlier hardware write.
4. Success copies10 configuration bytes to`0x02260058 + 14*index`, followed
   by caller type5 and validity1. Other caller types have different rules.

An error ACK is therefore not generally evidence that nothing changed.
The bit0 requirement is an observed odd-index gate, not a proven mode bit.
No out-of-range or odd reserved-slot trial was performed.

## Actual hardware packing

ROM writes`ITDR0=0x820d43b8`, `ITDR1=0x820d43bc`, then
`ITCR=0x820d43b0` with`0x80010000 | (index & 63)`.
The ten-byte internal configuration maps as follows:

| Internal offset | Command TLV offset | Meaning/pointer | Hardware destination |
|---|---|---|---|
| 0..1 | 6..7 | rate code | ITDR0 bits14:0 |
| 2 | **not assigned in traced tag handler** | unnamed low nibble | ITDR1 bits3:0 |
| 3 | 8 | SPE selection | ITDR1 bit6 |
| 4 | 9 | SPE index | ITDR1 bits11:7 |
| 5 | 10 | GI | ITDR1 bits13:12 |
| 6 | 11 | LTF | ITDR1 bits17:16 |
| 7 | 12 | LDPC | ITDR1 bit25 |
| 8 | 13 | beamforming | ITDR1 bit29 |
| 9 | 14 | dynamic bandwidth | ITDR1 bit30 |

Names derive from the corresponding
[upstream fixed-rate request](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7996/mcu.h),
not from guessed adjacent register bits. Positions follow ROM instructions,
including Andes bitfield-deposit semantics documented by the
[pinned Andes emulator](https://github.com/andestech/qemu/blob/32902627f26c5d760cd4efab499b989d566822f9/target/riscv/andes_helper.c).
The existing upstream MT7925 direct writer programs rate plus SPE-selection64.
Beamforming, dynamic bandwidth and explicit SPE routing were **not tested** here.

The tag handler stores a rate halfword at stack+4 and seven bytes at stack+7..13,
then passes stack+4 to ROM. There is no observed store to stack+6. ROM reads
that byte and uses its low nibble. The custom prologue is not fully decoded,
so this is an **apparently uninitialized field**, not a completed memory-safety
audit. In the live trial it is9, despite all corresponding request padding zero.
Do not use this command as a deterministic substitute for the direct writer.

## No-transmission command control

Three requests used only slot25, OFDM6 rate`0x4b`, SPE selection1/index0,
BF/dynamic-BW0, with GI/LTF/LDPC tuples`(0,0,0)`, `(1,1,1)`, `(0,0,0)`.
Wire layout:`struct.pack("<4xHHBBH8B", 0,16,25,0,0x4b,1,0,gi,ltf,ldpc,0,0,0)`.
Each matched EID1/sequence/CID40 with an exact8-byte RXD-bounded body and status0.

ITDR0 reads`0x4b`; ITDR1 reads`0x49 -> 0x02011049 -> 0x49`.
The14-byte cache at`0x022601b6` contains the expected rate/fields/type5/valid1,
including unexplained byte2=9. Both checks corroborate the packing. **These
are staging-register and software-cache observations, not an independent
readback of the hardware table SRAM.** ITCR reads mirror ITDR1 in this trial;
its read semantics are unresolved and not promoted to table-index evidence.
Alive and full normal reload pass. No host frames were submitted.

[Sanitized pointer/command evidence](../research/evidence/fixed-rate-table-2026-09-05.json).

## Independent on-air verification

`phy_tx_probe.py --suite ht-table --transmitter mt7925 --channel 6 --per-phase 4
--acknowledge-experimental-transmit` retains the proven direct writer and slot18.
Only GI bit12 or LDPC bit25 changes from baseline64. The unknown low nibble stays0;
LTF, SPE selection,20MHz width, power, no-ACK policy and frame construction stay
unchanged. Five phases use HT8 baseline, GI1, baseline, LDPC1, baseline.
The existing60-frame ceiling and50ms pacing remain.

The first trial independently receives **4/4 in all five phases**, with exact
fresh-nonce frame bytes and valid FCS. MT7961 reports HT MCS8/NSS2/NSTS2 throughout:
GI1 changes its decoded rate13.0 to14.4Mbps; LDPC1 sets the independent LDPC flag
without changing GI or decoded rate. Baselines report GI0/LDPC=false.
A fresh-nonce repeat again receives **4/4 in every phase**, with the same PHY
distinctions and successful alive/transmitter-reload checks:40/40 total frames.
These are **working short-GI and LDPC transmit formats**, not throughput or
coding-gain measurements. Raw RSSI is roughly−99..−100.5 and uncalibrated.
Both radios remain alive; the probe reloads the transmitter, not both radios.

[Sanitized on-air evidence](../research/evidence/ht-table-transmit-2026-09-05.json).
