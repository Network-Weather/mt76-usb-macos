# SPDX-License-Identifier: BSD-3-Clause-Clear
import pytest

from research.ipi_compact_probe import initialization
from research.ipi_hist_cmd import ipi_request


def test_value_position_is_the_only_changed_field():
    assert initialization(False) == ipi_request(0, set_val=1)
    assert initialization(True) == b"\x00\x01" + bytes(18)
    with pytest.raises(ValueError, match="boolean"):
        initialization(1)
