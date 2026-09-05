# Histogram acquisition during the dongle's own transmissions

**The working MT7925 histogram remains available during bounded own TX, but
collected-sample totals are affected.** Two long-packet controls show lower
totals during the burst and recovery afterward, without a high-bin power pileup.
Ambient variation can outweigh the short-burst effect: the final run's first
quiet window collected fewer samples than its TX window. This supports a
gating/coverage concern, not a calibrated subtraction formula or interference
classification.

## Bounded quiet / TX / quiet controls

[`noise_self_tx_probe.py`](../research/noise_self_tx_probe.py) uses the
[verified UNI36 one-shot event](MT7925_NOISE_HISTOGRAM.md#one-shot-firmware-event-now-works)
for each approximately half-second window. All three windows reset/start both
control indices through firmware and end with the automatic stop/event.
The middle window sends **at most20 synthetic CCK1 no-ACK probe frames**, on
channel6/20MHz, with either65 or193 bytes before FCS. The latter adds the already
tested128-byte private vendor IE. Software Duration0 is explicitly preserved.
No association, handshake, positive power adjustment or ambient-target traffic.

Submission begins after30ms, with at least15ms between completed submissions,
and ends by the400ms scheduling cutoff. Delayed packets are not sent in a
catch-up burst. One run submits19, not20; all conclusions use actual counts.
MT7961 independently checks exact fresh-nonce payloads and good FCS. Only match
sequence numbers are exported, not payloads, addresses or the nonce.

UNI MIB offsets11/12/13/17/31 bracket each acquisition: MDRDY, CCK/OFDM MDRDY
duration, primary CCA and MAC2PHY TX duration. MCU queries are the sole owner;
there are no direct consuming-counter reads or MIB-enable writes. Their windows
enclose the histogram interval rather than being atomically latched with it.

| Start UTC / size | Submitted / independently good | Quiet-before samples | TX samples | Quiet-after samples | MAC2PHY TX ticks |
| --- | --- | --- | --- | --- | --- |
| 20:14:18 /193 | 19 /19 | 53,945 | 50,218 | 53,900 | 33,668 |
| 20:14:51 /65 | 20 /19 | 55,120 | 52,131 | 53,975 | 14,960 |
| 20:15:02 /193 | 20 /20 | 53,717 | 49,451 | 52,717 | 35,440 |
| 20:15:27 /65 | 20 /20 | 48,225 | 52,432 | 53,469 | 14,960 |

All runs are2026-09-05. Both event arrays have exactly the tabulated total in
all twelve windows and exactly match their stopped register views. Both
controls stop automatically. All79 submitted packets have matching TX status:
CCK1/rate0, power raw36, one attempt and no reported error. The other radio
receives78/79 with exact payload and good FCS. Quiet windows have zero MAC2PHY
TX duration. Event receipt stays around511–514ms after activation.

## What the controls discriminate

The duration counter records748 ticks per65-byte packet and1772 per193-byte
packet. Increasing the payload by128 bytes adds1024 ticks per packet, matching
1024us of extra payload at1Mbps. This extends the earlier
[HT duration-counter result](TX_AIRTIME_COUNTERS.md) to CCK. It supports a1us
delta scale for this counter; absolute endpoint/preamble accounting remains
separate from the payload-length result.

The long-burst sample totals are lower than both adjacent quiet controls. The
short-burst totals are lower than their following quiet controls too. The
dominant timer0/timer1 bins remain7/6 rather than accumulating substantial
high-power-bin counts from the radio's own transmitter. This is consistent
with acquisition being gated or otherwise losing coverage during TX, rather
than treating every own-TX sample as environmental high power. The experiments
do not prove complete exclusion of every TX sample or isolate every receiver
holdoff mechanism.

The final short run's quiet-before window has37 MDRDY events and118,474 CCK
duration ticks, versus25/72,470 in the TX window. Its histogram rises rather
than falls during the burst. Retaining this counterexample is essential:
ambient activity is not controlled by the quiet label, which means **no own TX**,
not an RF-silent environment. Neither sample deficit divided by TX time nor
samples×8us is a calibrated full-dwell coverage correction. Source-named CCA
and decoded-duration fields are not interchangeable quantities.

All fixed code/table checks pass, all four histogram masks restore, and both
radios pass alive and normal-reload checks. Shared histogram histories reset
irrecoverably. No IQ/ambient capture export, NVM writes, gain override or RF-test
mode. Collection has a three-second/3072-transfer bound, and timeout tests check
that no phase exceeds20 transmissions and quiet phases transmit none.

[Sanitized four-run evidence](../research/evidence/noise-self-transmit-2026-09-05.json).
For Network Weather, retain whether own probes overlap a measurement window;
do not rank channels from raw histogram totals as though every window had equal
sample coverage.
