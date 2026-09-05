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

## Loaded-code follow-up: control and report routines identified

The entire declared code region 3 (`0xe0026c00`, 594896 bytes) was read locally,
SHA-256 `a4fbdb6a78bb1e8847947f22f4310005e67b21e81f3b3e1eeff9d63e58a3e2cd`.
Its two earlier independently read PFMU windows match exactly. No code bytes are
published. A targeted static-data search found `whCsiLoadMemory`; its reference
at `0xe0061100` led to the CSI hardware helpers, but the symbol alone was not
treated as evidence of a reporting interface.

Independent instruction references identify the **report constructor at
`0xe009e396`**. It emits EID 0x4a with sequence zero, builds outer TLV tag 0,
and calls the nested-TLV builder `0xe009e222`. The observed inner tag order
matches the public CSI enum, including I/Q tags 6/7, DBW 8, channel index 9,
transmitter address 10, receive mode 12 and TX/RX indices 18. Report-state base
is `0x0225d994`; the transmitter-address field is deliberately not read or saved.
This establishes an implemented report-construction path, not its execution in
our live runs or correctness/calibration of hypothetical samples.

**Control handler `0xe003d3f0`** accepts band 0/1, walks TLVs at command-buffer
offset 0x34, and indexes a five-entry jump table at **`0x02215558`**. A live USB
read exactly matches all five decoded branch destinations:

| Tag | Branch | Observed instruction behavior |
|---|---|---|
| 0 | `0xe003d466` | clears selected configuration's mode; stop helper `0xe009e2de` |
| 1 | `0xe003d49a` | stores mode/enable=1 and band; hardware helper `0xe009e256` |
| 2 | `0xe003d4c4` | validates index <=3, stores one selection byte, marks that index configured |
| 3 | `0xe003d4ec` | stores chain byte and a configuration flag |
| 4 | `0xe003d4fa` | delegates filter operation and supplied address to `0xe00611d4` |

There are two **14-byte configuration records at `0x02239760` and
`0x0223976e`**. The optional `--state` probe reads only this fixed 28-byte
configuration array, not report/sample/address buffers. Both records remained
all zero before/after accepted stop, chain and start commands in two fresh-boot
controls (band0/count2 and band1/count1). This **does not prove the handler is
idle**: CPU-cache/USB visibility, alternate dispatch, or another unmet condition
remain unresolved. The live jump table corroborates the address derivation, but
does not by itself establish coherence of subsequent RAM reads.

An independent read-path control used upstream `mt7925_mcu_regval`, UNI 0x0d
QUERY, BASIC tag0/length12 and its 20-byte union-sized payload. EID 6 returned
a valid matching hardware-status register value for `0x7c0600f0` (3), but the
four attempted CSI RAM addresses returned no valid TLV/address match. Those
responses are **not accepted as zero CPU-memory values**. Transfers were 1548
bytes with declared RX length 1536; only the recognized first TLV is meaningful.
No register writes or RAM-access bypass was attempted through that API.

The hardware-enable helper's field keys are `0x001302c0/2c1` plus band<<16;
frame-selection keys are `0x001302c7/2cb` plus band<<16 minus index. Its live
field callback at `0x02210428` points to ROM `0x0082a21e`. Further callback
tracing is underway before naming or probing the corresponding MMIO registers.

[Sanitized state/static evidence](../research/evidence/csi-code-state-2026-09-05.json)
contains pointers, code hashes, configuration snapshots and matched-event shapes,
not code/sample bytes. The Andes annotator now renders GP-relative word stores
from pinned upstream operand definitions; it remains annotation-only and does
not resolve all custom instructions. Twenty offline CSI-probe tests pass.
