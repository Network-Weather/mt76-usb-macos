# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research.ipi_register_probe import initialized_control


@pytest.mark.parametrize("original", [0, 0xFFFFFFFF, 0xDEADBEEF, 0x20000000])
def test_exact_recovered_fields_only(original):
    value = initialized_control(original)
    assert (value ^ original) & ~0x1EF == 0
    assert value & 0x1EF == 0x121


@pytest.mark.parametrize("original", [-1, 1 << 32, True, 1.5])
def test_invalid_control(original):
    with pytest.raises(ValueError, match="32-bit"):
        initialized_control(original)
