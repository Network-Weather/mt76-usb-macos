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


def test_snapshot_reads_only_three_source_traced_registers():
    class Device:
        CHIP = p.m.CHIP_MT7921

        def rr(self, address):
            assert address in (0x820E7050, 0x820E5604, 0x820E3014)
            return 1

    assert p.setup_snapshot(Device()) == {
        "0x820e7050": "0x1",
        "0x820e5604": "0x1",
        "0x820e3014": "0x1",
    }
    dev = Device()
    dev.CHIP = p.m.CHIP_MT7925
    with pytest.raises(ValueError, match="old-chip"):
        p.setup_snapshot(dev)
