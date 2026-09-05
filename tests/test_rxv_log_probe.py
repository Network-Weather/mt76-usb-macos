# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
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


def test_reset_is_exact_source_defined_volatile_counter_command():
    assert p.reset_log_request() == struct.pack("<B3xII", 1, 91, 0)


def test_match_ta_zeroes_receiver_and_uses_two_transmitter_fragments():
    source = b"\x02NW\x12\x34\x56"
    assert [struct.unpack("<B3xII", x) for x in p.match_ta_requests(source)] == [
        (1, 68, 0),
        (1, 68 | (1 << 18), 0),
        (1, 69, 0x12574E02),
        (1, 69 | (1 << 18), 0x5634),
        (1, 70, 0),
    ]


@pytest.mark.parametrize("source", [b"", b"\xff" * 6, b"\x00" * 6, "02NWxx"])
def test_match_rejects_nonsynthetic_sources(source):
    with pytest.raises(ValueError, match="synthetic"):
        p.match_ta_requests(source)


def test_match_snapshot_projects_only_flags_and_equality():
    class Device:
        CHIP = p.m.CHIP_MT7921

        def rr(self, address):
            return {
                0x0201717C: 0x02010000,
                0x02010038: 0,
                0x0201003C: 0xDEAD0001,
                0x820E5208: 0x12574E02,
                0x820E520C: 0x15634,
            }[address]

    assert p.match_ta_state(Device(), b"\x02NW\x12\x34\x56") == {
        "rule": 0,
        "transmitter_filter_flag": True,
        "receiver_filter_flag": False,
        "hardware_enable_bit": True,
        "hardware_matches_synthetic_target": True,
    }


@pytest.mark.parametrize("pointer", [0, 0x02010001, 0x03000000, 0x0207FFFC])
def test_match_snapshot_refuses_invalid_pointer(pointer):
    class Device:
        CHIP = p.m.CHIP_MT7921

        def rr(self, address):
            assert address == 0x0201717C
            return pointer

    with pytest.raises(ValueError, match="pointer"):
        p.match_ta_state(Device(), b"\x02NW\x12\x34\x56")


def test_clean_start_requires_filter_experiment_before_usb(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["rxv", "--acknowledge-experimental-transmit", "--rf-clean-start"]
    )
    monkeypatch.setattr(p.m, "open_device", lambda *_: pytest.fail("USB opened"))
    with pytest.raises(SystemExit) as exc:
        p.main()
    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("preparation", "expected"),
    [
        ("bare", []),
        ("channel", ["channel"]),
        ("config", ["config"]),
        ("tune", ["channel", "config"]),
        ("full", ["monitor", "enable", "channel", "config"]),
    ],
)
def test_clean_preparation_isolates_only_known_commands(preparation, expected):
    calls = []

    class Device:
        def set_monitor_mode(self):
            calls.append("monitor")

        def set_sniffer(self, enabled):
            assert enabled is True
            calls.append("enable")

        def set_chan_info(self, **kw):
            assert kw == {"control_ch": 36, "center_ch": 36, "bw": 0, "band": 1}
            calls.append("channel")

        def config_sniffer(self, **kw):
            assert kw == {"control_ch": 36, "center_ch": 36, "band_name": "5GHz", "bw": 0}
            calls.append("config")

    p.prepare_after_reload(Device(), preparation)
    assert calls == expected
    with pytest.raises(ValueError, match="unknown clean RF preparation"):
        p.prepare_after_reload(Device(), "unknown")
    assert calls == expected
