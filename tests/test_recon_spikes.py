# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Offline tests for the firmware/PHY reconnaissance spikes.

No adapter, no firmware upload, no USB. These cover the pure helpers that decide what a
reading means -- the classification thresholds, the plausibility guards, and the noise-floor
arithmetic -- so that a spike cannot silently start calling an unmapped register block a
measurement. See docs/FIRMWARE_RECON.md.
"""

import argparse
import math

import pytest

from scripts import fw_triage as ft
from scripts import ipi_probe as ip
from scripts import mib_survey as ms

# ---------------------------------------------------------------- fw_triage (Spike C)


def test_entropy_of_a_single_repeated_byte_is_zero():
    assert ft.entropy(b"\x00" * 4096) == 0.0


def test_entropy_of_a_uniform_byte_range_is_eight_bits():
    assert math.isclose(ft.entropy(bytes(range(256)) * 16), 8.0, abs_tol=1e-9)


def test_entropy_of_empty_input_is_zero_rather_than_a_domain_error():
    assert ft.entropy(b"") == 0.0


def test_feature_flag_bits_match_the_upstream_header():
    # mt76 mt76_connac_mcu.h:9-13 at baseline c5a3bd91.
    assert ft.FW_FEATURE_SET_ENCRYPT == 0x01
    assert ft.FW_FEATURE_SET_KEY_IDX == 0x06
    assert ft.FW_FEATURE_ENCRY_MODE == 0x10
    assert ft.FW_FEATURE_OVERRIDE_ADDR == 0x20
    assert ft.FW_FEATURE_NON_DL == 0x40


def test_feature_flags_name_the_bits_measured_in_the_pinned_images():
    # The five values the two RAM images actually carry, 2026-09-03.
    assert ft.feature_flags(0x20) == ["OVERRIDE_ADDR"]
    assert ft.feature_flags(0x00) == []
    assert ft.feature_flags(0x40) == ["NON_DL"]
    assert ft.feature_flags(0x21) == ["ENCRYPT", "OVERRIDE_ADDR", "KEY_IDX=0"]
    assert ft.feature_flags(0x01) == ["ENCRYPT", "KEY_IDX=0"]


def test_feature_flags_report_a_nonzero_key_index():
    assert "KEY_IDX=3" in ft.feature_flags(ft.FW_FEATURE_SET_ENCRYPT | 0b110)


def test_encryption_is_taken_from_the_header_not_from_entropy():
    # A declared-encrypted region stays encrypted however readable its bytes look, and a
    # plain region is never called encrypted just because it is dense. This is the whole
    # point of the rewrite: entropy corroborates, the header decides.
    assert ft.classify_region(ft.FW_FEATURE_SET_ENCRYPT, 1.0, 9999, 4096) == "encrypted"
    assert ft.classify_region(0, 6.874, 224, 363536) == "code"


def test_a_non_downloaded_region_is_named_for_what_it_is():
    # Both images carry one at load address 0, packed, never sent to the chip.
    assert ft.classify_region(ft.FW_FEATURE_NON_DL, 7.951, 266, 88416) == "not-downloaded"
    assert ft.classify_region(ft.FW_FEATURE_NON_DL, 7.465, 864, 303936) == "not-downloaded"


def test_the_measured_mt7921_regions_classify_as_code_text_and_table():
    # Values measured from WIFI_RAM_CODE_MT7961_1.bin on 2026-09-03.
    assert ft.classify_region(0, 6.874, 224, 363536) == "code"  # r0
    assert ft.classify_region(0, 2.548, 1457, 272400) == "text"  # r1, the string region
    assert ft.classify_region(0, 3.953, 0, 15376) == "table"  # r2, no strings at all
    assert ft.classify_region(0, 6.799, 30, 51920) == "code"  # r3


def test_a_plain_region_that_is_still_random_is_called_packed_not_code():
    assert ft.classify_region(0, 7.99, 10, 100000) == "packed"


def test_an_empty_region_is_not_misreported_as_text():
    assert ft.classify_region(0, 0.0, 0, 0) == "empty"


def test_every_unreadable_kind_carries_a_stated_reason():
    kinds = {"encrypted", "packed", "not-downloaded", "empty"}
    assert set(ft.UNREADABLE_REASONS) == kinds
    assert not kinds & ft.READABLE_KINDS
    assert all(ft.UNREADABLE_REASONS[k] for k in kinds)


def test_patch_section_encryption_matches_the_pinned_images():
    # mt76_connac2_get_data_mode reads PATCH_SEC_ENC_TYPE_MASK, GENMASK(31, 24), from
    # sec_key_idx. MT7921's patch declares 0x0 and MT7925's declares 0x1000000.
    assert ft.patch_section_encryption(0x00000000) == "PLAIN"
    assert ft.patch_section_encryption(0x01000000) == "AES"
    assert ft.patch_section_encryption(0x02000000) == "SCRAMBLE"


def test_patch_section_not_support_is_plain_because_the_loader_short_circuits():
    assert ft.patch_section_encryption(ft.PATCH_SEC_NOT_SUPPORT) == "PLAIN"


def test_an_unknown_patch_encryption_type_is_reported_rather_than_assumed_plain():
    assert "UNKNOWN" in ft.patch_section_encryption(0x7F000000)


def test_extract_strings_honours_the_minimum_length():
    blob = b"\x00\x01abc\x00abcdefgh\x00"
    assert ft.extract_strings(blob, 6) == ["abcdefgh"]
    assert sorted(ft.extract_strings(blob, 3)) == ["abc", "abcdefgh"]


def test_extract_strings_rejects_a_nonsense_minimum():
    with pytest.raises(ValueError, match="min_len"):
        ft.extract_strings(b"whatever", 0)


def test_symbol_inventory_groups_by_instrument_class():
    strings = [
        "rdmGetIpiHist",
        "EdccaTh2gBw20",
        "[rdmRddStart] RDD HW address",
        "MT_MIB_SDR9",
        "nothing to do with radios",
    ]
    inv = ft.symbol_inventory(strings)
    assert "rdmGetIpiHist" in inv["ipi"]["samples"]
    assert "EdccaTh2gBw20" in inv["edcca"]["samples"]
    assert inv["radar"]["count"] == 1
    assert inv["mib"]["count"] == 1
    # Every class carries its own justification, so a report says why a hit matters.
    assert all(info["why"] for info in inv.values())


def test_every_symbol_class_pattern_compiles_and_is_documented():
    inv = ft.symbol_inventory([])
    assert set(inv) == set(ft.SYMBOL_CLASSES)
    assert all(v["count"] == 0 for v in inv.values())


# ---------------------------------------------------------------- mib_survey (Spike A)


def test_mib_register_addresses_match_the_upstream_header():
    # mt76 mt792x_regs.h at baseline c5a3bd91, band 0. Transcribed constants are worth
    # exactly as much as the arithmetic behind them, so pin the resulting addresses.
    assert ms.MT_WF_MIB_BASE == 0x820ED000
    assert ms.MT_MIB_SCR1 == 0x820ED004
    assert ms.MT_MIB_SDR9 == 0x820ED02C
    assert ms.MT_MIB_SDR36 == 0x820ED054
    assert ms.MT_MIB_SDR37 == 0x820ED058
    assert ms.MT_WF_RMAC_MIB_AIRTIME0 == 0x820E5380
    assert ms.MT_WF_RMAC_MIB_AIRTIME14 == 0x820E53B8
    assert ms.MT_WF_RMAC_MIB_TIME0 == 0x820E53C4


def test_counter_fields_are_the_documented_twenty_four_bits():
    assert ms.COUNTER_MASK == 0xFFFFFF
    assert ms.COUNTER_WRAP_US == 0x1000000
    # The CLI cap must keep a dwell short enough that a wrap cannot be mistaken for traffic.
    assert ms.COUNTER_WRAP_US > 10 * 1_000_000


def test_plausible_rejects_an_all_zero_read():
    assert ms.plausible(dict.fromkeys(ms.COUNTERS, 0)) is not None


def test_plausible_rejects_an_all_ones_read():
    assert ms.plausible(dict.fromkeys(ms.COUNTERS, ms.COUNTER_MASK)) is not None


def test_plausible_accepts_a_mixed_read():
    counters = dict.fromkeys(ms.COUNTERS, 0)
    counters["cca_busy"] = 1234
    assert ms.plausible(counters) is None


def test_parse_target_defaults_center_to_control_and_width_to_twenty():
    assert ms.parse_target("5GHz:36") == ("5GHz", 36, 36, 20)
    assert ms.parse_target("5GHz:36:42:80") == ("5GHz", 36, 42, 80)


@pytest.mark.parametrize("bad", ["36", "9GHz:36", "5GHz:x", "5GHz:36:42:33"])
def test_parse_target_rejects_malformed_input(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        ms.parse_target(bad)


# ---------------------------------------------------------------- ipi_probe (Spike B)


def test_irpi_addresses_follow_the_mt7915_layout_under_test():
    assert ip.MT_WF_IRPI_BASE == 0x83000000
    assert ip.MT_WF_PHY_BASE == 0x83080000
    # MT_WF_IRPI_NSS(0, nss) = base + 0x6000 + (nss << 16)
    base0 = ip.MT_WF_IRPI_BASE + ip.MT_WF_IRPI_NSS_OFFSET
    assert base0 == 0x83006000
    assert base0 + ip.MT_WF_IRPI_NSS_STRIDE == 0x83016000


def test_nf_power_table_matches_mt7915_and_has_eleven_bins():
    assert ip.NF_POWER == (92, 89, 86, 83, 80, 75, 70, 65, 60, 55, 52)
    assert ip.IRPI_BINS == 11


def test_all_zero_bins_are_not_a_histogram():
    ok, why = ip.looks_like_histogram([0] * 11, [0] * 11)
    assert not ok
    assert "0 or all-ones" in why


def test_all_ones_bins_are_not_a_histogram():
    dead = [0xFFFFFFFF] * 11
    ok, _ = ip.looks_like_histogram(dead, dead)
    assert not ok


def test_a_constant_nonzero_read_is_not_a_distribution():
    ok, why = ip.looks_like_histogram([7] * 11, [7] * 11)
    assert not ok
    assert "same value" in why


def test_static_counters_are_rejected_even_when_they_look_like_a_distribution():
    bins = [5, 9, 2, 40, 3, 0, 1, 0, 0, 0, 0]
    ok, why = ip.looks_like_histogram(bins, bins)
    assert not ok
    assert "no bin grew" in why


def test_growing_bins_are_accepted():
    before = [5, 9, 2, 40, 3, 0, 1, 0, 0, 0, 0]
    after = [9, 14, 2, 61, 3, 0, 1, 0, 0, 0, 0]
    ok, why = ip.looks_like_histogram(before, after)
    assert ok
    assert "grew" in why


def test_mostly_decreasing_bins_are_rejected_as_non_monotonic():
    before = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10]
    after = [11, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    ok, why = ip.looks_like_histogram(before, after)
    assert not ok
    assert "decreased" in why


def test_noise_floor_of_an_empty_histogram_is_undefined_not_zero():
    assert ip.noise_floor_dbm([0] * 11) is None


def test_noise_floor_of_a_single_bin_is_that_bins_level():
    bins = [0] * 11
    bins[0] = 100
    assert ip.noise_floor_dbm(bins) == -92.0
    bins = [0] * 11
    bins[-1] = 7
    assert ip.noise_floor_dbm(bins) == -52.0


def test_noise_floor_is_the_count_weighted_mean_of_the_bin_levels():
    bins = [0] * 11
    bins[0], bins[10] = 1, 1  # -92 and -52 in equal measure
    assert ip.noise_floor_dbm(bins) == -72.0


def test_parse_window_accepts_hex_bounds():
    assert ip.parse_window("0x83006000:0x83007000") == (0x83006000, 0x83007000)


def test_the_default_window_is_within_the_transfer_budget_it_declares():
    lo, hi = ip.DEFAULT_WINDOW
    assert (hi - lo) // 4 <= ip.MAX_WORDS
    assert ip.parse_window(f"{lo:#x}:{hi:#x}") == ip.DEFAULT_WINDOW


def test_the_default_window_contains_the_first_chains_histogram():
    lo, hi = ip.DEFAULT_WINDOW
    base0 = ip.MT_WF_IRPI_BASE + ip.MT_WF_IRPI_NSS_OFFSET
    assert lo <= base0
    assert base0 + 4 * ip.IRPI_BINS <= hi


@pytest.mark.parametrize("bad", ["0x1", "0x4:0x0", "0x1:0x8", "0x0:0x100000", "not:hex"])
def test_parse_window_rejects_misaligned_inverted_or_oversized_ranges(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        ip.parse_window(bad)


def test_source_files_extracts_the_firmwares_own_build_paths():
    strings = [
        "assert at wifi/core/wificore/rlm/rdm_phy.c line 210",
        "mcu/coex/_core/conn_coex_cmm.c",
        "no path here at all",
    ]
    found = ft.source_files(strings)
    assert "wifi/core/wificore/rlm/rdm_phy.c" in found
    assert "mcu/coex/_core/conn_coex_cmm.c" in found
    assert len(found) == 2


def test_source_files_ignores_a_bare_extension_without_a_stem():
    assert ft.source_files(["ends in .c", "and .h too"]) == []
