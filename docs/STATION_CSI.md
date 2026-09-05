# Station CSI control interface

## MT7925 acknowledges controls; no sample events yet

On 2026-09-05, the A9000's pinned MT7925 firmware accepted **UNI 0x4a** stop,
start and maximum-chain commands: matched EID 1 command-result events contained
status **zero**. This is distinct from both UNI 0x33 PFMU profile reads and the
older AP **EXT** 0x4a airtime command. Numeric command IDs are not interchangeable
between command families.

**No CSI samples were observed.** A successful command acknowledgment does not
prove the capture machinery was armed, that a firmware build implements every
tag, or that its defaults accept unassociated monitor traffic. No CSI, channel
matrix, calibrated SNR or spatial-location capability is claimed.

## Reproduction and bounded controls

Tool: [csi_control_probe.py](../research/csi_control_probe.py).
[Sanitized seven-run evidence](../research/evidence/station-csi-2026-09-05.json).
Hardware/firmware pins are the same as the
[loaded-code investigation](MT7925_LOADED_FIRMWARE.md).

```sh
python research/csi_control_probe.py --chip mt7925 --ack
python research/csi_control_probe.py --chip mt7925 --ack --band 1
python research/csi_control_probe.py --chip mt7925 --ack --band 1 --chains 1
python research/csi_control_probe.py --chip mt7925 --ack --band 0 --chains 2
python research/csi_control_probe.py --chip mt7961
```

Each run freshly boots normal firmware, enables monitor/sniffer reception on
channel 36 at 20 MHz, then sends stop / optional chain configuration / start /
stop. Each phase collects for at most one second plus the final 100-ms USB read,
with a 512-transfer ceiling. Cleanup sends stop again, then reloads normal
firmware. All observed alive and reload checks passed. No test-mode entry,
transmission, association, filter changes, nonvolatile writes, raw coefficients
or ambient frame output occurs.

| Control | Layout | Observed result |
|---|---|---|
| MT7925 stop/start | band byte + 3 reserved; u16 tag 0/1 + u16 length 4 | ACK option 7: status 0, both band selectors |
| MT7925 chain count | band/reserved; tag 3 + length 8; u8 count + 3 reserved | status 0 for band1/count1 and band0/count2 |
| MT7961 stop/start | CE 0x4c SET, 48 bytes: band, mode 0/1, zeroed remainder | EID 0xfd at each matched sequence; vendor labels this command-not-found |

The vendor bridge uses UNI **option 6**, SET without ACK. Our first no-ACK
MT7925 run reached its then-64-transfer ceiling and was inconclusive. A repeat
with the 512 ceiling consumed the full one-second windows (68/66/58 transfers)
without CSI or command-result events. The separate `--ack` diagnostic uses
option **7** and exposed the successful status replies. No-ACK silence was not
misclassified as rejection.

Band 1 is not a random sweep: the vendor private-command frontend explicitly
selects band 1 for a 5/6-GHz BSS and band 0 for 2.4 GHz. Both were tested because
the USB monitor's band selection and this station interface may differ. Neither
selector yielded EID 0x4a data events. Optional chain-count runs likewise had
no sample events and did not reach their transfer limits.

## Source pointers and next discrimination

Protocol facts, not copied implementation, from Motorola gen4m
[`8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec`](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/tree/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec):

- `include/nic_uni_cmd_event.h`: command enum 0x4a, tags 0/1/2/3/4,
  packed stop/start/chain structures, unsolicited CSI event 0x4a/tag0.
  Its section comment still says 0x48; the enum and conversion code take priority.
- `nic/nic_uni_cmd_event.c:nicUniCmdSetCsiControl`: legacy-to-UNI conversion.
  Notably, it maps `CSI_CONFIG_OUTPUT_FORMAT` to the chain-count tag; names from
  the legacy API cannot be substituted directly for UNI tag numbers.
- `common/wlan_oid.c:wlanoidSetCSIControl`: SET/no-ACK choice.
- `os/linux/include/gl_csi.h`: 48-byte legacy control, modes, event fields.
- `include/wsys_cmd_handler_fw.h`: CE command 0x4c, CSI event 0x3c,
  and EID 0xfd command-not-found meaning.
- `os/linux/gl_wext_priv.c:priv_driver_set_csi`: band selection and CLI validation.

Next useful distinction: trace which state the accepted controls modify, then
resolve frame-type/filter defaults and the report path. The public frame-type
tag has an index and u32 value but does not establish their bit semantics here;
we have not guessed a catch-all mask or written arbitrary filter settings.
The weak MT7961-to-MT7925 test link also prevents a strong controlled-stimulus
CSI experiment for now. Nineteen offline tests cover request bounds, chip/band
layouts, matched status versus unsolicited data, rejection events, truncation,
ambient-frame filtering and absence of coefficient/address output.
