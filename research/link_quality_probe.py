#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Six normal-mode UNI23 link-quality reads, no association or TX.

Readiness gates all scalar interpretation. Firmware hardcodes medium-busy0;
it is not a channel-load measurement. Unknown/unready bytes are never exported.
Abort on a decreased command-pool count, and always reload normal firmware.
"""

import datetime
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import mt7925_diagnostic_stats_probe as diag
from research import mt7925_thermal_probe as thermal
from research import rmac_ics_probe as mac
from research.txpower_register_probe import check_image, m


def request():
    return struct.pack("<4xHH", 1, 4)


def parse(body):
    if len(body) != 40 or struct.unpack_from("<HH", body, 4) != (1, 36):
        raise ValueError("pinned four-row link-quality shape required")
    rows = []
    for slot in range(4):
        offset = 8 + slot * 8
        ready = body[offset + 5] == 1
        row = {"slot": slot, "ready": ready, "medium_busy_available": False}
        if ready:
            row.update(
                rssi_encoding_signed8=struct.unpack_from("<b", body, offset)[0],
                link_speed_raw_u16=struct.unpack_from("<H", body, offset + 2)[0],
                medium_busy_is_zero=(body[offset + 4] == 0),
            )
        rows.append(row)
    return {"tag": 1, "tlv_bytes": 36, "rows": rows}


def query(dev):
    dev.mcu_uni(0x23, request(), query=True, wait=False)
    sequence, start = dev.msg_seq, time.monotonic()
    received = 0
    for _ in range(512):
        if time.monotonic() - start > 0.7:
            break
        for ep in (dev.ep_in_pkt_rx, dev.ep_in_cmd_resp):
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            decoded = m.decoder_for(dev)(raw)
            if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
                received += 1
            event = mac.event_body(raw)
            if event and event[:2] == (0x23, sequence):
                return {
                    "sequence": sequence,
                    "event": parse(event[2]),
                    "ordinary_good_during_query": received,
                }
    raise ValueError("no matched link-quality event")


def main():
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transmissions": 0,
        "channel": 6,
        "queries": [],
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        check_image(images[1])

        def boot():
            dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            boot()
            out["tag_table_matches"] = diag.verify_table(dev)
            out["pool_counts_initial"] = diag.pool_counts(dev)
            for _ in range(6):
                before = diag.pool_counts(dev)
                row = query(dev)
                after = diag.pool_counts(dev)
                row.update(pool_counts_before=before, pool_counts_after=after)
                out["queries"].append(row)
                if any(after[k] < before[k] for k in before):
                    raise ValueError("pool depletion; no further link-quality requests")
                time.sleep(0.1)
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                out["thermal_after"] = thermal.query(dev, 0)
            except Exception as exc:
                out["thermal_error_type"] = type(exc).__name__
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
                out["pool_counts_after_reload"] = diag.pool_counts(dev)
            except Exception:
                out["cleanup_reload_alive"] = False
    print(json.dumps(out, indent=2))
    return int(
        "error_type" in out or "thermal_error_type" in out or not out["cleanup_reload_alive"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
