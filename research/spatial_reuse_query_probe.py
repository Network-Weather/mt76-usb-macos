#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""MT7925 read-only spatial-reuse capability and indicator queries.

Pinned gen4m UNI25 tagsC0/CB, exact QUERY_ACK3. Replies are unsolicited EID25,
tagsC0/C9 (request CB is NOT event C9; never send the C9 reset command).
No SR enable, threshold, reset, TX, RF mode or direct register writes.
Four half-second/128-transfer windows, then normal firmware reload.
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

CAPABILITIES = (
    "sr_enable",
    "srg_enable",
    "non_srg_enable",
    "single_mpdu_rtscts_enable",
    "header_duration_enable",
    "txop_duration_enable",
    "non_srg_inter_ppdu_preserve",
    "srg_inter_ppdu_preserve",
    "single_mpdu_no_trigger_enable",
    "srg_bssid_order",
    "cts_after_rts",
    "srp_old_rxv_enable",
    "srp_new_rxv_enable",
    "srp_data_only_enable",
    "fixed_rate_sr_receive_enable",
    "wtbl_sr_receive_enable",
    "sr_remaining_time_enable",
    "protection_in_sr_window_disable",
    "txcmd_dl_rate_select_enable",
    "ampdu_tx_count_enable",
)
INDICATORS = (
    "non_srg_valid",
    "srg_valid",
    "intra_bss_ppdu",
    "inter_bss_ppdu",
    "non_srg_ppdu_valid",
    "srg_ppdu_valid",
    "sr_ampdu_mpdu",
    "sr_ampdu_mpdu_acked",
)


def request(tag):
    if type(tag) is not int or tag not in (0xC0, 0xCB):
        raise ValueError("only read-only SR CAP/IND command tags C0/CB")
    return struct.pack("<4xHH4x", tag, 8)


def summarize(raw, seq, tag):
    request(tag)
    if len(raw) < 44:
        return None
    word = struct.unpack_from("<I", raw)[0]
    size = word & 65535
    if (
        (word >> 27) & 31 != m.PKT_TYPE_RX_EVENT
        or (word >> m.RXD0_PKT_FLAG_SHIFT) & m.RXD0_PKT_FLAG_MASK == m.PKT_FLAG_NORMAL_MCU
        or not 44 <= size <= len(raw)
    ):
        return None
    body = raw[44:size]
    if (
        raw[36] == 1
        and raw[37] == seq
        and len(body) >= 8
        and struct.unpack_from("<I", body)[0] == 0x25
    ):
        return {"command_result_status": struct.unpack_from("<I", body, 4)[0]}
    if raw[36] != 0x25 or raw[37] != 0:
        return None
    event_tag = 0xC0 if tag == 0xC0 else 0xC9
    out = {"eid": 0x25, "sequence": 0, "body_bytes": len(body)}
    if (
        len(body) != 28
        or body[:4] != bytes(4)
        or struct.unpack_from("<HH", body, 4) != (event_tag, 24)
    ):
        return out | {"unrecognized_shape": True}
    out["event_tag"] = event_tag
    if tag == 0xC0:
        if any(value not in (0, 1) for value in body[8:28]):
            raise ValueError("unexpected SR capability flag")
        out["capabilities_raw"] = dict(zip(CAPABILITIES, body[8:28], strict=True))
    else:
        out["indicators_raw"] = dict(
            zip(INDICATORS, struct.unpack_from("<6H2I", body, 8), strict=True)
        )
    return out


def query(dev, tag):
    payload = request(tag)
    if dev.CHIP != m.CHIP_MT7925 or dev.uni_option(0x25, True) != 3:
        raise ValueError("MT7925 explicit QUERY_ACK3 required")
    dev.mcu_uni(0x25, payload, query=True, wait=False, timeout=1000)
    sequence = dev.msg_seq
    deadline = time.monotonic() + 0.5
    transfers = 0
    frames = collections.Counter()
    events = []
    while time.monotonic() < deadline and transfers < 128:
        try:
            raw = bytes(dev.rx_read(timeout=30))
        except usb.core.USBTimeoutError:
            continue
        transfers += 1
        decoded = m.decoder_for(dev)(raw)
        if decoded and decoded.get("frame") and not decoded.get("fcs_err"):
            frames[str(decoded.get("phy", {}).get("mode"))] += 1
        event = summarize(raw, sequence, tag)
        if event is not None:
            events.append(event)
    return {
        "request_tag": tag,
        "events": events,
        "good_fcs_frames_by_phy_mode": dict(frames),
        "transfers": transfers,
        "transfer_limit_reached": transfers == 128,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, choices=(1, 36), default=1)
    args = parser.parse_args()
    out = {
        "tool": "spatial_reuse_query_probe",
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "channel": args.channel,
        "uni_option": 3,
        "rows": [],
    }
    with m.open_device("0846:9072") as dev:
        images = m.load_firmware(dev.CHIP, m.firmware_dir())

        def boot():
            with contextlib.redirect_stdout(sys.stderr):
                dev.bringup(*images, log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz" if args.channel == 1 else "5GHz", args.channel, args.channel, 20)

        try:
            boot()
            for tag in (0xC0, 0xCB, 0xCB, 0xC0):
                out["rows"].append(query(dev, tag))
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
