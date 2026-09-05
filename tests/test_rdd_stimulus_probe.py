# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct

import pytest

from research import rdd_stimulus_probe as p

MARKER = b"\xdd\x0c\x02NW\x01" + b"private!"


@pytest.mark.parametrize("sequence", [-1, 12, True])
def test_out_of_bound_sequence_fails_before_device_access(sequence):
    with pytest.raises(ValueError, match="bounded"):
        p.send_and_receive(None, None, sequence, MARKER)


def test_wrong_direction_before_io():
    class Device:
        CHIP = p.m.CHIP_MT7921

    with pytest.raises(ValueError, match="transmitter"):
        p.send_and_receive(Device(), Device(), 0, MARKER)


@pytest.mark.parametrize(
    ("changed_frame", "bad_fcs"), [(False, False), (True, False), (False, True)]
)
def test_exact_receipt_and_fcs_required_without_raw_export(monkeypatch, changed_frame, bad_fcs):
    expected = p.frame_for(0, MARKER)

    class Tx:
        CHIP = p.m.CHIP_MT7925
        ep_out_ac_be = 4

        def bulk_out(self, endpoint, wire, timeout):
            assert endpoint == 4
            assert timeout == 1000
            body_length = struct.unpack_from("<I", wire)[0]
            assert wire[4 : 4 + body_length].endswith(expected)
            assert len(wire) % 4 == 0

    class Rx:
        CHIP = p.m.CHIP_MT7921
        msg_seq = 7

        def rx_read(self, timeout):
            assert timeout == 20
            return b"fake record"

    times = iter([0, 0.01, 0.3])
    monkeypatch.setattr(p.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(p.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        p.m,
        "decoder_for",
        lambda _: (
            lambda __: {
                "frame": expected + (b"wrong" if changed_frame else b""),
                "fcs_err": bad_fcs,
                "phy": {"mode": 2, "mode_name": "HT", "mcs": 8, "nss": 2, "bw_mhz": 20},
            }
        ),
    )
    monkeypatch.setattr(p.r, "rdd_snapshot", lambda _: {"producer_word": "0x401c00"})
    result = p.send_and_receive(Tx(), Rx(), 0, MARKER)
    assert (result["exact_good_fcs_phy"] is not None) == (not changed_frame and not bad_fcs)
    assert "private" not in repr(result)
    assert not result["transfer_limit_reached"]
