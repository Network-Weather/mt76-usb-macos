# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research.cross_radio_clock_analysis import analyze
from research.tx_timing_analysis import ppdu_airtime_us


def fixture():
    tx, rx = [], []
    for n, rate in enumerate((0, 1, 2, 75)):
        stamp = 100000 + n * 50000
        tx.append(
            {
                "count": 1,
                "fields": {
                    "sequence": n,
                    "pid": 3,
                    "format": 0,
                    "tx_count_format0": 1,
                    "error_bits_16_22": 0,
                    "rate_stbc": False,
                    "tx_delay_raw": 30,
                    "timestamp_raw": stamp,
                    "front_time_raw_format0": 3125 + n * 1563,
                    "rate_raw": rate,
                    "status_received_host_seconds": 1 + n * 0.05,
                },
            }
        )
        rx.append({"sequence": n, "rxd_timestamp_raw": stamp + 500000 + ppdu_airtime_us(rate, 65)})
    return {
        "tool": "phy_tx_probe",
        "transmitter": "mt7925",
        "suite": "cck",
        "tx_timing": True,
        "submitted": 4,
        "frame_bytes_without_fcs": 65,
        "radios": [{"chip": "mt7925", "tx_status": tx}, {"chip": "mt7921", "own_rx_timing": rx}],
    }


def test_airtime_dependent_latch_separation_is_not_treated_as_clock_drift():
    result = analyze(fixture())
    assert result["raw_clock_difference_range_ticks"] == [500116, 500744]
    assert result["per_boot_offset_range_us"] == [500000, 500000]
    assert result["per_boot_offset_spread_us"] == 0
    assert result["airtime_corrected_rx_per_tx_tick_fit"] == pytest.approx(1)
    assert result["absolute_latch_point_or_propagation_time_validated"] is False


def test_short_preamble_removes_exactly96us_at_unchanged_payload_rate():
    trial = fixture()
    trial["suite"] = "preamble"
    for n, rate in enumerate((1, 5, 3, 7)):
        row = trial["radios"][0]["tx_status"][n]["fields"]
        row["rate_raw"] = rate
        trial["radios"][1]["own_rx_timing"][n]["rxd_timestamp_raw"] = (
            row["timestamp_raw"] + 500000 + ppdu_airtime_us(rate, 65)
        )
    out = analyze(trial)
    assert out["per_boot_offset_spread_us"] == 0
    for long, short in (("1", "5"), ("3", "7")):
        assert (
            out["rates"][long]["modeled_ppdu_airtime_us"]
            - out["rates"][short]["modeled_ppdu_airtime_us"]
            == 96
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sequence", 0),
        ("sequence", 4),
        ("sequence", True),
        ("rxd_timestamp_raw", None),
        ("rxd_timestamp_raw", -1),
        ("rxd_timestamp_raw", 1),
    ],
)
def test_bad_or_ambiguous_rx_pairs_rejected(field, value):
    trial = fixture()
    trial["radios"][1]["own_rx_timing"][1][field] = value
    with pytest.raises(ValueError, match=r"sequence|clock"):
        analyze(trial)


def test_missing_rx_is_explicit_and_bad_tx_still_rejected():
    trial = fixture()
    trial["radios"][1]["own_rx_timing"].pop()
    assert analyze(trial)["matched_frames"] == 3
    trial["radios"][0]["tx_status"][0]["fields"]["format"] = 1
    with pytest.raises(ValueError, match="statuses"):
        analyze(trial)
