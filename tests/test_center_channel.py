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
