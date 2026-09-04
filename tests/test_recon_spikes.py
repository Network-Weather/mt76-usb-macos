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
import struct

import pytest

import mt7921u as ms_mod  # the driver itself, for its MCU command-word encoder
from scripts import fw_triage as ft
from scripts import ipi_probe as ip
from scripts import mcu_stats as mcs
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


# ---------------------------------------------------------------- mcu_stats (Spike D)


def test_mcu_command_ids_match_the_upstream_header():
    # mt76 mt76_connac_mcu.h:1292 and :1309 at baseline c5a3bd91.
    assert mcs.MCU_EXT_CMD_GET_MIB_INFO == 0x5A
    assert mcs.MCU_EXT_CMD_PHY_STAT_INFO == 0xAD
    # And the driver's own encoder must put them where fill_message looks.
    assert ms_mod.MCU_EXT_CMD(mcs.MCU_EXT_CMD_GET_MIB_INFO) == 0xED | (0x5A << 8)


def test_the_mib_entry_is_the_sixteen_byte_upstream_struct():
    # struct mt7915_mcu_mib { __le32 band; __le32 offs; __le64 data; }
    assert mcs.MIB_ENTRY_LEN == 16


def test_both_published_offset_schemes_are_carried_and_disagree():
    # The point of sweeping: mt7915 and mt7916 number the same four quantities differently,
    # so MT7921's numbering cannot be assumed from either.
    assert mcs.MIB_OFFSETS_V1[87] == "non_wifi_time"
    assert mcs.MIB_OFFSETS_V2[491] == "non_wifi_time"
    assert not set(mcs.MIB_OFFSETS_V1) & set(mcs.MIB_OFFSETS_V2)
    assert "non_wifi_time" in mcs.NAMED_OFFSETS.values()


def test_build_mib_request_lays_out_one_entry_per_offset_with_zero_data():
    req = mcs.build_mib_request(1, [87, 81])
    assert len(req) == 2 * mcs.MIB_ENTRY_LEN
    band, offs, data = struct.unpack_from(mcs.MIB_ENTRY, req, 0)
    assert (band, offs, data) == (1, 87, 0)
    band, offs, data = struct.unpack_from(mcs.MIB_ENTRY, req, mcs.MIB_ENTRY_LEN)
    assert (band, offs, data) == (1, 81, 0)


def test_reply_parsing_survives_an_unknown_preamble_length():
    # mt7915 skips 20 bytes and mt7916 skips 0; MT7921's is unknown, so the parser locates
    # the echoed {band, offs} pair rather than trusting a fixed offset.
    entry = struct.pack(mcs.MIB_ENTRY, 0, 87, 4242)
    for preamble in (0, 4, 20, 37):
        body = bytes(preamble) + entry
        assert mcs.parse_mib_reply(body, 0, [87]) == {87: 4242}


def test_reply_parsing_reports_nothing_for_an_offset_the_firmware_did_not_echo():
    body = bytes(20) + struct.pack(mcs.MIB_ENTRY, 0, 87, 4242)
    assert mcs.parse_mib_reply(body, 0, [81]) == {}


def test_reply_parsing_does_not_read_past_the_end_of_a_truncated_reply():
    # The pair is echoed but the 64-bit counter behind it is cut off.
    body = bytes(8) + struct.pack("<II", 0, 87) + b"\x01\x02\x03"
    assert mcs.parse_mib_reply(body, 0, [87]) == {}


def test_reply_parsing_keys_on_the_band_so_another_bands_entry_is_not_misread():
    body = struct.pack(mcs.MIB_ENTRY, 1, 87, 999)
    assert mcs.parse_mib_reply(body, 0, [87]) == {}
    assert mcs.parse_mib_reply(body, 1, [87]) == {87: 999}


def test_the_five_named_phy_categories_match_upstream():
    # enum at mt76_connac_mcu.h:1199; anything past 4 is unnamed and is what we are probing.
    assert mcs.PHY_STATE_NAMES == {
        0: "TX_RATE",
        1: "RX_RATE",
        2: "RSSI",
        3: "CONTENTION_RX_RATE",
        4: "OFDMLQ_CNINFO",
    }


def test_parse_sweep_accepts_a_bounded_range():
    assert mcs.parse_sweep("0:16") == range(16)
    assert mcs.parse_sweep("0x50:0x60") == range(80, 96)


@pytest.mark.parametrize("bad", ["16", "8:8", "20:10", "-1:5", "0:2048", "a:b"])
def test_parse_sweep_rejects_inverted_negative_or_oversized_ranges(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        mcs.parse_sweep(bad)


def test_the_batch_size_matches_what_upstream_sends():
    # mt7915 declares req[5] and fills all five; a longer request is a plausible way to
    # earn a blanket refusal that says nothing about the individual offsets.
    assert mcs.MIB_BATCH == 5


def test_code_ranges_cover_the_load_addresses_the_image_declares():
    # The MT7921 RAM image's own region table, plus the mask ROM the patch overlays.
    assert ft.in_code(0x00915000)  # region 0 base
    assert ft.in_code(0xE02767C0)  # the GET_MIB_INFO handler, in region 3 IRAM
    assert ft.in_code(0x00918340)  # a dispatcher in region 0
    assert not ft.in_code(0x1818CDEF)  # a magic number, not an address
    assert not ft.in_code(0x02015C00)  # rodata is not code
    assert not ft.in_code(0)


def test_scan_dispatch_slots_finds_a_handler_cid_pair():
    blob = b"\xff" * 12 + struct.pack("<II", 0xE02767C0, 0x5A) + b"\x00" * 8
    found = ft.scan_dispatch_slots(blob, {0x5A: "GET_MIB_INFO"})
    assert found[0x5A] == [(12, 0xE02767C0)]


def test_scan_dispatch_slots_ignores_a_cid_beside_a_non_code_word():
    blob = struct.pack("<II", 0x1818CDEF, 0x5A)
    assert ft.scan_dispatch_slots(blob, {0x5A: "GET_MIB_INFO"})[0x5A] == []


def test_scan_dispatch_slots_reports_an_absent_cid_as_an_empty_list():
    blob = struct.pack("<II", 0xE02767C0, 0x5A)
    found = ft.scan_dispatch_slots(blob, {0x5A: "x", 0xAD: "PHY_STAT_INFO"})
    assert found[0xAD] == []


def test_the_command_name_table_pins_the_two_ids_the_spikes_depend_on():
    assert ft.EXT_CMD_NAMES[0x5A] == "GET_MIB_INFO"
    assert ft.EXT_CMD_NAMES[0xAD] == "PHY_STAT_INFO"


def test_identical_prefixes_across_every_category_read_as_a_stub():
    # What an MT7921U actually returned on 2026-09-03: one prefix for all 16 categories.
    entries = [{"answered": True, "reply_prefix": "ad000000fe000000"} for _ in range(16)]
    verdict = mcs.judge_phy_sweep(entries)
    assert verdict["distinct_prefixes"] == 1
    assert verdict["verdict"].startswith("stub")


def test_differing_prefixes_are_not_called_a_stub():
    entries = [{"answered": True, "reply_prefix": f"{i:016x}"} for i in range(16)]
    assert not mcs.judge_phy_sweep(entries)["verdict"].startswith("stub")


def test_a_sweep_that_nobody_answered_is_not_called_a_stub():
    entries = [{"answered": False} for _ in range(16)]
    assert mcs.judge_phy_sweep(entries)["answered"] == 0
    assert not mcs.judge_phy_sweep(entries)["verdict"].startswith("stub")


def test_one_identical_prefix_over_only_the_named_categories_is_not_enough():
    # Five categories agreeing proves much less than sixteen; the guard requires more
    # categories than upstream names before calling it a stub.
    entries = [{"answered": True, "reply_prefix": "aa"} for _ in range(5)]
    assert not mcs.judge_phy_sweep(entries)["verdict"].startswith("stub")


def test_the_refusal_signature_is_the_one_measured_on_hardware():
    # 16 bytes: echoed ext_cid then 0xfe. Calibrated against controls in both directions.
    assert mcs.is_refusal(bytes.fromhex("ad000000fe00000000000000f6d7e199"), 0xAD)
    assert mcs.is_refusal(bytes.fromhex("7c000000fe000000") + bytes(8), 0x7C)


def test_a_refusal_for_another_command_is_not_read_as_ours():
    assert not mcs.is_refusal(bytes.fromhex("4a000000fe000000") + bytes(8), 0xAD)


def test_a_real_reply_is_not_mistaken_for_a_refusal():
    # GET_MIB_INFO's 40-byte zeroed echo is dispatched, not refused; length alone separates
    # them, and a zero status word does too.
    assert not mcs.is_refusal(bytes(40), 0x5A)
    assert not mcs.is_refusal(bytes(16), 0x5A)  # right length, but status 0, not 0xfe


def test_a_sweep_that_is_refused_throughout_is_reported_as_not_implemented():
    entries = [
        {"answered": True, "refused": True, "reply_prefix": "ad000000fe000000"} for _ in range(16)
    ]
    assert mcs.judge_phy_sweep(entries)["verdict"].startswith("not implemented")


def test_a_partly_refused_sweep_is_not_reported_as_not_implemented():
    entries = [{"answered": True, "refused": i > 0, "reply_prefix": f"{i:016x}"} for i in range(16)]
    assert not mcs.judge_phy_sweep(entries)["verdict"].startswith("not implemented")
