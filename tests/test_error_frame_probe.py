# SPDX-License-Identifier: BSD-3-Clause-Clear
from types import SimpleNamespace

import pytest

from research import error_frame_probe as p


@pytest.mark.parametrize(("sniffer", "mac"), [(1, 1), (0, 1), (1, 0), (0, 0)])
def test_separate_drop_controls_change_only_fcs_bit(monkeypatch, sniffer, mac):
    monkeypatch.setattr(p.time, "sleep", lambda _: None)
    calls = []
    state = [0x201002]

    def filter(fif, operation, bitmap):
        calls.append(("filter", fif, operation, bitmap))
        state[0] = state[0] | bitmap if operation == p.m.MT7921_FIF_BIT_SET else state[0] & ~bitmap

    dev = SimpleNamespace(
        CHIP="mt7921",
        rr=lambda address: state[0],
        set_rxfilter=filter,
        config_sniffer=lambda *a, **k: calls.append(("sniffer", a, k)),
    )
    result = p.configure(dev, sniffer, mac)
    assert calls == [
        ("sniffer", (6, 6, "2.4GHz"), {"drop_err": sniffer}),
        ("filter", 0, 1 if mac else 2, 2),
    ]
    assert result["rfcr_after_sniffer"] == "0x201002"
    assert int(result["rfcr_after_mac"], 16) == 0x201000 | (mac << 1)


@pytest.mark.parametrize("value", [None, True, -1, 0xFFFFFFFF])
def test_invalid_rfcr_rejected_before_configuration(value):
    with pytest.raises(ValueError, match="RFCR"):
        p.configure(SimpleNamespace(CHIP="mt7921", rr=lambda _: value), 0, 0)


def test_other_chip_and_unbounded_controls_rejected():
    with pytest.raises(ValueError, match="MT7961"):
        p.configure(SimpleNamespace(CHIP="mt7925"), 0, 0)
    for pair in ((2, 0), (0, True), (None, 0)):
        with pytest.raises(ValueError, match="drop controls"):
            p.configure(None, *pair)


def test_failed_frame_export_has_no_payload_identity_or_verified_receipt():
    decoded = {
        "fcs_err": True,
        "frame": b"private payload and addresses",
        "rssi": -100,
        "phy": {"mode_name": "HT", "mcs": 15, "nss": 2},
        "ta": "private address",
    }
    meta = p.failed_metadata(decoded)
    assert meta["phy"]["mcs"] == 15
    assert meta["own_frame_identity_verified"] is False
    assert "private" not in str(meta)
    assert meta["frame_bytes_without_fcs"] == len(decoded["frame"])
    decoded["fcs_err"] = False
    assert p.failed_metadata(decoded) is None


def test_final_same_rate_restore_phase_and_twenty_eight_frame_bound():
    assert len(p.PHASES) * 4 == 28
    assert p.PHASES[-2] == ("ht15_restored", 0x48F, 1, 1)
    assert p.PHASES[0][1] == p.PHASES[-1][1] == 0x488
