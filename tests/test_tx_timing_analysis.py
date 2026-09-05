# SPDX-License-Identifier: BSD-3-Clause-Clear
import copy

import pytest

from research.tx_timing_analysis import analyze, ppdu_airtime_us, unwrap


@pytest.mark.parametrize(
    ("rate", "short", "long"),
    [(0, 744, 1768), (1, 468, 980), (2, 293, 479), (3, 243, 336), (75, 116, 288)],
)
def test_ppdu_model_includes_fcs_preamble_and_ofdm_service_tail(rate, short, long):
    assert ppdu_airtime_us(rate, 65) == short
    assert ppdu_airtime_us(rate, 193) == long


@pytest.mark.parametrize(("rate", "length"), [(5, 65), (0, True), (0, 513), (0, 0)])
def test_model_rejects_unqualified_rate_or_length(rate, length):
    with pytest.raises(ValueError, match=r"bounded|CCK"):
        ppdu_airtime_us(rate, length)


def test_clock_wrap_and_backward_guard():
    assert unwrap([0xFFFFFFF0, 0x10, 0x30], 32) == [0xFFFFFFF0, 0x100000010, 0x100000030]
    assert unwrap([0x1FFFFF0, 0x10], 25) == [0x1FFFFF0, 0x2000010]
    with pytest.raises(ValueError, match="clock"):
        unwrap([10, 9], 25)


def fixture():
    return {
        "tool": "phy_tx_probe",
        "transmitter": "mt7925",
        "suite": "cck",
        "tx_timing": True,
        "submitted": 2,
        "frame_bytes_without_fcs": 65,
        "radios": [
            {
                "chip": "mt7925",
                "tx_status": [
                    {
                        "count": 1,
                        "fields": {
                            "sequence": n,
                            "pid": 3,
                            "format": 0,
                            "tx_count_format0": 1,
                            "error_bits_16_22": 0,
                            "rate_stbc": False,
                            "tx_delay_raw": 4,
                            "timestamp_raw": 100000 + n * 32000,
                            "front_time_raw_format0": 3125 + n * 1000,
                            "rate_raw": 75,
                            "status_received_host_seconds": 1 + n * 0.032,
                        },
                    }
                    for n in range(2)
                ],
            }
        ],
    }


def test_consistent_model_keeps_unknown_offset_and_units_explicit():
    result = analyze(fixture())
    assert result["timestamp_ticks_per_host_second_fit"] == pytest.approx(1e6)
    assert result["front_ticks_per_host_second_fit"] == pytest.approx(31250)
    assert result["per_boot_offset_range_us"] == [12, 12]
    assert result["calibrated_clock_or_contention_measurement"] is False


def test_frame_length_override_cannot_contradict_recorded_length():
    with pytest.raises(ValueError, match="conflicts"):
        analyze(fixture(), 193)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sequence", 0),
        ("format", 1),
        ("pid", 4),
        ("tx_count_format0", 2),
        ("error_bits_16_22", 1),
        ("timestamp_raw", 3),
        ("status_received_host_seconds", 0),
    ],
)
def test_bad_statuses_do_not_get_a_clock_fit(field, value):
    data = fixture()
    data["radios"][0]["tx_status"][1]["fields"][field] = value
    with pytest.raises(ValueError, match=r"sequence|statuses|clock|host"):
        analyze(data)


def test_burst_serial_service_relation_is_reported_not_assumed():
    data = fixture()
    template = data["radios"][0]["tx_status"][0]
    records = []
    for n in range(6):
        record = copy.deepcopy(template)
        record["fields"].update(
            sequence=n,
            timestamp_raw=100000 + n * 32000,
            front_time_raw_format0=3125 + n * 1000,
            status_received_host_seconds=1 + n * 0.032,
        )
        records.append(record)
    data.update(
        suite="timing-burst",
        per_phase=2,
        submitted=6,
        host_submissions=[
            {"sequence": n, "start_seconds": n * 0.001, "call_seconds": 0.0001} for n in range(6)
        ],
    )
    data["radios"][0]["tx_status"] = records
    result = analyze(data)["burst"]
    assert result["host_submission_window_us"] == pytest.approx(1100)
    assert result["front_step_minus_previous_delay_ticks"] == [996]
    records[2]["fields"]["tx_delay_raw"] = 1000
    assert analyze(data)["burst"]["front_step_minus_previous_delay_ticks"] == [0]
    data["host_submissions"][3]["start_seconds"] = -1
    with pytest.raises(ValueError, match="host submission"):
        analyze(data)
