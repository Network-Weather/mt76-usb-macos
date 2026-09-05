# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research.csi_filter_probe import Window, filter_request


def test_exact_single_address_add_remove_layout():
    target = b"\x02NW\x01\x02\x03"
    for add in (False, True):
        payload = filter_request(add, target)
        assert len(payload) == 16
        assert struct.unpack("<4xHHBB6s", payload) == (4, 12, int(add), 0, target)


@pytest.mark.parametrize("target", [bytes(6), b"\xff" * 6, bytes(5), "abcdef", b"\x01abcde"])
def test_reject_invalid_or_group_target(target):
    with pytest.raises(ValueError, match="unicast transmitter"):
        filter_request(True, target)


def test_reject_arbitrary_operation():
    with pytest.raises(ValueError, match="boolean"):
        filter_request(2, b"\x02abcde")


def test_window_exports_counts_only_and_separates_post_ack():
    window = Window("filtered")
    selected, other = b"SECRET", b"hidden"
    window.beacons.update({selected: 10, other: 40})
    window.csi.update({selected: 20, other: 2})
    window.after_ack.update({selected: 18, other: 1})
    window.acks = [0]
    out = window.export(selected)
    assert out["selected_beacons"] == 10
    assert out["selected_csi_reports"] == 20
    assert out["other_csi_reports"] == 2
    assert out["after_ack_other_csi"] == 1
    assert "SECRET" not in str(out)
    assert "hidden" not in str(out)
