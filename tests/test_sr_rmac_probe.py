# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research import sr_rmac_probe as p


def test_firmware_halfword_order_not_naive_low_high():
    assert p.fields([0x20001, 0x30004, 0x60005]) == {
        "non_srg_valid": 1,
        "srg_valid": 2,
        "intra_bss_ppdu": 3,
        "inter_bss_ppdu": 4,
        "non_srg_ppdu_valid": 5,
        "srg_ppdu_valid": 6,
    }


@pytest.mark.parametrize(
    "words", [[], [1, 2], [1, 2, 3, 4], [True, 0, 0], [0, -1, 0], [0, 0, 0xFFFFFFFF], [0, 0, 1.0]]
)
def test_invalid_values(words):
    with pytest.raises(ValueError, match="RMAC words"):
        p.fields(words)


@pytest.mark.parametrize("chip", [p.m.CHIP_MT7925, p.m.CHIP_MT7921])
def test_fixed_addresses_only_and_no_writes(chip):
    class Device:
        CHIP = chip

        def __init__(self):
            self.reads = []

        def rr(self, a):
            self.reads.append(a)
            return 0

    dev = Device()
    assert p.read(dev)["fields_raw"]["inter_bss_ppdu"] == 0
    assert dev.reads == [0x820E5198, 0x820E519C, 0x820E51A0]
    dev.CHIP = 0xFFFF
    with pytest.raises(ValueError, match="MT7925"):
        p.read(dev)
    assert len(dev.reads) == 3
