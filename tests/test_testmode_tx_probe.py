# SPDX-License-Identifier: BSD-3-Clause-Clear
import sys
import threading

import pytest

from research import testmode_tx_probe as p


def test_finite_safe_packet_generator_settings():
    settings = dict(p.settings(b"\x02NWabc"))
    assert settings[1] == 0
    assert settings[7] == 4
    assert settings[6] == 64
    assert settings[8] == 2000
    assert settings[2] == 0
    assert settings[3] == 4
    assert settings[18] == 5180000
    assert settings[11] == 1
    assert settings[13] == 0
    assert settings[68] == 0xFFFFFFFF
    assert settings[68 | (1 << 18)] == 0xFFFF
    assert 67 not in settings  # NVM write
    assert 105 not in settings  # calibration bypass
    assert settings[69].to_bytes(4, "little") == b"\x02NWa"
    assert settings[69 | (1 << 18)].to_bytes(2, "little") == b"bc"


@pytest.mark.parametrize("address", [bytes(6), b"\xff" * 6, b"\x02NW", "secret"])
def test_reject_non_synthetic_address(address):
    with pytest.raises(ValueError, match="synthetic"):
        p.settings(address)


def test_requires_explicit_transmit_opt_in(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["probe"])
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2


def test_observer_counts_only_and_checks_header_fcs(monkeypatch):
    source = b"\x02NWabc"
    frame = b"\x08\x00\x00\x00" + b"\xff" * 6 + source + b"secret" + b"\x30\x12" + b"\xa5" * 40
    packets = [
        {"frame": frame, "fcs_err": False, "phy": {"mode": 1, "bw_mhz": 20, "nss": 1}},
        {"frame": frame, "fcs_err": True},
    ]
    stop, ready = threading.Event(), threading.Event()

    class Device:
        index = 0

        def rx_read(self, **_):
            value = self.index
            self.index += 1
            if self.index == len(packets):
                stop.set()
            return bytes([value])

    monkeypatch.setattr(p.m, "decoder_for", lambda _: lambda raw: packets[raw[0]])
    result = p.collect(Device(), source, stop, ready)
    assert result["counts"]["matching_good_fcs_frames"] == 1
    assert result["counts"]["synthetic_source_bad_fcs"] == 1
    assert result["counts"]["candidate_fixed_payload_frames"] == 1
    assert result["unique_sequence_controls"] == 1
    assert "secret" not in str(result)
    assert "abc" not in str(result)
    assert ready.is_set()
