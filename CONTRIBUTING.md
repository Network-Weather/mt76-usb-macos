# Contributing

Thanks for your interest. This project is a userspace driver for one chipset family
(MediaTek MT7921 over USB) on macOS. It is **research-grade** and maintained
best-effort.

## Ground rules

- **Keep the driver derivation honest.** `mt7921u.py` and `rxd.py` are transcribed from
  `openwrt/mt76` (BSD-3-Clause-Clear). If you add or fix a register, MCU command, or
  descriptor field, cite the upstream source file inline the way the existing code does,
  and note the mt76 commit you referenced. See [NOTICE.md](NOTICE.md) for the pinned
  baseline commit; diff forward from it.
- **Never commit firmware.** The MediaTek blobs are licensed and fetched at runtime by
  `setup.sh`. `.gitignore` blocks `*.bin`; keep it that way.
- **No hardware-only tests in CI.** The test suite must pass with no adapter attached and
  no firmware present. Put hardware-dependent checks behind a skip or in an example, not
  in `tests/`.
- **Transmit responsibly.** The injection path is rate-limited and can destabilize the
  MCU under sustained load. Do not present it as a dependable transmitter, and do not add
  functionality whose primary purpose is to disrupt networks you do not own.

## Before opening a PR

```bash
ruff check .
pytest -q
```

Describe what you changed, why, and (for driver changes) the upstream mt76 source you
checked against.
