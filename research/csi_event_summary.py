# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Bounded CSI validation and aggregate-only summaries; never export sample arrays.

Layout: pinned gen4m gl_csi.h / gl_csi.c:nicEventCSIData. Inner lengths exclude
their eight-byte header. Unknown tags are length-checked, never interpreted.
"""

import collections
import hashlib
import struct

from mt76_csi import parse_csi_tlvs


def snr_field_without_offset(version, value):
    """Pinned report22: (PHY0x83080cb8 >>25)+16, unless a type bit forces0.

    This removes a proven encoding offset; it does not calibrate SNR units.
    Zero is not minus16: it may be the firmware's explicit zeroing path.
    """
    if type(version) is int and version == 22 and type(value) is int and 16 <= value <= 143:
        return value - 16
    return None


def parse_tlvs(body):
    """Private in-memory data for validation; callers must not serialize this."""
    return parse_csi_tlvs(body)


def iq_layout(fields):
    """Separate the pinned CCK count13/storage64 format from ordinary dimensions.

    Firmware e009e3bc/e009e444 fixes 128-byte arrays but reports count13.
    Its e009e0fa branch expands signed14-bit I/Q. Count13 is not a justified
    reason to silently discard the other51 stored pairs or label them subcarriers.
    """
    count = struct.unpack("<I", fields[5])[0]

    def scalar(tag):
        return struct.unpack("<I", fields[tag])[0]

    if scalar(0) == 22 and scalar(1) == 6 and scalar(12) & 65535 == 0:
        if count != 13 or scalar(8) != 0 or any(len(fields.get(t, b"")) != 128 for t in (6, 7)):
            raise ValueError("CSI pinned CCK dimensions")
        samples = struct.unpack("<128h", fields[6] + fields[7])
        if any(not -8192 <= value <= 8191 for value in samples):
            raise ValueError("CSI pinned CCK signed14 storage")
        return "pinned_cck_count13_storage64"
    if not 1 <= count <= 1024 or any(len(fields.get(t, b"")) != 2 * count for t in (6, 7)):
        raise ValueError("CSI I/Q dimensions")
    return "count_matches_storage"


def validate_fields(fields):
    for tag in (0, 1, 2, 3, 4, 5, 8, 9, 12, 18, 20, 21):
        if len(fields.get(tag, b"")) != 4:
            raise ValueError(f"CSI required scalar tag {tag}")
    iq_layout(fields)
    if len(fields.get(10, b"")) != 8:
        raise ValueError("CSI transmitter field size")


def parse_fields(body):
    fields = parse_tlvs(body)
    validate_fields(fields)
    return fields


class CsiSummary:
    """Aggregate bounded event metadata; discard transmitter IDs and sample arrays."""

    def __init__(self):
        self.events = 0
        self.invalid = 0
        self.errors = collections.Counter()
        self.shapes = collections.Counter()
        self.padding = collections.Counter()
        self.layouts = collections.Counter()
        self.metadata = collections.defaultdict(collections.Counter)
        self.fingerprints = set()
        self.rx_fingerprints = collections.defaultdict(set)
        self.rx_events = collections.Counter()
        self.iq_nonzero = 0
        self.iq_values = 0
        self.iq_min = None
        self.iq_max = None

    def add(self, body):
        try:
            fields = parse_tlvs(body)
            self.shapes[tuple((tag, len(data)) for tag, data in fields.items())] += 1
            self.padding[len(body) - 8 - sum(8 + len(data) for data in fields.values())] += 1
            validate_fields(fields)
        except ValueError as exc:
            self.invalid += 1
            self.errors[str(exc)] += 1
            return
        self.events += 1
        self.layouts[iq_layout(fields)] += 1
        words = {
            tag: struct.unpack("<I", fields[tag])[0]
            for tag in (0, 1, 2, 3, 4, 5, 8, 9, 12, 18, 20, 21)
        }
        values = {
            "version_raw": words[0],
            "cbw_raw": words[1],
            "rssi_raw_signed_byte": (words[2] & 255) - (256 if words[2] & 128 else 0),
            "snr_raw_byte": words[3] & 255,
            "band_raw": words[4],
            "data_count": words[5],
            "iq_stored_pairs": len(fields[6]) // 2,
            "dbw_raw": words[8],
            "channel_index_raw": words[9],
            "rx_mode_raw": words[12] & 65535,
            "rx_rate_raw": words[12] >> 16,
            "rx_index_raw": words[18] & 65535,
            "tx_index_raw": words[18] >> 16,
            "segment_raw": words[20],
            "remain_last_raw": words[21],
        }
        snr = snr_field_without_offset(words[0], words[3])
        if snr is not None:
            values["snr_pinned_encoding_minus16"] = snr
        for name, value in values.items():
            self.metadata[name][value] += 1
        iq = fields[6] + fields[7]
        # Digest is transient: only cardinality is ever exported.
        fingerprint = hashlib.sha256(iq).digest()
        self.fingerprints.add(fingerprint)
        rx_index = words[18] & 65535
        self.rx_fingerprints[rx_index].add(fingerprint)
        self.rx_events[rx_index] += 1
        samples = struct.unpack(f"<{len(iq) // 2}h", iq)
        self.iq_values += len(samples)
        self.iq_nonzero += sum(value != 0 for value in samples)
        lo, hi = min(samples), max(samples)
        self.iq_min = lo if self.iq_min is None else min(self.iq_min, lo)
        self.iq_max = hi if self.iq_max is None else max(self.iq_max, hi)

    def export(self):
        return {
            "valid_events": self.events,
            "invalid_events": self.invalid,
            "iq_layout_counts": dict(self.layouts),
            "iq_distinct_by_rx_index": [
                {
                    "rx_index": index,
                    "events": self.rx_events[index],
                    "distinct_payloads": len(values),
                }
                for index, values in sorted(self.rx_fingerprints.items())
            ],
            "validation_errors": dict(self.errors),
            "zero_tail_bytes_counts": [
                {"bytes": size, "count": count} for size, count in sorted(self.padding.items())
            ],
            "inner_shapes": [
                {"fields": [{"tag": t, "bytes": n} for t, n in shape], "count": count}
                for shape, count in self.shapes.items()
            ],
            "metadata_counts": {
                name: [{"value": value, "count": count} for value, count in sorted(counter.items())]
                for name, counter in sorted(self.metadata.items())
            },
            "iq_distinct_payloads": len(self.fingerprints),
            "iq_int16_values": self.iq_values,
            "iq_nonzero_values": self.iq_nonzero,
            "iq_min_raw": self.iq_min,
            "iq_max_raw": self.iq_max,
        }
