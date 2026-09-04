# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Independent, bounded 802.11 control-frame interpretation for research.

Wire-format reference: IEEE 802.11-2020 9.3.1.7/9.3.1.8. Cross-checked against
Wireshark packet-ieee80211.c, dissect_ieee80211_block_ack_details, 2026-09-04.
No Wireshark implementation is incorporated. Unhandled BA types remain explicit.
Returned addresses are sensitive; research tools must aggregate before serialization.
"""

import struct


def parse_control(frame: bytes) -> dict | None:
    if len(frame) < 10:
        return None
    fc, duration = struct.unpack_from("<HH", frame)
    if (fc >> 2) & 3 != 1:
        return None
    subtype = (fc >> 4) & 15
    out = {"subtype": subtype, "duration_id": duration, "ra": frame[4:10]}
    # RTS, BlockAckReq, BlockAck each have a transmitter address. CTS/ACK do not.
    if subtype in (8, 9, 11):
        if len(frame) < 16:
            return out | {"error": "short_ta"}
        out["ta"] = frame[10:16]
    if subtype not in (8, 9):
        return out
    if len(frame) < 18:
        return out | {"error": "short_ba_control"}
    (control,) = struct.unpack_from("<H", frame, 16)
    ba_type = (control >> 1) & 15
    out.update(ba_type=ba_type, ack_policy=control & 1)
    if ba_type != 2:
        return out | {"unsupported": "only_single_tid_compressed_ba"}
    if len(frame) < 20:
        return out | {"error": "short_ssc"}
    (ssc,) = struct.unpack_from("<H", frame, 18)
    out.update(tid=control >> 12, start_sequence=ssc >> 4)
    if subtype == 8:
        return out
    # Explicitly handle observed/standardized bitmap size selectors; refuse others.
    selector = ssc & 15
    sizes = {0: 8, 4: 32, 8: 64, 10: 128}
    if selector not in sizes:
        return out | {"unsupported": "bitmap_size_selector"}
    size = sizes[selector]
    if len(frame) < 20 + size:
        return out | {"error": "short_bitmap"}
    bitmap = int.from_bytes(frame[20 : 20 + size], "little")
    out.update(bitmap_bits=size * 8, acknowledged=bitmap.bit_count())
    out["ack_sequences"] = [
        (out["start_sequence"] + bit) % 4096 for bit in range(size * 8) if bitmap & (1 << bit)
    ]
    # Trailing zero positions can be unsent packets; never label these as losses.
    covered = bitmap.bit_length()
    out["zero_positions_through_last_ack"] = covered - bitmap.bit_count()
    return out
