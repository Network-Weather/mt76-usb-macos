#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Sixteen bounded known HT8 frames into MT7961 RMAC ICS off/on/off.

Optional previously qualified Group5 report bit; independent exact good-FCS
receipt required for vector pairing. No opaque/ambient exports or calibrated CFO.
"""

import argparse
import collections
import contextlib
import datetime
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import legacy_ics_probe as legacy
from research import normal_phy_counter_probe as counters
from research import phy_tx_probe as phy
from research import rmac_ics_match as matching
from research.noise_self_tx_probe import packet
from research.txpower_register_probe import check_image, m


def own_ics_observation(raw, packets):
    """Source-inspired locations, only for an exact submitted24-byte header.

    P-RXV2 filling is mode dependent: a separate RF-mode cache comparison verifies
    this location; normal-mode controls return all-one fields, not valid CFO/SNR.
    Source masks are intentionally not converted into calibrated units.
    """
    shape = legacy.aggregate_shape(raw)
    if shape != {"type": 12, "bytes": 272, "frame_count": 3}:
        return None
    candidates = [i for i, (payload, _) in packets.items() if raw[120:144] == payload[:24]]
    if len(candidates) != 1:
        return None
    common = struct.unpack_from("<I", raw, 16)[0]
    rcpi = struct.unpack_from("<I", raw, 40)[0]
    p20, p21 = struct.unpack_from("<II", raw, 104)
    cfo = (p20 >> 19) | ((p21 & 127) << 13)
    if cfo & (1 << 19):
        cfo -= 1 << 20
    return {
        "sequence": candidates[0],
        "pairing": "exact submitted MAC header, not a full-payload/FCS verdict",
        "source_crxv_at16_hypothesis": {
            "mode": (common >> 4) & 15,
            "bandwidth_code": (common >> 8) & 7,
        },
        "rcpi_bytes_at40": [rcpi & 255, (rcpi >> 8) & 255],
        "source_prxv2_at104_hypothesis": {"cfo_signed20": cfo, "snr_bits": (p20 >> 13) & 63},
    }


def acquire(tx, rx, packets):
    if len(packets) not in (4, 8):
        raise ValueError("four or eight prepared frames only")
    pending = list(packets.items())
    submitted, good, statuses = [], {}, []
    normal, aggregates = [], []  # Own normal records; opaque ICS stays local only.
    counts = collections.Counter()
    decoder = m.decoder_for(rx)
    expected = {payload: i for i, (payload, _) in packets.items()}
    start = time.monotonic()
    next_tx, attempts = start + 0.03, 0
    while time.monotonic() - start < 0.6 and attempts < 1536:
        now = time.monotonic()
        if len(submitted) < len(pending) and now >= next_tx and now < start + 0.4:
            i, (_, wire) = pending[len(submitted)]
            tx.bulk_out(tx.ep_out_ac_be, wire, 1000)
            submitted.append(i)
            next_tx = time.monotonic() + 0.035
        for dev, ep in ((rx, rx.ep_in_pkt_rx), (tx, tx.ep_in_pkt_rx), (tx, tx.ep_in_cmd_resp)):
            attempts += 1
            try:
                raw = dev.bulk_in(ep, 4096, timeout=1)
            except m.usb.core.USBError as exc:
                if exc.errno == 110 or getattr(exc, "backend_error_code", None) == -7:
                    continue
                raise
            if len(raw) < 4:
                continue
            kind = struct.unpack_from("<I", raw)[0] >> 27
            if dev is tx:
                if kind == 0:
                    statuses.extend(
                        s
                        for s in phy.c3.tx_status(raw)
                        if s["pid"] == 3 and s["sequence"] in submitted
                    )
                continue
            counts[kind] += 1
            decoded = decoder(raw)
            if decoded and not decoded.get("fcs_err"):
                index = expected.get(decoded.get("frame"))
                if index in submitted:
                    good[index] = {
                        k: decoded.get("phy", {}).get(k)
                        for k in ("mode_name", "mcs", "nss", "bw_mhz", "gi", "ldpc")
                    }
                    if len(normal) < matching.LIMIT:
                        normal.append(bytes(raw))
            shape = legacy.aggregate_shape(raw)
            if shape and len(aggregates) < matching.LIMIT:
                aggregates.append(bytes(raw[: shape["bytes"]]))
    return {
        "elapsed_seconds": time.monotonic() - start,
        "attempts": attempts,
        "submitted_sequences": submitted,
        "exact_good_phy": good,
        "tx_status": statuses,
        "receiver_packet_types": dict(counts),
        "in_memory_matching": matching.reduce_matches(normal, aggregates, legacy=True),
        "known_header_field_hypotheses": [
            v
            for raw in aggregates
            if (v := own_ics_observation(raw, {i: packets[i] for i in submitted})) is not None
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-legacy-rmac-ics", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--enable-group5", action="store_true")
    parser.add_argument("--enable-phy-counters", action="store_true")
    args = parser.parse_args()
    if not (args.activate_legacy_rmac_ics and args.acknowledge_experimental_transmit):
        parser.error("explicit ICS and transmit acknowledgments required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "max_submissions": 16,
        "channel": 6,
        "group5_requested": args.enable_group5,
        "phy_counters_requested": args.enable_phy_counters,
        "phases": [],
    }
    originals, attempted = {}, False
    counter_attempted = False
    with contextlib.ExitStack() as stack:
        rx, tx = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        radios = (rx, tx)
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        check_image(images[1][1])
        if hashlib.sha256(images[0][1]).hexdigest() != legacy.OLD_RAM_SHA256:
            raise ValueError("pinned receiver firmware required")

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            for i in (0, 1):
                boot(i)
            out["verified_receiver"] = legacy.verify(rx)
            originals = {a: legacy.valid_word(rx.rr(a)) & mask for a, mask in legacy.MASKS.items()}
            if (
                originals[0x820E50D0]
                or originals[0x820E705C]
                or legacy.valid_word(rx.rr(0x820E4120)) & 1
            ):
                raise ValueError("ICS already enabled")
            out["before_masks"] = legacy.masks(rx)
            if args.enable_phy_counters:
                if rx.CHIP != m.CHIP_MT7921:
                    raise ValueError("old-chip PHY counters only")
                word = legacy.valid_word(rx.rr(counters.CONTROL))
                if word & counters.MASK:
                    raise ValueError("exclusive initially disabled counters required")
                counter_attempted = True
                for enabled in (False, True):
                    rx.wr(
                        counters.CONTROL, counters.control_value(rx.rr(counters.CONTROL), enabled)
                    )
                out["counter_enabled_bits"] = (
                    legacy.valid_word(rx.rr(counters.CONTROL)) & counters.MASK
                )
                if out["counter_enabled_bits"] != 0xA00:
                    raise RuntimeError("counter enable readback failed")
            if args.enable_group5:
                attempted = True
                rx.wr(legacy.DMA_DCR0, legacy.valid_word(rx.rr(legacy.DMA_DCR0)) | legacy.G5_ENABLE)
            phy.program_rate(tx, 0x488)
            nonce = os.urandom(8)
            for first, last, enabled in ((0, 4, False), (4, 12, True), (12, 16, False)):
                if first:
                    attempted = True
                    legacy.send(rx, enabled)
                packets = {i: packet(tx, i, nonce, 128 if i % 2 else 0) for i in range(first, last)}
                phase = acquire(tx, rx, packets)
                phase.update({"ics_enabled": enabled, "masks_after": legacy.masks(rx)})
                if args.enable_phy_counters:
                    phase["counter_bits_after"] = (
                        legacy.valid_word(rx.rr(counters.CONTROL)) & counters.MASK
                    )
                out["phases"].append(phase)
            out["alive_after"] = [dev.alive() for dev in radios]
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if counter_attempted:
                try:
                    rx.wr(counters.CONTROL, counters.control_value(rx.rr(counters.CONTROL), False))
                    out["counter_restored"] = (
                        legacy.valid_word(rx.rr(counters.CONTROL)) & counters.MASK == 0
                    )
                except Exception as exc:
                    out["counter_restore_error_type"] = type(exc).__name__
            if attempted:
                try:
                    legacy.send(rx, False)
                    out["restored"] = legacy.restore(rx, originals)
                except Exception as exc:
                    out["restore_error_type"] = type(exc).__name__
            out["cleanup_reload_alive"] = []
            for i in (0, 1):
                try:
                    boot(i)
                    out["cleanup_reload_alive"].append(radios[i].alive())
                except Exception:
                    out["cleanup_reload_alive"].append(False)
    print(json.dumps(out, indent=2))
    return int(
        any(k.endswith("error_type") for k in out)
        or not all(out.get("cleanup_reload_alive", [False]))
        or not all(out.get("restored", {}).values())
        or (counter_attempted and not out.get("counter_restored"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
