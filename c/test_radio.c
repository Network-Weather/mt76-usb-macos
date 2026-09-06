/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Sanitizer target: deterministic malformed binary input and fault paths. */
#include "mt7921_radio.h"
#include "mt7921_rxd.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int parity_g5_fault(int, int);
int parity_mcu_fault(int, int);
int parity_rate_table(int, unsigned, unsigned *);
int parity_vendor_timeout(unsigned);
int parity_counter_read(int, int);
int parity_thermal_read(int, int, int);

int main(void) {
    const int thermal_modes[] = {0, 1, 2, 5, 6};
    for (int chip = 0; chip < 2; chip++) for (int action = 0; action < 3; action++)
        for (unsigned i = 0; i < sizeof(thermal_modes)/sizeof(*thermal_modes); i++)
            assert(!parity_thermal_read(chip, action, thermal_modes[i]));
    for (int chip = 0; chip < 2; chip++)
        for (int mode = 0; mode < 7; mode++) assert(!parity_counter_read(chip, mode));
    for (unsigned mode = 0; mode < 3; mode++) assert(!parity_vendor_timeout(mode));
    for (int initial = 0; initial < 2; initial++)
        for (int fail = 0; fail < 7; fail++) assert(!parity_g5_fault(fail, initial));
    for (int chip = 0; chip < 2; chip++)
        for (int mode = 0; mode < 4; mode++) assert(!parity_mcu_fault(chip, mode));
    for (int rate = 1; rate <= 2; rate++) for (unsigned mode = 0; mode < 6; mode++) {
        unsigned words[9];
        int ret = parity_rate_table(rate, mode, words);
        assert((ret == 0) == (mode == 0));
    }
    uint32_t seed = 0x79217925;
    for (unsigned trial = 0; trial < 10000; trial++) {
        uint8_t raw[512], txwi[64];
        for (unsigned i = 0; i < sizeof(raw); i++) {
            seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
            raw[i] = (uint8_t)seed;
        }
        unsigned len = seed % sizeof(raw);
        /* Alternate arbitrary and structurally plausible packet headers. */
        if (trial & 1) {
            raw[0] = len & 255; raw[1] = len >> 8;
            raw[3] = trial & 2 ? 2 << 3 : 0;
        }
        for (int chip = 0; chip < 2; chip++) {
            mt7921_rxd_frame_t f;
            mt_tx_status_t statuses[16];
            mt7921_rxd_decoder_for_chip(chip)(raw, len, &f);
            mt_tx_status_parse(chip, raw, len, statuses, 16);
            uint32_t offsets[] = {11, 19, 20}; uint64_t values[3];
            mt_mib_parse(chip, raw, len, offsets, chip ? 3 : 1, values);
            mt_probe_txwi(chip, raw, len, trial % 4096, 1, 0, txwi);
        }
    }
    puts("PASS: radio fault tests and 10,000 malformed-input sanitizer cases");
    return 0;
}
