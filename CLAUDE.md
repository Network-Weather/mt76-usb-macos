# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A userspace, libusb-based monitor-mode driver for the MediaTek MT7921AU (USB `0e8d:7961`,
e.g. ALFA AWUS036AXML) on macOS. Passive 2.4/5/6 GHz capture to radiotap pcap; not a
network interface. The code is a transcription of the BSD-3-Clause-Clear
[openwrt/mt76](https://github.com/openwrt/mt76) MT7921 path at commit `c5a3bd91`.
[README.md](README.md) covers requirements, usage, the endpoint map, the capability
matrix, and the five measured bring-up gotchas; read it before touching the driver.

## Commands

Everything runs through the project venv. Never use a bare `python` or `pip`.

```bash
bash setup.sh                                  # idempotent: .venv + pyusb, fetch pinned firmware into ./firmware
./.venv/bin/pip install -e '.[dev]'            # pytest, ruff, build

./scripts/check.sh                             # the full gate; run before every PR
./.venv/bin/python -m pytest -q                # offline tests only (no adapter, no firmware)
./.venv/bin/python -m pytest tests/test_decode.py::test_name -q
./.venv/bin/python -m ruff format . && ./.venv/bin/python -m ruff check .
./.venv/bin/python scripts/check_docs.py       # local Markdown links/anchors + JSON (covers this file too)
```

`check.sh` = ruff format/lint, `check_docs.py`, `bash -n setup.sh` (+ shellcheck if
installed), pytest, `python -m build --no-isolation`, `pip check`. CI runs the same minus shellcheck on
`macos-14`/`macos-26` with Python 3.10 and 3.14.

Hardware runs (attached adapter required; firmware dir overridable with `MT7921_FW_DIR`):

```bash
./.venv/bin/python scripts/hardware_smoke.py --plan all   # redacted; exit 0 pass, 1 fail, 2 inconclusive, 3 unsupported
./.venv/bin/python examples/scan.py [2.4|5|6|all]
./.venv/bin/python examples/sniff_to_pcap.py <chan> <secs> [out.pcap] [2.4GHz|5GHz|6GHz]
```

## Architecture

Two flat modules, no package:

- `mt7921u.py` is three stacked classes. `Mt7921u` owns libusb: vendor control transfers,
  register `rr`/`wr`/`rmw`, bulk I/O. `Mt7921uMcu` adds MCU TXD framing, sequence numbers,
  and the firmware-download primitives. `Mt7921uDevice` adds DMA init and `bringup()`.
- **Most `Mt7921uDevice` methods are not in the class body.** They are module-level
  `_name` functions bound afterward with `Mt7921uDevice.name = _name`, grouped by themed
  banner sections (reset, MCU ext/CE commands, RX filter, monitor mode, UNI/sniffer,
  efuse, TX, telemetry). `grep 'def set_sniffer'` finds nothing; grep `_set_sniffer` or
  the binding line. This runtime attachment is why mypy is not gated yet
  ([docs/QUALITY.md](docs/QUALITY.md)); ROADMAP R4 is the planned fix.
- `rxd.py` is pure Python with no USB dependency: RX descriptor `decode()`, `parse_80211()`
  and IE parsers (RSN, 802.11k/v/r, Multi-AP, mesh), PHY rate/airtime, A-MPDU aggregation
  tracking. Its tests need no fakes at all.

Capture pipeline, in the order the examples call it:
`bringup(patch, ram)` (ends by pushing efuse calibration, without which 5/6 GHz are silent)
→ `set_monitor_mode()` → `set_sniffer(True)` → per channel `set_chan_info(...)` +
`config_sniffer(...)` → `rx_read()` → `rxd.decode(raw)` → `rxd.parse_80211(frame)`.

Tests fake the USB boundary by subclassing `Mt7921uMcu` and overriding `bulk_out` /
`mcu_wait` (see `RecordingMcu` in `tests/test_driver.py`). `conftest.py` puts the repo
root on `sys.path`. `scripts/hardware_smoke.py` is imported by an offline test, so keep
its pure helpers importable without hardware.

The version is declared twice, `mt7921u.__version__` and `pyproject.toml`; a test asserts
they match and CI checks the git tag against them on release. Bump both plus CHANGELOG.

## Rules specific to this repo

Each is documented in full elsewhere; these are the ones that bite.

- Never commit `firmware/` or any `*.bin`. The blobs are licensed and fetched by
  `setup.sh` with pinned SHA-256s ([NOTICE.md](NOTICE.md)).
- Nothing under `tests/` may require an adapter or firmware. Hardware checks go in
  `scripts/` or `examples/`.
- Any register, MCU command, or descriptor change cites the upstream mt76 file and symbol
  inline, diffed forward from baseline commit `c5a3bd91` ([CONTRIBUTING.md](CONTRIBUTING.md)).
- wifikit (MIT) and wifit3 (GPL-2.0) are read-only references. Reimplement independently;
  do not translate their code into this BSD repository ([RELATED_WORK.md](RELATED_WORK.md)).
- Captures are sensitive. No pcaps, SSIDs, BSSIDs, client MACs, or USB serials in the
  repo, tests, issues, or PRs. `scan.py` output is sensitive; `hardware_smoke.py` output
  is redacted by design.
- Injection (`inject`, `_build_txwi`, `examples/inject_demo.py`) is experimental and
  rate-limited; sustained TX can panic the MCU. Do not extend it toward reliability or
  present it as dependable.
- Do not promote anything from the "previously observed" or "untested" lists in
  [docs/TESTING.md](docs/TESTING.md) to a claim without adding a dated result, test bed,
  command, and acceptance criterion there. A quiet channel is not a driver failure.
- Only `0e8d:7961` with Wi-Fi on interface 3 is supported; adding a USB ID, band, width,
  or chip requires dated hardware evidence first ([ROADMAP.md](ROADMAP.md) decision rules).
