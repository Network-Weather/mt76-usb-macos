/* SPDX-License-Identifier: BSD-3-Clause-Clear */
/* Synthetic-test bridge only; never opens a USB device. */
#include "mt7921_rxd.h"
#include "mt7921_chip.h"
#include <string.h>

/* Fixed scalar output keeps Python tests independent of C struct padding. */
int parity_rx(const unsigned char *raw, unsigned len, int chip, unsigned *v) {
    mt7921_rxd_frame_t frame;
    int result = mt7921_rxd_decoder_for_chip(chip)(raw, len, &frame);
    if (result) return result;
    v[0] = frame.has_timestamp;
    v[1] = frame.timestamp;
    v[2] = frame.group_mask;
    v[3] = frame.g3_words;
    v[4] = frame.g5_words;
    v[5] = frame.frame ? (unsigned)(frame.frame - raw) : 0;
    v[6] = frame.frame_len;
    memcpy(v + 7, frame.g3, sizeof(frame.g3));
    memcpy(v + 11, frame.g5, sizeof(frame.g5));
    return 0;
}
