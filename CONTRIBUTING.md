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
- **Check the existing ecosystem.** Read [RELATED_WORK.md](RELATED_WORK.md) before claiming
  a new mechanism. If mt76, linux-firmware, wifikit, wifit3, an issue, or another project
  informed a change, cite the exact revision/file/symbol or experiment. Comparative evidence
  does not become a local hardware result without being reproduced here.
- **Preserve license boundaries.** The transcribed mt76 paths are BSD-3-Clause-Clear and their
  exact notices are retained in [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). wifikit is MIT;
  wifit3 is GPL-2.0. Ideas and observed behavior can motivate an independent experiment, but do
  not translate peer code into this BSD repository without an explicit license review and an
  updated provenance record.
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
./scripts/check.sh
```

The script checks Ruff formatting and lint, shell syntax (plus ShellCheck when installed),
all offline tests, and both distribution formats. See [docs/QUALITY.md](docs/QUALITY.md) for
what these checks establish and the quality gaps they do not cover.

Describe what you changed, why, and (for driver changes) the upstream mt76 source you
checked against. If you exercised hardware, use the evidence format in
[docs/TESTING.md](docs/TESTING.md), preferably attach the redacted output from
`scripts/hardware_smoke.py`, and state exactly what was not tested. Never attach its ambient
traffic or an unredacted pcap.
