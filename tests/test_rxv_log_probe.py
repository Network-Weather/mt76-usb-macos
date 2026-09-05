# SPDX-License-Identifier: BSD-3-Clause-Clear
import sys

import pytest

from research import rxv_log_probe as p


@pytest.mark.parametrize("count", range(6))
def test_log_offsets_only_complete_older_records(count):
    rows = p.log_offsets(count)
    assert len(rows) == min(max(count - 1, 0), 3)
    for record, offsets in enumerate(rows):
        assert offsets == tuple(record * 176 + word * 4 for word in (0, 6, 20, 21))
        assert all(offset <= (count - 1) * 176 - 4 for offset in offsets)
        assert all(offset % 4 == 0 for offset in offsets)


@pytest.mark.parametrize("count", [-1, 6, True, 3.0])
def test_bad_counts_fail_closed(count):
    with pytest.raises(ValueError, match="zero through five"):
        p.log_offsets(count)


def test_projection_discards_unknown_vector_bits():
    raw = (-3945) & 0xFFFFF
    row = p.log_fields(
        0xABC00020, 0xDEAD1D1D, ((raw & 8191) << 19) | (29 << 13) | 8191, 0xABC00000 | (raw >> 13)
    )
    assert set(row) == {"phy_mode", "rcpi_bytes", "fields"}
    assert row["phy_mode"] == 2
    assert row["rcpi_bytes"] == [29, 29]
    assert row["fields"]["firmware_frequency_offset_s32"] == -4685
    assert row["fields"]["firmware_snr_field"] == 29
    with pytest.raises(ValueError, match="RCPI"):
        p.log_fields(0, -1, 0, 0)


def test_missing_tx_ack_fails_before_usb(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["rxv_log_probe.py"])
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("USB opened"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2
