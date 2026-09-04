# research

Open questions and the experiments that probed them. Fresh as of 2026-09-03.

Everything here touches hardware, answers a question that is **not yet settled**, and is not
part of the supported surface. Scripts in [`../scripts/`](../scripts/mib_survey.py) are diagnostics that
work; scripts here are how we find out whether something *can* work. A result that graduates
moves to `scripts/` with dated evidence in [../docs/TESTING.md](../docs/TESTING.md); a result
that dies is recorded in [../NEGATIVE_RESULTS.md](../NEGATIVE_RESULTS.md) and the script stays
so the finding can be re-run rather than re-argued.

The background, the capability map and the method these follow are in
[../docs/FIRMWARE_RECON.md](../docs/FIRMWARE_RECON.md).

## What is here

| script | question | state |
|---|---|---|
| [`ipi_probe.py`](ipi_probe.py) | Is the PHY's power histogram reachable through the USB register window? | **partly answered** — the window is mapped, the histogram is not at mt7915's address |
| [`ipi_hist_cmd.py`](ipi_hist_cmd.py) | Will `RDD_IPI_HIST_CTRL` (0xa3) return a noise floor? | **open** — transport works, the sampler stays idle |
| [`mcu_command_probe.py`](mcu_command_probe.py) | Which MCU commands does this firmware actually implement? | **answered** — the refusal reply identifies them |
| [`mib_offset_sweep.py`](mib_offset_sweep.py) | Which MIB counter offsets does this chip accept? | **answered** — 19 of them, its own numbering |

## Running these

They need an attached adapter and the project venv, and they pin the USB id because two
adapters are usually attached here:

```bash
MT76_USB_ID=0e8d:7961 ./.venv/bin/python research/mib_offset_sweep.py
MT76_USB_ID=0e8d:7961 ./.venv/bin/python research/mcu_command_probe.py
MT76_USB_ID=0e8d:7961 ./.venv/bin/python research/ipi_hist_cmd.py
MT76_USB_ID=0e8d:7961 ./.venv/bin/python research/ipi_probe.py --band 5GHz --channel 36
```

## Rules

- **Passive receive only, unless the script says otherwise in its docstring and the user has
  agreed.** `ipi_hist_cmd.py` and `mcu_command_probe.py` send SET commands; both say so.
- Nothing here is imported by `scripts/` or by the driver. The dependency runs one way.
- A script that stops answering a live question belongs in git history, not in this directory,
  but delete it only once its finding is written down somewhere durable.
- No SSIDs, BSSIDs, or capture payloads in output, same as everywhere else in this repository.
