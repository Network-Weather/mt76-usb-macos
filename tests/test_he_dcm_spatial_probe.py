# SPDX-License-Identifier: BSD-3-Clause-Clear
from types import SimpleNamespace

import pytest

from research import he_dcm_spatial_probe as p


@pytest.mark.parametrize("code", [0x200, 0x210, 0x240, 0x250])
def test_spatial_he_rates_have_exact_source_fields(monkeypatch, code):
    writes = []
    dev = SimpleNamespace(
        CHIP=p.m.CHIP_MT7925, wr=lambda a, v: writes.append((a, v)), rr=lambda _: 0
    )
    monkeypatch.setattr(p, "read_slot", lambda d, i: (code, 0x10080) if i == 18 else None)
    assert p.program(dev, code) == [hex(code), "0x10080"]
    assert writes == [
        (p.phy.c3.ITDR0, code),
        (p.phy.c3.ITDR1, 0x10080),
        (p.phy.c3.ITCR, 0x80010012),
    ]


@pytest.mark.parametrize("code", [0x488, 0x600, 0x201, True])
def test_rejects_other_rates_before_io(code):
    with pytest.raises(ValueError, match="HE/ER"):
        p.program(SimpleNamespace(CHIP=p.m.CHIP_MT7925), code)


def test_indexed_readback_failure_stops_before_transmit(monkeypatch):
    monkeypatch.setattr(p.phy, "program_rate", lambda *a, **k: None)
    monkeypatch.setattr(p, "read_slot", lambda *a: (0x200, 0x10040))
    with pytest.raises(ValueError, match="mismatch"):
        p.program(SimpleNamespace(CHIP=p.m.CHIP_MT7925), 0x200)


def test_twenty_frame_scope_and_brackets():
    assert len(p.PHASES) * 4 == 20
    assert p.PHASES[0][1] == p.PHASES[-1][1] == 0x200
    assert [code for _, code in p.PHASES[1:-1]] == [0x210, 0x240, 0x250]
