# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Control channel to center channel, the mapping a wide capture needs.

Centers are the operating-class definitions quoted in hostapd
src/common/ieee802_11_common.c (classes 126/127, 128, 129) and the 6 GHz rule in
center_idx_to_bw_6ghz() in the same file.
"""

import pytest

import mt7921u as m


def test_twenty_megahertz_is_its_own_center_on_every_band():
    for band, channel in (("2.4GHz", 6), ("5GHz", 44), ("6GHz", 37)):
        assert m.center_channel(band, channel, 20) == channel


@pytest.mark.parametrize(
    ("control", "center"),
    [(36, 42), (40, 42), (44, 42), (48, 42), (52, 58), (100, 106), (149, 155), (161, 155)],
)
def test_five_ghz_eighty_megahertz_blocks(control, center):
    assert m.center_channel("5GHz", control, 80) == center


@pytest.mark.parametrize(("control", "center"), [(36, 50), (64, 50), (100, 114), (128, 114)])
def test_five_ghz_one_hundred_sixty_megahertz_blocks(control, center):
    assert m.center_channel("5GHz", control, 160) == center


@pytest.mark.parametrize(("control", "center"), [(36, 38), (40, 38), (44, 46), (149, 151)])
def test_five_ghz_forty_megahertz_blocks(control, center):
    assert m.center_channel("5GHz", control, 40) == center


@pytest.mark.parametrize(("control", "center"), [(1, 7), (5, 7), (13, 7), (33, 39), (37, 39)])
def test_six_ghz_eighty_megahertz_follows_the_center_index_rule(control, center):
    assert m.center_channel("6GHz", control, 80) == center
    # center_idx_to_bw_6ghz(): an 80 MHz center index satisfies (idx & 0xf) == 0x7.
    assert center & 0xF == 0x7


@pytest.mark.parametrize(("control", "center"), [(1, 15), (29, 15), (33, 47)])
def test_six_ghz_one_hundred_sixty_megahertz_follows_the_center_index_rule(control, center):
    assert m.center_channel("6GHz", control, 160) == center
    assert center & 0x1F == 0xF


def test_a_two_point_four_ghz_forty_megahertz_channel_is_refused_as_ambiguous():
    # A 2.4 GHz 40 MHz channel may extend above or below its control channel, and the
    # control channel alone does not say which. Guessing would tune the wrong 40 MHz.
    for channel in (1, 6, 11):
        assert m.center_channel("2.4GHz", channel, 40) is None
        assert m.center_channel("2.4GHz", channel, 80) is None


def test_a_control_channel_outside_every_block_of_that_width_is_refused():
    assert m.center_channel("5GHz", 1, 80) is None  # not a 5 GHz channel at all
    assert m.center_channel("5GHz", 144, 160) is None  # 144 sits above the 114 block
    assert m.center_channel("6GHz", 2, 80) is None  # 6 GHz channel 2 is 20 MHz only


def test_every_listed_center_is_recovered_from_its_own_block():
    # A center channel of a 40 MHz block is not itself a control channel, but every
    # control channel in each block must resolve to exactly that block's center.
    for (band, width), centers in m.CENTER_CHANNELS.items():
        reach = (width // 5 - 2) // 2
        for center in centers:
            # Control channels sit at odd multiples of 2 channel numbers from the center.
            offsets = [o for o in range(-reach, reach + 1) if o % 4 == 2]
            assert len(offsets) == width // 20
            for offset in offsets:
                resolved = m.center_channel(band, center + offset, width)
                assert resolved == center, (band, width, center, offset, resolved)


def test_a_channel_that_is_not_a_control_channel_of_any_block_is_refused():
    # Halfway between two 20 MHz control channels is not a control channel.
    assert m.center_channel("5GHz", 42, 80) is None
    assert m.center_channel("6GHz", 7, 80) is None
    assert m.center_channel("6GHz", 3, 80) is None


def test_six_ghz_blocks_stop_where_the_band_does():
    # 6 GHz 20 MHz control channels run 1 to 233 in steps of 4, so a block is real only
    # when its outermost control channel is still in the band. Channel 229 has no 80 MHz
    # block: one centered at 231 would need control channel 237, which does not exist.
    assert m.center_channel("6GHz", 229, 80) is None
    assert m.center_channel("6GHz", 233, 80) is None
    assert m.center_channel("6GHz", 233, 40) is None
    assert m.center_channel("6GHz", 213, 80) == 215  # the last real 80 MHz block


def test_the_six_ghz_channel_plan_has_the_number_of_blocks_it_is_defined_to_have():
    assert len(m.CENTER_CHANNELS[("6GHz", 40)]) == 29
    assert len(m.CENTER_CHANNELS[("6GHz", 80)]) == 14
    assert len(m.CENTER_CHANNELS[("6GHz", 160)]) == 7


def test_no_block_on_any_band_reaches_past_the_top_of_its_band():
    tops = {"5GHz": 177, "6GHz": m.SIX_GHZ_MAX_CHANNEL}
    bottoms = {"5GHz": 36, "6GHz": 1}
    for (band, width), centers in m.CENTER_CHANNELS.items():
        # A block of width W holds W/20 control channels at odd multiples of 2 channel
        # numbers from its center, so the outermost one is W/10 - 2 away.
        outermost = width // 10 - 2
        assert centers[-1] + outermost <= tops[band], (band, width, centers[-1])
        assert centers[0] - outermost >= bottoms[band], (band, width, centers[0])


def test_each_chip_declares_the_widest_capture_it_has_evidence_for():
    import mt7925u

    # A width above these makes the radio return nothing rather than fail, so a caller
    # must be able to refuse it before tuning. Raising either needs hardware evidence.
    assert m.Mt7921uDevice.MAX_WIDTH_MHZ == 80
    assert mt7925u.Mt7925uDevice.MAX_WIDTH_MHZ == 160
    for chip in (m.Mt7921uDevice, mt7925u.Mt7925uDevice):
        assert chip.MAX_WIDTH_MHZ in m.WIDTH_TO_SNIFFER_BW


def test_the_uppermost_five_ghz_forty_megahertz_block_exists():
    # Operating classes 126/127 define a 40 MHz block centered at 175, holding control
    # channels 173 and 177. The 80 MHz block at 171 and the 160 MHz block at 163 already
    # reach that far, so omitting it refused a channel the other widths accept.
    assert m.center_channel("5GHz", 173, 40) == 175
    assert m.center_channel("5GHz", 177, 40) == 175
    assert len(m.CENTER_CHANNELS[("5GHz", 40)]) == 14


@pytest.mark.parametrize(
    ("band", "channel"),
    [("5GHz", 999), ("2.4GHz", 999), ("6GHz", 234), ("5GHz", 34), ("2.4GHz", 15), ("6GHz", 0)],
)
def test_a_channel_the_band_does_not_have_is_refused_at_twenty_megahertz_too(band, channel):
    # A 20 MHz channel is its own center, so without a channel-plan check any integer
    # would validate and be handed to the firmware.
    assert m.center_channel(band, channel, 20) is None


@pytest.mark.parametrize(
    ("band", "channel"),
    [("2.4GHz", 1), ("2.4GHz", 14), ("5GHz", 36), ("5GHz", 177), ("6GHz", 1), ("6GHz", 233)],
)
def test_the_edges_of_each_band_are_still_accepted(band, channel):
    assert m.center_channel(band, channel, 20) == channel


def test_six_ghz_channel_two_is_a_real_twenty_megahertz_channel():
    # center_idx_to_bw_6ghz() reports 20 MHz for index 2 specifically, so it is valid at
    # 20 MHz even though it belongs to no wider block.
    assert m.center_channel("6GHz", 2, 20) == 2
    assert m.center_channel("6GHz", 2, 40) is None
    assert m.center_channel("6GHz", 2, 80) is None


def test_every_control_channel_a_block_implies_is_in_its_band_plan():
    for (band, width), centers in m.CENTER_CHANNELS.items():
        outermost = width // 10 - 2
        for center in centers:
            for offset in range(-outermost, outermost + 1, 4):
                channel = center + offset
                assert channel in m.CONTROL_CHANNELS[band], (band, width, center, channel)


def test_each_band_has_the_number_of_twenty_megahertz_channels_it_is_defined_to_have():
    assert len(m.CONTROL_CHANNELS["2.4GHz"]) == 14
    assert len(m.CONTROL_CHANNELS["5GHz"]) == 28
    # 59 channels at 1, 5, 9 ... 233, plus the standalone channel 2.
    assert len(m.CONTROL_CHANNELS["6GHz"]) == 60
