# SPDX-License-Identifier: BSD-3-Clause-Clear
"""MT7961 statistics-builder formulas; firmware names, not calibrated units.

Band0 cached C-RXV word7/8 -> output26/27/30/31 (FAGC names).
PHY register bank0/1 upper bytes -> output10..13 and34/35/38/39.
"""


def u32(word):
    if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
        raise ValueError("unsigned32 source word required")
    return word


def s8(value):
    value &= 255
    return value - 256 if value & 128 else value


def instantaneous(word):
    word = u32(word)
    return {"inst_ib_raw_s8": s8(word >> 24), "inst_wb_raw_s8": s8(word >> 16)}


def fagc_band0(word7, word8):
    word7, word8 = u32(word7), u32(word8)
    # Fractional low bits in the reconstructed9-bit values are discarded by
    # the firmware's logical >>1 BEFORE signed8 interpretation.
    return {
        "fagc_ib0_raw_s8": s8(word7),
        "fagc_ib1_raw_s8": s8(word7 >> 8),
        "fagc_wb0_raw_s8": s8(word8 >> 5),
        "fagc_wb1_raw_s8": s8(word8 >> 14),
    }


def expected_statistics(fagc, bank0, bank1):
    return {
        10: bank0["inst_wb_raw_s8"],
        11: bank0["inst_ib_raw_s8"],
        12: bank1["inst_wb_raw_s8"],
        13: bank1["inst_ib_raw_s8"],
        26: fagc["fagc_ib0_raw_s8"],
        27: fagc["fagc_ib1_raw_s8"],
        30: fagc["fagc_wb0_raw_s8"],
        31: fagc["fagc_wb1_raw_s8"],
        34: bank0["inst_ib_raw_s8"],
        35: bank1["inst_ib_raw_s8"],
        38: bank0["inst_wb_raw_s8"],
        39: bank1["inst_wb_raw_s8"],
    }
