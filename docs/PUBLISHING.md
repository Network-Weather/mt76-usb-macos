# Publication checklist

The repository is suitable for a research-grade `0.1.0` publication, not a production
driver claim. Before making it public or tagging a release:

- verify the macOS-only GitHub Actions matrix is green;
- run `pip-audit -r requirements.txt` against the current Python vulnerability database;
- review [TESTING.md](TESTING.md) and keep its current/previous/untested distinctions;
- review [../RELATED_WORK.md](../RELATED_WORK.md) and retain the direct transcription source,
  in-tree Linux integration, firmware source, and both peer projects in release notes and
  repository-facing documentation;
- retain the exact upstream copyright notices in `LICENSE` and `NOTICE.md`, distinguish the
  pinned openwrt/mt76 transcription source from its in-tree Linux integration, and pin any peer
  claim to the revision actually reviewed;
- confirm firmware blobs, pcaps, SSIDs, MAC addresses, and serial numbers are absent from
  the Git history, release assets, and issue attachments;
- enable GitHub Issues and private vulnerability reporting;
- add the GitHub description and topics below;
- protect `main` by requiring CI and review for future changes; and
- tag `v0.1.0` only after the release commit itself has passed
  `scripts/hardware_smoke.py --plan all`. Retain its redacted JSON result with the release
  records. Do not publish the ambient pcap; retain only its hash and aggregate counts.

The `0.1.0` end-user installation is a Git clone plus `setup.sh`; publish a GitHub source
release. The wheel contains the two importable Python modules but intentionally does not install
firmware or hardware scripts. Do **not** publish it to PyPI as a turnkey application until the
firmware acquisition, command-line entry points, and supported Python API have a stable install
contract. Building the wheel in CI currently checks packaging metadata and clean module import.

## GitHub discovery metadata

The description and topics below were configured on the still-private GitHub repository on
2026-09-02. Verify that they remain present when visibility changes.

Suggested repository description:

> Userspace MediaTek mt76 USB driver for macOS: MT7921U (AWUS036AXML) working, MT7925U (A9000, Wi-Fi 7, 160 MHz) in progress. Passive 2.4/5/6 GHz radiotap capture via libusb, no kext or VM.

Suggested topics:

`macos`, `apple-silicon`, `mt76`, `mt7921au`, `mt7921u`, `mt7961`, `mt7925`, `mt7925u`, `awus036axml`,
`nighthawk-a9000`, `wifi-6e`, `wifi-7`, `6ghz`, `monitor-mode`, `packet-capture`, `radiotap`, `wireshark`,
`libusb`, `802-11`, `wireless-research` (GitHub allows 20 topics; `pyusb` was dropped to fit)

Those strings cover the names users actually search: the Linux driver name (`mt7921u`),
the silicon/adapter names (`MT7921AU`, `MT7961`, `AWUS036AXML`), the task (“macOS monitor
mode” / “packet capture”), and the differentiators (“6 GHz”, “Wi-Fi 6E”, “no kext”).

## Positioning

Do not market this as the first native macOS userspace Wi-Fi driver. `wifikit` overlaps on
macOS and MT7921AU, while `wifit3` overlaps on a cross-platform userspace mt76 port. The defensible value
is a compact, auditable Python reference focused on passive tri-band capture and measured
bring-up details. `openwrt/mt76` must be credited as the source implementation and
the in-tree Linux mt76 module as the canonical kernel integration; `linux-firmware` must be
credited as the required firmware source. Link related work; it makes the claim more credible,
not less.

Keep the strong/weak table in [../RELATED_WORK.md](../RELATED_WORK.md#capability-comparison)
current. Every release should state the comparison date, distinguish peer self-reports from
local reproduction, use “not assessed” for unknowns, and avoid turning small size or one
successful hardware run into a blanket reliability claim.
