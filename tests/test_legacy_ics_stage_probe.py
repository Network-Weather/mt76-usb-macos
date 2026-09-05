# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import legacy_ics_stage_probe as p


def test_only_existing_receive_operations_are_exposed():
    commands = {s: [struct.unpack("<B3xII", b) for b in p.stage_commands(s)] for s in p.STAGES}
    assert commands == {
        "normal_ics": [],
        "rf_entered": [(0, 1, 0)],
        "rf_configured": [(1, 1, 0), (1, 104, 0), (1, 106, 3 << 16), (1, 18, 2437000), (1, 15, 0)],
        "rf_started": [(1, 1, 2)],
        "rf_stopped": [(1, 1, 0)],
    }
    with pytest.raises(ValueError, match="five fixed"):
        p.stage_commands("transmit")


def test_twenty_unique_sequences_fit_existing_packet_builder():
    assert list(range(len(p.STAGES) * 4)) == list(range(20))
