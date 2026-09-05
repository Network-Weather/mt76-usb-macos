# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Transient CSI/beacon coincidence checks; export counts, never identifiers."""

import collections
import struct

from research.csi_event_summary import parse_fields


class CsiCorrelation:
    """One <=512-transfer window, with no retained ambient payload or sample data."""

    def __init__(self):
        self.beacons = collections.Counter()
        self.reports = collections.Counter()
        self.frame_keys = collections.defaultdict(set)
        self.report_keys = collections.defaultdict(collections.Counter)
        self.groups = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        self.invalid = 0

    def add_frame(self, decoded):
        if not decoded or decoded.get("fcs_err"):
            return
        frame = decoded.get("frame", b"")
        if len(frame) < 36 or frame[0] != 0x80:
            return
        ta = bytes(frame[10:16])
        self.beacons[ta] += 1
        sequence = struct.unpack_from("<H", frame, 22)[0]
        self.frame_keys["sequence_control"].add((ta, sequence))
        self.frame_keys["sequence_number"].add((ta, sequence >> 4))
        self.frame_keys["beacon_tsf_low32"].add((ta, struct.unpack_from("<I", frame, 24)[0]))
        if type(decoded.get("timestamp")) is int:
            self.frame_keys["rx_descriptor_timestamp"].add((ta, decoded["timestamp"]))

    def add_csi(self, body):
        try:
            fields = parse_fields(body)
        except ValueError:
            self.invalid += 1
            return
        ta = bytes(fields[10][:6])
        rx = struct.unpack("<I", fields[18])[0] & 65535
        self.reports[ta] += 1
        for tags in ((17,), (23,), (25,), (23, 25)):
            if any(len(fields.get(tag, b"")) != 4 for tag in tags):
                continue
            label = "+".join(f"tag{tag}" for tag in tags)
            key = (ta, *(bytes(fields[tag]) for tag in tags))
            self.groups[label][key][rx] += 1
            if len(tags) == 1:
                self.report_keys[label][(ta, struct.unpack("<I", fields[tags[0]])[0])] += 1

    def export(self):
        shared = self.beacons.keys() & self.reports.keys()
        return {
            "beacons": sum(self.beacons.values()),
            "beacon_transmitters": len(self.beacons),
            "csi_reports": sum(self.reports.values()),
            "csi_transmitters": len(self.reports),
            "shared_transmitters": len(shared),
            "reports_from_heard_beacon_transmitters": sum(self.reports[ta] for ta in shared),
            "invalid_csi_events": self.invalid,
            "candidate_pair_keys": {
                label: {
                    "groups": len(groups),
                    "exact_rx0_rx1_pairs": sum(
                        counts == {0: 1, 1: 1} for counts in groups.values()
                    ),
                    "groups_with_repeated_rx_index": sum(
                        max(counts.values()) > 1 for counts in groups.values()
                    ),
                    "singleton_groups": sum(
                        sum(counts.values()) == 1 for counts in groups.values()
                    ),
                }
                for label, groups in sorted(self.groups.items())
            },
            "full_word_coincidences": {
                label: {
                    name: sum(count for key, count in keys.items() if key in frame_keys)
                    for name, frame_keys in sorted(self.frame_keys.items())
                }
                for label, keys in sorted(self.report_keys.items())
            },
        }
