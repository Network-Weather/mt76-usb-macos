#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read source-defined per-rate power reports on both dongles, without TX.

Six or seven bounded normal-mode channel/width settings per radio, then reload.
MT7961 CE d0 and MT7925 UNI2b/tag7 are report operations, not power setters.
No EEPROM/efuse, calibration, power-limit or direct-register writes. Reported
table values are raw firmware state, not independently measured radiated power.
"""

import argparse
import datetime
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m

# mt76 c5a3bd91 mt7921/mt7921.h and mt7925/mt7925.h, declaration order.
LEGACY_GROUPS = (
    ("cck", 4),
    ("ofdm", 8),
    ("ht20", 8),
    ("ht40", 9),
    ("vht20", 12),
    ("vht40", 12),
    ("vht80", 12),
    ("vht160", 12),
    ("he26", 12),
    ("he52", 12),
    ("he106", 12),
    ("he242", 12),
    ("he484", 12),
    ("he996", 12),
    ("he996x2", 12),
)
EHT_GROUPS = tuple(
    (name, 16)
    for name in (
        "eht26",
        "eht52",
        "eht106",
        "eht242",
        "eht484",
        "eht996",
        "eht996x2",
        "eht996x4",
        "eht26_52",
        "eht26_106",
        "eht484_242",
        "eht996_484",
        "eht996_484_242",
        "eht996x2_484",
        "eht996x3",
        "eht996x3_484",
    )
)
PLAN = ((6, 6, 20), (6, 8, 40), (6, 6, 20), (36, 36, 20), (149, 149, 20), (6, 6, 20))
WIDTH_CACHE_PLAN = (
    (6, 6, 20),
    (36, 36, 20),
    (36, 38, 40),
    (6, 6, 20),
    (6, 8, 40),
    (36, 36, 20),
    (6, 6, 20),
)


def request(chip):
    if chip == m.CHIP_MT7925:
        # Exact Linux get_txpwr_info: format0, category2, band0, SET/ACK envelope.
        return struct.pack("<4xHH4B", 7, 8, 0, 2, 0, 0)
    if chip == m.CHIP_MT7921:
        return bytes(8)  # ver/action/len/dbdc_idx/reserved all zero
    raise ValueError("only MT7961/MT7925 power-report layouts")


def groups(values, layout):
    if len(values) != sum(count for _, count in layout):
        raise ValueError("power table length mismatch")
    out, offset = {}, 0
    for name, count in layout:
        out[name] = list(values[offset : offset + count])
        offset += count
    return out


def summarize(raw, chip, seq):
    request(chip)
    header, eid_offset, expected_eid = (44, 36, 0x2A) if chip == m.CHIP_MT7925 else (36, 28, 0xD0)
    if len(raw) < header:
        raise ValueError("short power-report event")
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if (
        not header <= size <= len(raw)
        or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT
        or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
        or raw[eid_offset] != expected_eid
        or raw[eid_offset + 1] != seq
    ):
        raise ValueError("not a matching power-report event")
    body = raw[header:size]
    out = {"event_id": expected_eid, "body_bytes": len(body)}
    if chip == m.CHIP_MT7925:
        # Observed pinned event uses payload-only TLV length841, not845.
        if (
            len(body) != 849
            or body[:4] != bytes(4)
            or struct.unpack_from("<HH", body, 4) != (5, 841)
            or body[8] != 5
            or body[9] != 0
            or body[11] != 1
        ):
            raise ValueError("unexpected MT7925 power-report shape")
        values = struct.unpack_from("<834b", body, 12)
        layout = LEGACY_GROUPS + EHT_GROUPS
        out.update(
            category=body[8],
            firmware_band=body[9],
            channel_band_raw=body[10],
            format_raw=body[11],
            selected_band_power_raw=groups(values[::2], layout),
            other_band_distinct_raw=sorted(set(values[1::2])),
            max_bound_raw=struct.unpack_from("<b", body, 846)[0],
            min_bound_raw=struct.unpack_from("<b", body, 847)[0],
            tail_byte_raw=body[848],
        )
    else:
        if (
            len(body) != 494
            or body[:2] != bytes(2)
            or struct.unpack_from("<H", body, 2)[0] != 494
            or body[5:8] != bytes(3)
        ):
            raise ValueError("unexpected MT7961 power-report shape")
        out["reported_channel"] = body[4]
        out["planes"] = {}
        for i, name in enumerate(("user", "eeprom", "mac")):
            at = 8 + 162 * i
            out["planes"][name] = {
                "reported_channel": body[at],
                "power_raw_u8": groups(body[at + 1 : at + 162], LEGACY_GROUPS),
            }
    return out


def query(dev):
    payload = request(dev.CHIP)
    if dev.CHIP == m.CHIP_MT7925:
        if dev.uni_option(0x2B, False) != 7:
            raise ValueError("source-shaped SET/ACK envelope required for read-only show tag")
        raw = dev.mcu_uni(0x2B, payload, query=False, timeout=1000)
    else:
        raw = dev.mcu_cmd_word(m.MCU_CE_CMD(0xD0), payload, timeout=1000)
    return summarize(raw, dev.CHIP, dev.msg_seq)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("baseline", "width-cache"), default="baseline")
    args = parser.parse_args()
    plan = WIDTH_CACHE_PLAN if args.suite == "width-cache" else PLAN
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "suite": args.suite,
        "radios": [],
    }
    for uid in ("0e8d:7961", "0846:9072"):
        row = {"usb_id": uid, "samples": []}
        out["radios"].append(row)
        with m.open_device(uid) as dev:
            images = m.load_firmware(dev.CHIP, m.firmware_dir())
            row["firmware_sha256"] = [hashlib.sha256(b).hexdigest() for b in images]

            def boot(dev=dev, images=images):
                dev.bringup(*images, log=lambda *_: None)
                dev.set_monitor_mode()
                dev.set_sniffer(True)
                dev.tune("2.4GHz", 6, 6, 20)

            try:
                boot()
                for primary, center, width in plan:
                    dev.tune("2.4GHz" if primary == 6 else "5GHz", primary, center, width)
                    time.sleep(0.05)
                    row["samples"].append(
                        {
                            "primary": primary,
                            "center": center,
                            "width_mhz": width,
                            "report": query(dev),
                        }
                    )
                row["alive_after"] = dev.alive()
            except Exception as exc:
                row["error_type"] = type(exc).__name__
            finally:
                try:
                    boot()
                    row["cleanup_reload_alive"] = dev.alive()
                except Exception as exc:
                    row["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int(
        any(
            "error_type" in r or not r.get("alive_after") or not r.get("cleanup_reload_alive")
            for r in out["radios"]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
