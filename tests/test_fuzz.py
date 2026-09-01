# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Network Weather, Inc.
"""Random-input robustness for the parsers that face untrusted bytes.

Every parser here consumes data straight off the USB endpoint or out of the air. The
contract is that arbitrary input returns a value or None and never raises. Random bytes
rarely satisfy structural preconditions deep inside a parser, so a pass proves bounds
discipline at the entry points, not coverage of every branch; structured fuzzing is
roadmap work (R20).
"""

import random

import pytest

import rxd

# Deterministic so a failure reproduces from the printed seed and index.
SEED = 20260901
# Lengths straddle every fixed-size boundary the parsers check: the 24-byte RX
# descriptor, MAC header sizes (10, 16, 24, 30), IE headers, and typical MTUs.
LENGTHS = (0, 1, 2, 3, 4, 7, 8, 10, 15, 16, 23, 24, 25, 30, 31, 32, 36, 40, 64, 100, 200, 1500)
ROUNDS = 2000


@pytest.mark.parametrize("parser", [rxd.decode, rxd.parse_80211, rxd.parse_ies])
def test_random_bytes_never_raise(parser):
    rng = random.Random(SEED)  # noqa: S311 - test input, not security
    for index in range(ROUNDS):
        length = rng.choice(LENGTHS)
        data = rng.randbytes(length)
        try:
            parser(data)
        except Exception as exc:
            pytest.fail(f"{parser.__name__} raised {exc!r} on input {index} ({data.hex()})")
