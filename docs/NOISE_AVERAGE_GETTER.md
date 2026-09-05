# Vendor GET_NOISE: a zero-result stub is not a noise measurement

**The source-defined noise-average getter does not expose a usable measurement
on either pinned firmware.** MT7925 returns two zeros across6→36→6; its verified
QUERY branch explicitly zeros the result without reading PHY noise state.
MT7961 replies with query ID0 rather than the requested ID, so its result is
rejected, not interpreted as a power value.

This is distinct from the [working MT7925 histogram event](MT7925_NOISE_HISTOGRAM.md#one-shot-firmware-event-now-works).
An apparently well-formed debug reply alone does not establish capability.

## Exact source-defined request

Pinned vendor source `8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec` defines
[`CMD_SW_DBGCTL_ADVCTL_GET_ID = 0xb1260000`](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/debug.h#L94).
[`priv_driver_get_noise`](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/os/linux/gl_wext_priv.c#L16556)
adds1, queries with data0, and interprets the result as two signed16 fields
labelled WF0/WF1 idle average power. That source naming does not calibrate a
returned value or establish physical antenna mapping on these firmware images.

The old source command is CE0xc4 with QUERY set. Its
[`CMD_SW_DBG_CTRL`](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_cmd_event.h#L1827)
is264 bytes: ID, zero data and64 zero debug-count words. Only the requested
ID/result could be exported; debug words and USB padding are never retained.
The expected event is0x17. The observed264-byte response instead has ID0.

[`nicUniCmdSwDbgCtrl`](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_uni_cmd_event.c#L1157)
translates this to UNI0x0e/tag0/length12, with a four-byte reserved prefix and
the two u32 fields. The reproducer uses this library's QUERY option2; the
library suppresses ACK for CHIP_CONFIG even when querying. Do not describe
this as proven identical to Linux's comparison of the full command word:
the query bit can affect that equality. No production transport change is made.

MT7925 replies EID7, same sequence, body16, tag0/length12, matching IDb1260001
and data0. Twelve requests across two6→36→6 runs all return `[0, 0]`.
The former prototype's option3 guard rejected locally before sending on MT7925;
that was a probe framing assumption, not a device rejection.

## Why the MT7925 zeros are not measurements

Live four-record tag table GP+14388 = `02216034` maps tag0 to `e00470a8`.
The outer UNI0x0e handler at `e0046e02` uses the standard first TLV at+0x34.
Tag0 reads the requested ID at buffer+0x38 and checks option bit2 at+0x2b.
QUERY goes directly to `e0047230`; the SET dispatch is separate and untested.

The QUERY branch:

1. At `e0047248`, writes **zero to request buffer+0x3c**, the result/data word.
2. Allocates the event and calls the header builder with EID7.
3. Copies12 bytes from request+0x34 to event+0x30: TLV, ID and the zeroed data.
4. Writes tag0/length12 and sends the event at `e004729c`.

There is no ID-selected getter or histogram/PHY read between clearing the data
and copying the reply. This is a generic zero-result QUERY path in this pinned
tag handler, not an inference from repeated zeros. Experimental Andes decoding
remains a static-trace limitation; fixed loaded code/ITB hashes independently
match retained bytes. The verifier makes1092 aligned reads:1090 code/ITB words
and two tag-record words. No firmware code bytes are published.

[`noise_average_probe.py`](../research/noise_average_probe.py) pins both RAM
images, verifies the MT7925 path, and queries only IDb1260001. It stops that
radio's experiment on an invalid event, retains only sanitized mismatch
metadata, checks liveness, and reloads normal firmware. Both radios pass all
alive/reload checks. No TX, selector/gain setter, nonvolatile programming or
raw ambient capture. An old mismatch intentionally makes the process exit
nonzero even when the newer branch is successfully characterized.

[Sanitized results and tag table](../research/evidence/noise-average-getter-2026-09-05.json).
Do not display these zeros as0dB or0dBm, and do not broaden the negative to the
working hardware histogram or unrelated firmware interfaces.
