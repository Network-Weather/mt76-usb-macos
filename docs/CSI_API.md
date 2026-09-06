# Experimental CSI primitives and session gate (R32)

Implemented on `feat/measurement-api`, not released. `mt76_csi.py` and
`c/mt76_csi.h` expose matching **pure wire primitives**, not yet a public streaming
lifecycle. Hardware/session orchestration currently lives in the bounded research
and native probes below. Do not mistake an accepted command for usable CSI data.

| Python | C | Contract |
| --- | --- | --- |
| `CsiAction`, `build_csi_request` | `MT_CSI_*`, `mt_csi_request` | MT7925 band0 STOP, START, beacon selector, receiver-count1/2, single-transmitter add/remove; no arbitrary commands or masks |
| `parse_csi_ack` | `mt_csi_ack` | Exact EID1/sequence/UNI4a status envelope; return the actual status, never silently treat rejection as success |
| `parse_beacon_csi` / `BeaconCsiReport` | `mt_beacon_csi_parse` / `mt_beacon_csi_report_t` | EID4a/sequence0, complete DMA and TLVs, version22,64 signed I/Q pairs, receiver0/1, transmitter index0; unchanged native output on error |

The selected report profile requires band/CBW/DBW/segment/remain0 and OFDM6
receive metadata. Unknown versions, wider/segmented formats, truncated arrays,
duplicate tags and known-stale CCK count13/storage64 are rejected. Unknown tags
are bounded but not interpreted. Only the evidenced36-byte zero tail after a
four-byte terminal tag25 is tolerated; USB padding cannot supply missing fields.
MT7921 is unsupported, not an empty successful sample.

The report owns its arrays. Python hides transmitter/I/Q from the default repr,
but explicit serialization can still disclose them. Applications must treat
addresses, coefficients and their fingerprints as sensitive. Default probes
export aggregate counts/cardinalities only. The raw RSSI/SNR fields are not
calibrated measurements. `channel_index_raw` is not an RF channel number (it is
zero in the channel36 reference reports). `mcu_gpt_raw` is a wrapping32-bit MCU
timer, approximately1us, not over-air TSF, RXD timestamp or arrival time.
No pair assembly, calibration, clock synchronization or ranging is implemented.
Matching structure alone cannot establish frame subtype or sensor freshness:
the caller also needs the qualified mode, channel, firmware, epoch and filtering.

## New control-order requirement

The working sequence is:

1. Establish normal monitor/sniffer capture on5GHz channel36/20MHz with pinned
   firmware and a single acquisition-session USB owner.
2. STOP, configure beacon selector, START. START clears the firmware allowlist.
3. Add the selected transmitter, **then set receiver count last**.
4. Mark the host configuration-completion time after the last checked ACK.
   Reject preconfiguration packets and enforce transmitter/receiver filters on
   the host too. Keep packet/session epoch and channel generation; do not retune
   while treating reports as belonging to this configuration.
5. STOP explicitly, reject/count late reports, stop the session, and reload
   firmware after the experiment. STOP is not full configuration restoration.

Fresh Python and native controls reproduce an ordering interaction: count1 then
ADD yields both receiver indices despite successful ACKs; ADD then count1 yields
receiver0 only. This is an observed interaction, not yet proof of the exact
firmware field reset responsible. Filtering only in firmware is insufficient
even with the corrected order because reports may already be queued.

## Bounded coexistence probes

```sh
python research/csi_session_probe.py --fw /path/to/pinned/firmware
make -C c mt76_csi_probe
c/mt76_csi_probe --fw /path/to/pinned/firmware
```

Run them separately on the A9000. Both capture normal frames, interleave named
CCA/MPDU and temperature reads every approximately250ms, discover a transmitter
seen in both beacons and CSI, and execute two filtered stop/restart cycles.
`--receiver-order before-filter` reproduces the negative ordering control.
`--event-capacity 1 --stall-ms 250` deliberately overflows the bounded event
queue; drops remain visible, and no complete receiver-pair coverage is implied.
Source/digest storage in the native probe is independently bounded and reports
its own ceilings. Native final diagnostics also expose queued records discarded
at destruction; those are distinct from overflow drops.

[Dated gate evidence](../research/evidence/r32-csi-session-2026-09-06.json) retains
positive and negative ordering/overflow controls. The unfiltered reference
windows yielded190 Python /194 native reports, with normal RX and all MCU queries
completing. Correctly ordered filtered windows accepted20/18 Python and19/19 C
reports, all receiver0 from one selected source. Preconfiguration/late-STOP
reports were rejected explicitly. Intentional one-event queues dropped137
Python /101 native events; neither lost normal-frame queue data or failed USB.
The Python overflow run used the earlier before-filter ordering, while the native
overflow run used after-filter, so those counts are not a like-for-like comparison.

Remaining gate: extract matching public session-bound start/accept/stop ownership
helpers, test failures at every lifecycle stage and epoch/retune rejection, then
perform the selected longer-session acceptance work. Current wire parity and
short coexistence evidence do not establish a released streaming API, multi-hour
stability, calibrated CSI or broader RF configurations.

Active-CSI SIGTERM checks passed in both probes: exit130, explicit STOP ACK and
normal firmware reload. Native cancellation recorded11 frame/2 event records
still queued at destruction. Cancellation stops acquisition; it does not promise
all received records were delivered to the application.
