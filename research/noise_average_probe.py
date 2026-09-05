#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Pinned vendor GET_NOISE query only; no selector/gain setters, TX or raw export.

SW debug ID b1260001 is source-defined idle average power, two signed16 fields.
This does not itself establish calibration, freshness or physical chain mapping.
Three fixed channel states per radio; normal firmware reload after each radio.
"""

import datetime
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m
from research.mt7961_sniffer_trace import RAM_SHA256 as OLD_RAM_SHA256
from research.txpower_register_probe import check_image, read_words

GET_NOISE = 0xB1260001
WINDOWS = (
    (
        "chip_dispatcher",
        0xE0046E00,
        112,
        "dedf8897206b22151c6cc9c08cbddf86f152cd667a05406294b3741fd18e6d71",
    ),
    (
        "sw_debug_branch",
        0xE00470A8,
        32,
        "1614d1ddd0f3e8bf27a5d9aaa2180b028840ae93e72066c8f20c3977973d0617",
    ),
    (
        "query_zero_reply",
        0xE0047230,
        120,
        "dd5ab49b34364ba18fc3876df1368535a5812c08f40f526f5aa0a8c84e9ad52f",
    ),
    (
        "instruction_table",
        0x9171E8,
        4096,
        "d24962d144ffa01a10c0a19b5192e4afa1fccdccc179dfbe126274b2a68cb153",
    ),
)


def verify(dev):
    rows = []
    for name, address, size, expected in WINDOWS:
        digest = hashlib.sha256(read_words(dev, address, size)).hexdigest()
        rows.append(
            {
                "name": name,
                "address": hex(address),
                "bytes": size,
                "sha256": digest,
                "expected_sha256": expected,
                "matches": digest == expected,
            }
        )
    record = read_words(dev, 0x02216034, 8)
    if (
        struct.unpack_from("<H", record)[0] != 0
        or struct.unpack_from("<I", record, 4)[0] != 0xE00470A8
    ):
        raise ValueError("SW debug tag dispatch mismatch")
    if not all(row["matches"] for row in rows):
        raise ValueError("live SW debug query code mismatch")
    return rows


class UnexpectedNoiseEvent(ValueError):
    def __init__(self, raw, chip, reason):
        super().__init__("unexpected noise-average event")
        self.diagnostic = {"parser_reason": reason, "usb_bytes": len(raw)}
        header, eid_at = (44, 36) if chip == m.CHIP_MT7925 else (36, 28)
        if len(raw) < header:
            return
        word = struct.unpack_from("<I", raw)[0]
        size = word & 65535
        if (
            not header <= size <= len(raw)
            or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT
            or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
        ):
            return
        eid = raw[eid_at]
        body = raw[header:size]
        self.diagnostic.update(event_id=eid, sequence=raw[eid_at + 1], body_bytes=len(body))
        if chip == m.CHIP_MT7925 and eid == 1 and len(body) == 8:
            cid, status = struct.unpack("<II", body)
            if cid == 0x0E:
                self.diagnostic.update(command_cid=cid, command_status=status)
        if chip == m.CHIP_MT7925 and eid == 7 and len(body) >= 8:
            tag, length = struct.unpack_from("<HH", body, 4)
            self.diagnostic.update(tag=tag, tag_length=length)
        if chip == m.CHIP_MT7921 and eid == 0x17 and len(body) in (8, 264):
            self.diagnostic["returned_query_id"] = hex(struct.unpack_from("<I", body)[0])


def request(chip):
    if chip == m.CHIP_MT7925:
        return struct.pack("<4xHHII", 0, 12, GET_NOISE, 0)
    if chip == m.CHIP_MT7921:
        # CMD_SW_DBG_CTRL: two u32 fields plus64 zero debug-count words.
        return struct.pack("<II256x", GET_NOISE, 0)
    raise ValueError("only pinned MT7961/MT7925 GET_NOISE layouts")


def summarize(raw, chip, sequence):
    request(chip)
    header, eid_at, eid = (44, 36, 7) if chip == m.CHIP_MT7925 else (36, 28, 0x17)
    if len(raw) < header:
        raise ValueError("short noise-average event")
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if (
        not header <= size <= len(raw)
        or (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT
        or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
        or raw[eid_at] != eid
        or raw[eid_at + 1] != sequence
    ):
        raise ValueError("not matching noise-average event")
    body = raw[header:size]
    if chip == m.CHIP_MT7925:
        if len(body) != 16 or body[:4] != bytes(4) or struct.unpack_from("<HH", body, 4) != (0, 12):
            raise ValueError("unexpected UNI noise-average body")
        body = body[8:]
    elif len(body) not in (8, 264):
        raise ValueError("unexpected legacy noise-average body")
    query_id, value = struct.unpack_from("<II", body)
    if query_id != GET_NOISE:
        raise ValueError("noise-average query ID mismatch")
    return {
        "event_id": eid,
        "body_bytes": size - header,
        "query_id": hex(query_id),
        "average_power_raw_i16": list(struct.unpack("<hh", struct.pack("<I", value))),
        "calibrated": False,
    }


def query(dev):
    payload = request(dev.CHIP)
    if dev.CHIP == m.CHIP_MT7925:
        # This library suppresses CHIP_CONFIG ACK, including QUERY => option2.
        # Do not infer equivalence to Linux's comparison of the full cmd word.
        if dev.uni_option(0x0E, True) != 2:
            raise ValueError("explicit CHIP_CONFIG QUERY option2 required")
        raw = dev.mcu_uni(0x0E, payload, query=True, timeout=1000)
    else:
        raw = dev.mcu_cmd_word(m.MCU_CE_CMD(0xC4) | m.MCU_CMD_FIELD_QUERY, payload, timeout=1000)
    try:
        return summarize(raw, dev.CHIP, dev.msg_seq)
    except ValueError as exc:
        raise UnexpectedNoiseEvent(raw, dev.CHIP, str(exc)) from exc


def main():
    out = {"date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "radios": []}
    for uid in ("0e8d:7961", "0846:9072"):
        row = {"usb_id": uid, "samples": []}
        out["radios"].append(row)
        with m.open_device(uid) as dev:
            images = m.load_firmware(dev.CHIP, m.firmware_dir())
            row["firmware_sha256"] = [hashlib.sha256(b).hexdigest() for b in images]
            if dev.CHIP == m.CHIP_MT7925:
                check_image(images[1])
            elif row["firmware_sha256"][1] != OLD_RAM_SHA256:
                raise ValueError("pinned legacy RAM required")

            def boot(dev=dev, images=images):
                dev.bringup(*images, log=lambda *_: None)
                dev.set_monitor_mode()
                dev.set_sniffer(True)
                dev.tune("2.4GHz", 6, 6, 20)

            try:
                boot()
                if dev.CHIP == m.CHIP_MT7925:
                    row["code"] = verify(dev)
                for channel in (6, 36, 6):
                    dev.tune("2.4GHz" if channel == 6 else "5GHz", channel, channel, 20)
                    time.sleep(0.25)
                    sample = {"channel": channel, "queries": []}
                    row["samples"].append(sample)
                    for _ in range(2):
                        sample["queries"].append(query(dev))
                        time.sleep(0.05)
                row["alive_after"] = dev.alive()
            except Exception as exc:
                row["error_type"] = type(exc).__name__
                if isinstance(exc, UnexpectedNoiseEvent):
                    row["unexpected_event"] = exc.diagnostic
                try:
                    row["alive_after"] = dev.alive()
                except Exception:
                    row["alive_after"] = False
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
