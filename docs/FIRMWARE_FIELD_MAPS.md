# MT7961 ROM-derived IPI and ICAP field maps

Pinned RAM SHA-256 `b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9`;
attached MT7961, 2026-09-05. These are firmware-specific register facts, not a
working spectrum analyzer or a cross-chip API. No ROM bytes are redistributed.

## Resolution chain

The [runtime GP correction](NDS32_RECON.md#runtime-relocation-resolves-the-real-gp)
unlocks a shared field-access framework in ROM:

1. Runtime GP 0x02003000 + 0x10884 contains resolver pointer **0x00826860**.
2. That resolver indexes **0x02014f04** by `(key >> 16) & 255`, with domain < 92.
3. Domain 0x26 points to descriptor 0x0201392c, whose first word is mapper
   **0x00830350**. Domain 0x5a points to descriptor 0x020139cc, first word
   **0x00832174**. Other descriptor words were not interpreted as callbacks.
4. Each mapper uses `(key & 65535) >> 5` to select an eight-byte ROM descriptor:
   field-table pointer, 16-bit register offset, and byte field count.
5. `key & 31` selects a two-byte inclusive low/high bit range from that field
   table. **It is a field index, not a bit position.**

IPI uses descriptor table 0x0084cac4 and register base 0x830a0000; ICAP uses
0x0084d550 and base 0x80021000. Generic accessor 0x00826b12 performs masked
read-modify-write; 0x00826c22 performs masked, shifted reads and copies one,
two, or four result bytes for its typed wrappers. The mappers' independent
mask calculations agree: bits low through high inclusive, including bit 31.

## Concrete mappings

| Field key | Register | Bits | Observed firmware use |
|---|---|---|---|
| 0x260000 | 0x830af04c | 5 | IPI initialization writes 1 |
| 0x260001 | 0x830af04c | 8:6 | IPI initialization writes 4 |
| 0x260002 | 0x830af04c | 3:0 | IPI initialization writes request value |
| 0x260080 + 32 × i, i=0..11 | 0x830af0a8 + 4 × i | 22:0 | Twelve IPI GET values |
| 0x5a0013 | 0x80021090 | 1 | ICAP start/active; status reports inverse |
| 0x5a0005 | 0x80021090 | 22:20 | ICAP start-path field; meaning not yet named |
| 0x5a0008 | 0x80021090 | 17 | ICAP start-path read; meaning not yet named |
| 0x5a0040 | 0x80021098 | 31:0 | ICAP start-path word |
| 0x5a0060 | 0x8002109c | 31:0 | ICAP start-path word |
| 0x5a00a0 | 0x800210a4 | 31:0 | ICAP start-path word |
| 0x5a0120 | 0x800210b4 | 31:0 | ICAP start-path read |

The twelve 23-bit IPI values are not automatically twelve calibrated power bins.
The firmware's ALL response includes its free-run accounting; bin thresholds,
time units, accumulation behavior, and clear/read effects need live validation.
Likewise the ICAP word fields are not yet named as addresses or lengths.

## Reproduction and boundaries

[`research/firmware_fields.py`](../research/firmware_fields.py) independently
resolves only the traced keys from live ROM metadata. It refuses arbitrary keys,
out-of-range pointers, and malformed bit ranges. Its snapshot functions read
fixed registers only. The optional `--registers` flags on the IPI compact and ICAP
capture probes run separate diagnostic comparisons; added register reads may
affect hardware state and are not silently inserted into acquisition.

[Sanitized evidence](../research/evidence/firmware-field-mappings-2026-09-05.json)
records pointers, resolved fields, bounded ROM-window hashes and successful
reload/alive checks. Raw ROM remained in local temporary files. Disassembly used
the independent NDS32 inspector; no firmware implementation was copied into the
driver and no new direct register write was performed for this discovery.

## Live command/register cross-check

Normal and activated RF-RX runs with old/compact IPI setters still read zero at
the resolved control and counter registers, before/after SET and after three GETs.
The expected initialization fields did not appear in these USB reads. This does
not yet distinguish gated hardware, an ineffective write path, or a USB alias.

ICAP is much stronger: with mode 2, explicit channel setup, node 0x49 and event
-1, control 0x80021090 changes **0x400 → 0x4f3 → 0x4f1** across pre/start/stop.
Bit 1 therefore independently agrees with status: inactive, active, inactive.
The three post-start status polls remain incomplete; the control stays 0x4f3.
Other start-path words change too: 0x80021098 becomes 0, 0x8002109c becomes
0xfffc, and 0x800210a4 becomes 64. Their roles and the validity of that setup
remain under investigation. No data retrieval was attempted. All reloads passed.
[Live comparison evidence](../research/evidence/field-register-controls-2026-09-05.json).

## Activation controls and remaining limits

Further [activation evidence](../research/evidence/field-activation-controls-2026-09-05.json)
isolates these issues without claiming working samples:

- The PHY USB window does work: ICAP changes 0x83080004/8 from 0x3800 to 0x3840,
  0x830a1000 from 0 to 0x04010100, and the selector registers exactly as the
  disassembly predicts. A blanket “0x83 registers are inaccessible” explanation
  does not fit these controls; individual sub-block gating remains possible.
- A single direct masked IPI initialization at 0x830af04c, mask 0x1ef/value 0x121,
  also reads back zero in activated RF RX. Its counters and firmware GET remain
  zero after 0.5 seconds. The original word was restored and reload/alive passed.
  This reproduces only the three firmware initialization fields, not an arbitrary
  register sweep. No additional gating writes were guessed.
- On-chip capture wrappers 0x0096be4e/5c intentionally select start 0/end 0xfffc
  for this caller: a 64-KiB device-buffer range, not supplied host DMA addresses.
- Packed node 0x00110000 uses class 0x11, group/format 0 and selector 0. Firmware
  0x0096c4d2 halves the stop count for classes 0x11, 0x14, 0x21. With 64 requested
  samples, hardware 0x800210a4 becomes 32 and 0x830ad440 becomes 0x80000011.
  Those predictions hold, but capture still stays active; no data is retrieved.
- Starting RX after ICAP-mode entry, as the original phone tool does, also leaves
  capture incomplete with this node. A separate identical-settings scalar control
  sees RXOK 0→2 in mode 1 but 0→0 in mode 2 over 0.5 seconds. Ambient exposure was
  low, so this is not proof that mode-2 RX cannot work. Neither mode entry nor
  configuration acknowledgment alone proves an active sampling clock.

[`ipi_register_probe.py`](../research/ipi_register_probe.py) preserves the exact
reversible write experiment behind `--direct-init`. All runs stop/reload cleanly.
The legacy CE ICAP-start route remains a separate lead; it was not executed here
because its buffer/architecture defaults have not yet been traced on this image.
