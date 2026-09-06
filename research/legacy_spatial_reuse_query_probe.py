#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""MT7961 source-defined SR GET subcommands over legacy EXT A8 SET transport.

Pinned gen4m legacy getters use SET framing, but subcommands15/18 only query.
No enable/reset subcommands, TX, RF mode or direct register writes. Getters may
consume shared statistics; exclusive ownership required. Four bounded windows
and full normal reload. Only config/counter fields and aggregate traffic output.
"""

import argparse
import collections
import contextlib
import datetime
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import usb.core

import mt7921u as m
from research.icap_status_probe import event_summary
from research.spatial_reuse_query_probe import INDICATORS


def request(subcommand):
    if type(subcommand) is not int or subcommand not in (15, 18):
        raise ValueError("only source-defined legacy SR GET15/18")
    return bytes([subcommand]) + bytes((20 if subcommand == 15 else 32) - 1)


def summarize(raw, sequence, subcommand):
    request(subcommand)
    event = event_summary(raw, sequence)
    if event is None or not event["sequence_matches"] or event["eid"] != 0xED:
        return None
    size = struct.unpack_from("<I", raw)[0] & 65535
    body = raw[36:size]
    if event["ext_eid"] == 0 and len(body) == 8 and struct.unpack_from("<I", body)[0] == 0xA8:
        return {"command_result_status": struct.unpack_from("<I", body, 4)[0]}
    if event["ext_eid"] != 0xA8:
        return None
    expected_event = 1 if subcommand == 15 else 4
    expected_length = 28 if subcommand == 15 else 32
    out = {"eid": 0xED, "ext_eid": 0xA8, "body_bytes": len(body), "sequence_matches": True}
    if len(body) != expected_length or body[:8] != bytes([expected_event]) + bytes(7):
        return out | {"unrecognized_shape": True}
    out["sr_event_subcommand"] = expected_event
    if subcommand == 15:
        if any(value not in (0, 1) for value in body[8:]):
            raise ValueError("non-boolean capability flag")
        # Pinned firmware returns20 flags, unlike the older legacy12-byte struct.
        # Keep indexes raw; do not mislabel the legacy AGG/MIB offsets8..11.
        out["capability_flags_pinned20"] = list(body[8:])
    else:
        if body[22:24] != bytes(2):
            return out | {"unrecognized_shape": True}
        out["non_srg_inter_ppdu_rcpi_raw"] = body[8]
        out["srg_inter_ppdu_rcpi_raw"] = body[9]
        out["indicators_raw"] = dict(
            zip(INDICATORS, struct.unpack_from("<6H2x2I", body, 10), strict=True)
        )
    return out


def query(dev, subcommand):
    payload = request(subcommand)
    if dev.CHIP != m.CHIP_MT7921:
        raise ValueError("pinned MT7961 only")
    # Deliberately no QUERY flag: exact transport of source-defined legacy GET.
    dev.mcu_cmd_word(m.MCU_EXT_CMD(0xA8), payload, wait=False, timeout=1000)
    sequence = dev.msg_seq
    deadline = time.monotonic() + 0.5
    transfers = 0
    counts = collections.Counter()
    events = []
    while time.monotonic() < deadline and transfers < 128:
        try:
            raw = bytes(dev.rx_read(timeout=30))
        except usb.core.USBTimeoutError:
            continue
        transfers += 1
        decoded = m.decoder_for(dev)(raw)
        if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
            counts[str(decoded.get("phy", {}).get("mode"))] += 1
        event = summarize(raw, sequence, subcommand)
        if event is not None:
            events.append(event)
    return {
        "get_subcommand": subcommand,
        "events": events,
        "good_fcs_frames_by_phy_mode": dict(counts),
        "transfers": transfers,
        "transfer_limit_reached": transfers == 128,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, choices=(1, 36), default=1)
    args = parser.parse_args()
    out = {
        "tool": "legacy_spatial_reuse_query_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": args.channel,
        "transport": "EXT_A8_SET_with_GET15_or_GET18",
        "rows": [],
    }
    with m.open_device("0e8d:7961") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel == 1 else "5GHz", args.channel, args.channel, 20)

        try:
            boot()
            for subcommand in (15, 18, 18, 15):
                out["rows"].append(query(dev, subcommand))
            out["alive_after"] = dev.alive()
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            try:
                boot()
                out["cleanup_reload_alive"] = dev.alive()
            except Exception as exc:
                out["cleanup_error_type"] = type(exc).__name__
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not out.get("cleanup_reload_alive"))


if __name__ == "__main__":
    raise SystemExit(main())
