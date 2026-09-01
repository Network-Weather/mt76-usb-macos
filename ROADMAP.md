# Roadmap

Stack-ranked, not numbered. The driver captures reliably today (RX on all three bands
including 6 GHz, radiotap pcap out, working control/management/data frames). These are the
things most worth doing next.

- **Keep the chip up between captures.** Firmware is re-uploaded on every run today. Boot
  once and hold the device initialized across captures to cut retune/startup cost.
- **Hardware CCA / channel-busy counters.** The upstream registers exist but read back zero
  in this bring-up. Getting real CCA busy / RX / OBSS time would turn channel comparison
  from frame-count heuristics into airtime measurement.
- **Noise floor.** `mt792x_phy_get_nf()` returns zero here; find the correct path so RSSI
  has a floor to sit above.
- **A-MSDU de-encapsulation.** Subframes are accounted for but not split into individual
  inner frames.
- **Wireshark extcap wrapper.** A thin script emitting radiotap pcap on stdout would drop
  this straight into Wireshark's external-capture UI, making it usable without writing
  Python. Highest-impact end-user feature.
- **Sibling MediaTek chips.** The MT7922 (160 MHz) and other connac2/connac3 parts share
  most of this path; widening support is mostly register and capability gating.
- **Injection stability.** Transmit is confirmed only at scan rates and can panic the MCU
  under sustained load. Understanding and bounding that is required before injection is
  anything more than a demo.

Boundaries that are unlikely to move (documented in the README): single radio means no
simultaneous multi-channel; 160/320 MHz capture is gated in firmware for this part; the
adapter is a strong receiver but a weak (~8 dB down) transmitter.
