# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

from research.csi_correlation import CsiCorrelation


def report(rx, stamp, rssi=-90, snr=23):
    fields = {
        tag: struct.pack("<I", 0) for tag in (0, 1, 2, 3, 4, 5, 8, 9, 12, 17, 18, 20, 21, 23, 25)
    }
    fields.update(
        {
            2: struct.pack("<I", rssi & 0xFFFFFFFF),
            3: struct.pack("<I", snr),
            5: struct.pack("<I", 1),
            6: bytes(2),
            7: bytes(2),
            10: b"SECRET!!",
            18: struct.pack("<I", rx),
            23: struct.pack("<I", stamp),
            25: struct.pack("<I", 123),
        }
    )
    data = b"".join(struct.pack("<II", tag, len(value)) + value for tag, value in fields.items())
    return struct.pack("<4xHH", 0, len(data) + 4) + data


def beacon():
    data = bytearray(36)
    data[0] = 0x80
    data[10:16] = b"SECRET"
    struct.pack_into("<H", data, 22, 123 << 4)
    struct.pack_into("<Q", data, 24, 987654)
    return {"frame": bytes(data), "fcs_err": False, "timestamp": 555}


def test_transient_match_and_pair_candidates_export_only_counts():
    correlation = CsiCorrelation()
    correlation.add_frame(beacon())
    for stamp in (555, 666):
        for rx in (0, 1):
            correlation.add_csi(report(rx, stamp))
    out = correlation.export()
    assert out["shared_transmitters"] == 1
    assert out["reports_from_heard_beacon_transmitters"] == 4
    assert out["candidate_pair_keys"]["tag23"]["exact_rx0_rx1_pairs"] == 2
    assert out["candidate_pair_keys"]["tag25"]["groups_with_repeated_rx_index"] == 1
    assert out["full_word_coincidences"]["tag23"]["rx_descriptor_timestamp"] == 2
    assert out["full_word_coincidences"]["tag25"]["sequence_number"] == 4
    for private in ("SECRET", "987654", "555", "666", "123"):
        assert private not in str(out)


def test_nonbeacons_bad_fcs_truncation_and_bad_csi_do_not_match():
    correlation = CsiCorrelation()
    correlation.add_frame({**beacon(), "fcs_err": True})
    correlation.add_frame({"frame": bytes(40)})
    correlation.add_frame({"frame": bytes(20)})
    correlation.add_frame(None)
    correlation.add_csi(b"invalid")
    correlation.add_csi(report(0, 555))
    out = correlation.export()
    assert out["beacons"] == out["shared_transmitters"] == 0
    assert out["invalid_csi_events"] == 1
    assert out["candidate_pair_keys"]["tag23"]["singleton_groups"] == 1


def test_paired_signal_metadata_excludes_duplicate_and_incomplete_pairs():
    correlation = CsiCorrelation()
    correlation.add_csi(report(0, 10, -92))
    correlation.add_csi(report(1, 10, -87))
    out = correlation.export()["paired_signal_metadata"]
    assert out == {
        "exact_rx0_rx1_pairs": 1,
        "equal_snr_raw": 1,
        "different_rssi_raw": 1,
        "rx1_minus_rx0_rssi_raw_min": 5,
        "rx1_minus_rx0_rssi_raw_max": 5,
    }
    correlation.add_csi(report(1, 10, -87))
    assert correlation.export()["paired_signal_metadata"]["exact_rx0_rx1_pairs"] == 0
