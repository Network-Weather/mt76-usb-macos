# SPDX-License-Identifier: BSD-3-Clause-Clear
import struct
from types import SimpleNamespace

import pytest

import mt7921u as m
from research import phy_tx_probe as p
from research.rx_stat_query import request


@pytest.mark.parametrize(("name", "code"), p.RATES + p.STREAM_RATES)
def test_inline_connac2_vs_table_connac3(name, code):
    frame = p.c3.controlled_frame(7)
    c2 = SimpleNamespace(CHIP=m.CHIP_MT7921)
    c2._build_txwi = lambda frame, seq, pid: bytes(32)
    data = p.descriptor(c2, frame, 7, code)
    assert struct.unpack_from("<I", data, 24)[0] == (code << 16) | m.MT_TXD6_FIXED_BW
    c3 = SimpleNamespace(CHIP=m.CHIP_MT7925)
    data = p.descriptor(c3, frame, 7, code)
    assert struct.unpack_from("<I", data, 24)[0] == 0x12001C
    changed = p.descriptor(c3, frame, 7, code, fixed_bw=True)
    assert struct.unpack_from("<I", changed, 24)[0] == 0x212001C
    assert data[:24] == changed[:24]
    assert data[28:] == changed[28:]


def test_rate_allowlist():
    dev = SimpleNamespace(CHIP=m.CHIP_MT7925)
    with pytest.raises(ValueError, match="outside bounded experiment"):
        p.program_rate(dev, 0xFFFF)
    with pytest.raises(ValueError, match="outside bounded experiment"):
        p.descriptor(dev, b"", 0, 0xFFFF)


@pytest.mark.parametrize("spe", [0, 1, 24])
def test_spatial_code_only_changes_connac2_word7_field(spe):
    dev = SimpleNamespace(CHIP=m.CHIP_MT7921)
    dev._build_txwi = lambda frame, seq, pid: bytes.fromhex("a5" * 32)
    frame = p.c3.controlled_frame(0)
    before = p.descriptor(dev, frame, 0, 0x4B)
    after = p.descriptor(dev, frame, 0, 0x4B, spe_idx=spe)
    assert after[:28] == before[:28]
    word = struct.unpack_from("<I", after, 28)[0]
    assert (word >> 11) & 31 == spe
    assert word & ~(31 << 11) == struct.unpack_from("<I", before, 28)[0] & ~(31 << 11)
    assert not struct.unpack_from("<I", after, 24)[0] & (1 << 10)


@pytest.mark.parametrize(
    ("chip", "rate", "spe"),
    [
        (m.CHIP_MT7925, 0x4B, 0),
        (m.CHIP_MT7921, 0x488, 1),
        (m.CHIP_MT7921, 0x4B, 2),
        (m.CHIP_MT7921, 0x4B, -1),
    ],
)
def test_spatial_rejects_other_chip_rate_or_code(chip, rate, spe):
    with pytest.raises(ValueError, match="spatial experiment"):
        p.descriptor(SimpleNamespace(CHIP=chip), b"", 0, rate, spe_idx=spe)


def test_spatial_controls_and_packet_ceiling():
    assert len(p.SPATIAL_RATES) == len(p.SPATIAL_SPE) == 5
    assert p.SPATIAL_SPE == (0, 1, 0, 24, 0)
    assert {rate for _, rate in p.SPATIAL_RATES} == {0x4B}
    assert len(p.SPATIAL_RATES) * 10 <= 60


def test_stream_suite_encodes_nss_minus_one_and_stays_bounded():
    assert len(p.STREAM_RATES) == 6
    assert dict(p.STREAM_RATES)["ht8_2ss"] == 0x488
    assert dict(p.STREAM_RATES)["vht0_2ss"] == 0x500
    assert dict(p.STREAM_RATES)["he0_2ss"] == 0x600
    assert p.STREAM_RATES[0][1] == p.STREAM_RATES[-1][1] == 0x4B


@pytest.mark.parametrize("channel", [1, 6, 11])
def test_lowband_suite_has_no_vht_and_keeps_packet_ceiling(channel):
    rates = p.suite_rates("lowband", channel)
    assert len(rates) * 10 <= 60
    assert {code >> 6 & 15 for _, code in rates} == {1, 2, 8}
    assert rates[0][1] == rates[-1][1] == 0x4B
    assert dict(rates)["ht8_2ss"] == 0x488


@pytest.mark.parametrize("suite", ["cck", "preamble"])
@pytest.mark.parametrize("channel", [1, 6, 11])
def test_cck_suites_are_lowband_and_bounded(suite, channel):
    rates = p.suite_rates(suite, channel)
    assert len(rates) * 10 <= 60
    assert rates[0][1] == rates[-1][1] == 0x4B
    assert all(code in (0, 1, 2, 3, 5, 7) for _, code in rates[1:-1])
    with pytest.raises(ValueError, match="lowband"):
        p.suite_rates(suite, 36)


@pytest.mark.parametrize("code", [0, 1, 2, 3, 5, 7])
def test_cck_table_programs_only_allowed_source_rate(code):
    class Device:
        CHIP = m.CHIP_MT7925

        def __init__(self):
            self.writes = []

        def wr(self, address, value):
            self.writes.append((address, value))

        def rr(self, address):
            assert address == p.c3.ITCR
            return 0

    dev = Device()
    p.program_rate(dev, code)
    assert dev.writes == [
        (p.c3.ITDR0, code),
        (p.c3.ITDR1, 1 << 6),
        (p.c3.ITCR, (1 << 31) | (1 << 16) | 18),
    ]


def test_preamble_codes_change_only_short_preamble_bit():
    rates = dict(p.PREAMBLE_RATES)
    assert rates["cck2_short"] ^ rates["cck2_long"] == 4
    assert rates["cck11_short"] ^ rates["cck11_long"] == 4


def test_stbc_uses_connac3_bit14_and_two_space_time_streams():
    rates = p.suite_rates("stbc", 1)
    assert len(rates) * 10 <= 60
    code = dict(rates)["ht0_stbc"]
    assert code == (1 << 14) | (1 << 10) | (2 << 6)
    assert rates[0][1] == rates[-1][1] == 0x488
    assert rates[1][1] == rates[-2][1] == 0x80
    dev = SimpleNamespace(CHIP=m.CHIP_MT7925)
    frame = p.c3.controlled_frame(0)
    assert p.descriptor(dev, frame, 0, code) == p.descriptor(dev, frame, 0, 0x80)
    with pytest.raises(ValueError, match="lowband"):
        p.suite_rates("stbc", 36)


def test_stbc_wrong_chip_never_writes():
    dev = SimpleNamespace(CHIP=m.CHIP_MT7921)
    with pytest.raises(ValueError, match="MT7925-only"):
        p.program_rate(dev, 0x4480)
    with pytest.raises(ValueError, match="MT7925-only"):
        p.descriptor(dev, b"", 0, 0x4480)


def test_stbc_table_write_exact_rate_and_existing_selector():
    class Device:
        CHIP = m.CHIP_MT7925

        def __init__(self):
            self.writes = []

        def wr(self, address, value):
            self.writes.append((address, value))

        def rr(self, address):
            assert address == p.c3.ITCR
            return 0

    dev = Device()
    p.program_rate(dev, 0x4480)
    assert dev.writes == [
        (p.c3.ITDR0, 0x4480),
        (p.c3.ITDR1, 64),
        (p.c3.ITCR, (1 << 31) | (1 << 16) | 18),
    ]


def test_he_coding_source_bits_and_unchanged_controls():
    rates = p.suite_rates("he-coding", 1)
    codes = dict(rates)
    assert len(rates) * 10 <= 60
    assert rates[0][1] == rates[-1][1] == 0x600
    assert codes["he0_dcm_1ss"] == codes["he0_1ss"] | (1 << 4)
    assert codes["he0_stbc_1ss"] == (1 << 14) | (1 << 10) | (8 << 6)
    with pytest.raises(ValueError, match="lowband"):
        p.suite_rates("he-coding", 36)


@pytest.mark.parametrize("code", [0x210, 0x4600])
def test_he_coding_rejects_other_chip_before_io(code):
    dev = SimpleNamespace(CHIP=m.CHIP_MT7921)
    with pytest.raises(ValueError, match="MT7925-only"):
        p.program_rate(dev, code)
    with pytest.raises(ValueError, match="MT7925-only"):
        p.descriptor(dev, b"", 0, code)


def test_timing_padding_is_exact_valid_private_ie():
    assert p.timing_padding(0) == b""
    value = p.timing_padding(128)
    assert len(value) == 128
    assert value[:6] == b"\xdd\x7e\x02NW\x02"
    assert value[1] == len(value) - 2


@pytest.mark.parametrize("length", [True, -1, 127, 129, 256])
def test_timing_padding_is_bounded(length):
    with pytest.raises(ValueError, match="padding"):
        p.timing_padding(length)


def test_timing_burst_is_at_most_ten_unpaced_frames_with_bracketing_controls():
    rates = p.suite_rates("timing-burst", 6)
    assert len(rates) == 3
    assert {rate for _, rate in rates} == {0}
    assert [p.phase_gap("timing-burst", i) for i in range(3)] == [0.05, 0, 0.05]
    assert p.phase_gap("cck", 1) == 0.05
    with pytest.raises(ValueError, match="three-phase"):
        p.phase_gap("timing-burst", 3)


@pytest.mark.parametrize(
    ("suite", "channel"),
    [
        ("baseline", 1),
        ("streams", 6),
        ("spatial", 11),
        ("lowband", 36),
        ("lowband", 149),
        ("lowband", True),
        ("baseline", 37),
    ],
)
def test_rate_suite_geometry_rejected_before_usb(suite, channel):
    with pytest.raises(ValueError, match=r"bounded|lowband"):
        p.suite_rates(suite, channel)


@pytest.mark.parametrize("category", [0, 3, 4, 5, 6])
def test_receive_query_shape(category):
    assert request(category) == bytes((category, 0, 0, 0))


@pytest.mark.parametrize(("category", "selector"), [(1, 0), (2, 0), (7, 0), (4, 2), (5, 1), (6, 1)])
def test_receive_query_rejects_nonqueries(category, selector):
    with pytest.raises(ValueError, match=r"query|categories"):
        request(category, selector)


def test_capture_only_exact_own_frames_and_valid_fcs(monkeypatch):
    stop = p.threading.Event()
    frame = p.c3.controlled_frame(0)
    samples = iter(
        [
            {"pkt_type": 2, "frame": frame, "phy": {"mode_name": "HT", "mcs": 0}},
            {"pkt_type": 2, "frame": frame, "phy": {"mode_name": "HT", "mcs": 0}},
            {"pkt_type": 2, "frame": frame, "fcs_err": True},
            {"pkt_type": 2, "frame": frame + b"different"},
        ]
    )

    def decode(raw):
        try:
            return next(samples)
        except StopIteration:
            stop.set()
            return None

    monkeypatch.setattr(m, "decoder_for", lambda dev: decode)
    dev = SimpleNamespace(CHIP=m.CHIP_MT7921, rx_read=lambda **kwargs: b"")
    out = p.capture(dev, {0: frame}, 1, p.threading.Event(), stop)
    assert out["phases"][0]["unique_exact_frames"] == 1
    assert out["phases"][0]["phy"][0]["count"] == 2
    assert out["counts"]["controlled_fcs_errors"] == 1
