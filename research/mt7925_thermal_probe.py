#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Read MT7925 analog-die temperature and raw ADC, without thermal controls.

Pinned UNI35 tag0, band0, actions0/1 only. No protection overrides, TX, direct
register access or undocumented sensor indices. Normal firmware reload on exit.
"""

import argparse
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mt7921u as m
from mt76_measurements import (
    ThermalAction,
    build_thermal_request,
    parse_thermal_event,
    read_thermal,
)


def request(action):
    if type(action) is not int or action not in (0, 1):
        raise ValueError("only temperature0 and raw ADC1 queries allowed")
    return build_thermal_request(m.CHIP_MT7925, ThermalAction(action))


def summarize(raw, seq, action):
    request(action)
    value = parse_thermal_event(m.CHIP_MT7925, raw, seq, ThermalAction(action))
    return _summary(value, action)


def _summary(value, action):
    result = {"action": action, "band": 0, "event_tag": 0, "sensor_result_raw_u32": value}
    if action == 0:
        result["reported_temperature_c"] = value if value < 0x80000000 else value - 0x100000000
    else:
        result["units"] = "raw ADC code; conversion not calibrated"
    return result


def query(dev, action):
    request(action)
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(0x35, True) != 3:
        raise ValueError("MT7925 with explicit QUERY_ACK option3 required")
    return _summary(read_thermal(dev, ThermalAction(action)).raw, action)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "MT7925 analog-die temperature/ADC queries only, no thermal controls or TX",
        "samples": [],
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())
        out["firmware_sha256"] = [hashlib.sha256(image).hexdigest() for image in images]
        try:
            dev.bringup(*images, log=lambda *_: None)
            for action in (0, 1, 0):
                out["samples"].append(query(dev, action))
                time.sleep(0.1)
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                dev.bringup(*images, log=lambda *_: None)
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
