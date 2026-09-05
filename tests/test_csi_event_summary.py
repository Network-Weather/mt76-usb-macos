# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research.csi_event_summary import CsiSummary, parse_fields


def body(iq=(1, -2), override=None):
    fields = {tag: struct.pack("<I", 0) for tag in (0, 1, 2, 3, 4, 5, 8, 9, 12, 18, 20, 21)}
    fields.update(
        {
            2: struct.pack("<I", 0xFFFFFFBA),
            5: struct.pack("<I", 2),
            6: struct.pack("<2h", *iq),
            7: struct.pack("<2h", 0, 3),
            10: b"SECRET!!",
            25: b"hidden!!",
        }
    )
    if override:
        fields.update(override)
    inner = b"".join(struct.pack("<II", tag, len(data)) + data for tag, data in fields.items())
    return struct.pack("<4xHH", 0, len(inner) + 4) + inner


def test_valid_aggregate_has_no_samples_addresses_unknown_data_or_fingerprints():
    summary = CsiSummary()
    summary.add(body())
    summary.add(body())
    summary.add(body((4, -5)))
    out = summary.export()
    assert out["valid_events"] == 3
    assert out["iq_distinct_payloads"] == 2
    assert out["iq_int16_values"] == 12
    assert out["iq_nonzero_values"] == 9
    assert (out["iq_min_raw"], out["iq_max_raw"]) == (-5, 4)
    assert out["metadata_counts"]["rssi_raw_signed_byte"] == [{"value": -70, "count": 3}]
    for forbidden in ("SECRET", "hidden", "fingerprint", "samples", "aucbody"):
        assert forbidden not in str(out)


@pytest.mark.parametrize(
    "override",
    [{5: struct.pack("<I", 0)}, {5: struct.pack("<I", 1025)}, {6: b"x"}, {10: b"123456"}, {0: b""}],
)
def test_reject_bad_required_dimensions(override):
    with pytest.raises(ValueError, match="CSI"):
        parse_fields(body(override=override))


def test_reject_truncation_oversize_and_bad_outer_length():
    valid = body()
    for malformed in (b"", valid[:-1], bytes(8193), bytes(8)):
        with pytest.raises(ValueError, match="CSI"):
            parse_fields(malformed)


def test_reject_duplicate_and_inner_overrun_without_exporting_body():
    for inner in (struct.pack("<II", 0, 0) * 2, struct.pack("<II", 0, 999)):
        summary = CsiSummary()
        summary.add(struct.pack("<4xHH", 0, len(inner) + 4) + inner)
        assert summary.export()["invalid_events"] == 1
        assert summary.export()["valid_events"] == 0


def test_pinned_zero_tail_is_narrow_and_reported_not_generic_padding():
    data = body(override={25: bytes(4)})
    padded = bytearray(data + bytes(36))
    struct.pack_into("<H", padded, 6, len(padded) - 4)
    summary = CsiSummary()
    summary.add(padded)
    assert summary.export()["valid_events"] == 1
    assert summary.export()["zero_tail_bytes_counts"] == [{"bytes": 36, "count": 1}]
    padded[-1] = 1
    with pytest.raises(ValueError, match="CSI duplicate"):
        parse_fields(padded)
    for count in (4, 8, 32, 40):
        bad = bytearray(data + bytes(count))
        struct.pack_into("<H", bad, 6, len(bad) - 4)
        with pytest.raises(ValueError, match="CSI"):
            parse_fields(bad)
