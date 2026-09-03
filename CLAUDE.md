# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A userspace, libusb-based monitor-mode driver for the MediaTek MT7921AU (USB `0e8d:7961`,
e.g. ALFA AWUS036AXML) and MT7925U (e.g. Netgear Nighthawk A9000, `0846:9072`) on macOS.
Passive 2.4/5/6 GHz capture to radiotap pcap, 160 MHz on the MT7925; not a network
interface. The code is a transcription of the BSD-3-Clause-Clear
[openwrt/mt76](https://github.com/openwrt/mt76) MT7921 and MT7925 USB paths at commit
`c5a3bd91` (a checkout lives at `~/dev/mt76` on the reference host).
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

Hardware runs (attached adapter required; firmware dir overridable with `MT76_FW_DIR`; with two
adapters attached, pick one with `MT76_USB_ID=vvvv:pppp`):

```bash
./.venv/bin/python scripts/usb_descriptors.py --chip-id    # what the driver sees; no firmware needed
./.venv/bin/python scripts/firmware_boot.py --rx 5          # boot + receive census, either chip
./.venv/bin/python scripts/hardware_smoke.py --plan all   # redacted; exit 0 pass, 1 fail, 2 inconclusive, 3 unsupported
./.venv/bin/python examples/scan.py [2.4|5|6|all]
./.venv/bin/python examples/sniff_to_pcap.py <chan> <secs> [out.pcap] [2.4GHz|5GHz|6GHz]
./c/mt7921_smoke --plan quick --fw firmware [--usb-id vvvv:pppp]   # C driver, either chip
```

## Architecture

Four flat modules, no package:

- `mt7921u.py` is three stacked classes. `Mt7921u` owns libusb: vendor control transfers,
  register `rr`/`wr`/`rmw`, bulk I/O. `Mt7921uMcu` adds MCU TXD framing, sequence numbers,
  and the firmware-download primitives. `Mt7921uDevice` adds DMA init and `bringup()`.
- **Most `Mt7921uDevice` methods are not in the class body.** They are module-level
  `_name` functions bound afterward with `Mt7921uDevice.name = _name`, grouped by themed
  banner sections (reset, MCU ext/CE commands, RX filter, monitor mode, UNI/sniffer,
  efuse, TX, telemetry). `grep 'def set_sniffer'` finds nothing; grep `_set_sniffer` or
  the binding line. This runtime attachment is why mypy is not gated yet
  ([docs/QUALITY.md](docs/QUALITY.md)); ROADMAP R4 is the planned fix.
- Chip-specific MCU geometry lives in class attributes on `Mt7921uMcu`/`Mt7921uDevice`
  (`TXD1`, `MCU_RXD_LEN`, `RXD_SEQ_OFFSET`, `RXD_STATUS_OFFSET`, `WFSYS_*`, `uni_option()`,
  `post_firmware_init()`), with MT7921 values as defaults. `mt7925u.py` is `Mt7925uDevice`,
  a subclass overriding those for connac3 plus UNI-encoded capability/efuse commands; it is
  declared after the bindings, so it inherits every bound method. `open_device()` in
  `mt7921u.py` returns the right class for the attached USB id. `tests/golden_mt7921_frames.json`
  freezes the MT7921 on-wire frames; regenerate it only for a deliberate wire change.
- `rxd.py` is pure Python with no USB dependency: connac2 RX descriptor `decode()`,
  `parse_80211()` and IE parsers (RSN, 802.11k/v/r, Multi-AP, mesh), PHY rate/airtime,
  A-MPDU aggregation tracking. Its tests need no fakes at all.
- `rxd_connac3.py` is the connac3 (MT7925) `decode()`, same dict keys, reusing everything in
  `rxd.py` below the descriptor. Callers get the right one from `mt7921u.decoder_for(dev)`.

Capture pipeline, in the order the examples call it:
`dev = open_device()` → `load_firmware(dev.CHIP)` → `bringup(patch, ram)` (ends by pushing
efuse calibration, without which 5/6 GHz are silent) → `set_monitor_mode()` →
`set_sniffer(True)` → per channel `tune(band, control, center, width_mhz)` (MT7921:
`set_chan_info` + `config_sniffer`; MT7925: `config_sniffer` only) → `rx_read()` →
`decoder_for(dev)(raw)` → `rxd.parse_80211(frame)`.

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
  rate-limited; only 60 spaced frames have ever been sent here and sustained transmit is
  untested. Do not extend it toward reliability or
  present it as dependable.
- Do not promote anything from the "previously observed" or "untested" lists in
  [docs/TESTING.md](docs/TESTING.md) to a claim without adding a dated result, test bed,
  command, and acceptance criterion there. A quiet channel is not a driver failure.
- Supported devices are the `SUPPORTED_DEVICES` table (MT7921U `0e8d:7961`, MT7925U
  `0846:9072` validated; other MT7925 ids listed but untested); the Wi-Fi interface comes from
  the descriptors. Adding a USB ID, band, width, or chip requires dated hardware evidence first
  ([ROADMAP.md](ROADMAP.md) decision rules).
- This repository is the instrument, not a survey product. Generic probes and decoders belong
  here; site-survey orchestration, place or room naming, network-specific verdict rules, and
  anything that identifies a real network (SSIDs, BSSIDs, AP names, controller settings) do
  not. Evidence in docs stays chip-generic.

## Review calibration

- Base the review verdict on merge risk, not on whether any improvement can still be found. A
  clean review is a valid outcome; do not manufacture requested changes to demonstrate rigor.
- Separate must-fix findings from optional follow-ups. Correctness failures on supported paths,
  security or privacy regressions, data loss, broken builds or tests, and violations of an
  explicit public contract normally block. Narrow edge cases, diagnostic precision, stronger
  future-proofing, and editorial improvements normally do not unless they materially mislead a
  user or violate an explicit acceptance criterion.
- Severity and disposition are related but distinct. For every finding, state the triggering
  conditions, likely frequency, user impact, and available mitigation; then say explicitly
  whether it should block the merge or be tracked afterward.
- On a re-review, first verify that earlier blockers are resolved and avoid expanding scope merely
  because the original issues are gone. Raise a newly discovered blocker only when its concrete
  risk justifies delaying the change.
- Calibrate the final recommendation to the whole evidence set: implementation risk, test and
  sanitizer results, CI status, hardware or integration evidence where applicable, and remaining
  uncertainty. When the remaining risk is bounded and non-critical, approve with clearly labeled
  follow-ups instead of requesting changes.
