# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Offline boundaries for the opt-in Windows register experiment."""

from types import SimpleNamespace

import pytest

import mt7921u as m
from research.windows import boot_alias_probe as probe


def test_refuse_other_chip_before_returning_device_and_restore_on_exit(monkeypatch):
    def factory(*args, **kwargs):
        return SimpleNamespace(CHIP=m.CHIP_MT7925)

    def delegated_script(*args, **kwargs):
        m.open_device("0846:9072")

    monkeypatch.setattr(m, "open_device", factory)
    monkeypatch.setattr(probe.runpy, "run_path", delegated_script)
    monkeypatch.setattr(probe.sys, "argv", ["probe", "boot"])
    read, write = m.Mt7921u.uhw_rr, m.Mt7921u.uhw_wr
    with pytest.raises(m.UnsupportedDevice, match="only for MT7961"):
        probe.main()
    assert m.open_device is factory
    assert m.Mt7921u.uhw_rr is read
    assert m.Mt7921u.uhw_wr is write


def test_alias_wire_requests_preserve_reset_bus_and_device_selectors(monkeypatch):
    requests = []
    selections = []
    device = m.Mt7921uDevice()

    def factory(usb_id, verbose=False, address=None):
        selections.append((usb_id, verbose, address))
        return device

    def vendor(request, request_type, value, index, data_or_len, timeout=1000):
        requests.append((request, request_type, (value << 16) | index, data_or_len))
        return b"\x00" * 4

    def delegated_script(*args, **kwargs):
        selected = m.open_device("0e8d:7961", verbose=True, address="1:5")
        for register in (
            m.MT_SSUSB_EPCTL_CSR_EP_RST_OPT,
            m.MT_UDMA_CONN_INFRA_STATUS_SEL,
            m.MT_CBTOP_RGU_WF_SUBSYS_RST,
        ):
            selected.uhw_rr(register)
            selected.uhw_wr(register, 1)
        raise SystemExit(0)

    monkeypatch.setattr(device, "_vendor", vendor)
    monkeypatch.setattr(m, "open_device", factory)
    monkeypatch.setattr(probe.runpy, "run_path", delegated_script)
    monkeypatch.setattr(probe.sys, "argv", ["probe", "capture"])
    read, write = m.Mt7921u.uhw_rr, m.Mt7921u.uhw_wr
    with pytest.raises(SystemExit) as result:
        probe.main()
    assert result.value.code == 0
    assert selections == [("0e8d:7961", True, "1:5")]
    assert [(r, t, a) for r, t, a, _ in requests] == [
        (0x63, 0xDF, 0x74011890),
        (0x66, 0x5F, 0x74011890),
        (0x63, 0xDF, m.MT_UDMA_CONN_INFRA_STATUS_SEL),
        (0x66, 0x5F, m.MT_UDMA_CONN_INFRA_STATUS_SEL),
        (0x01, 0xDE, m.MT_CBTOP_RGU_WF_SUBSYS_RST),
        (0x02, 0x5E, m.MT_CBTOP_RGU_WF_SUBSYS_RST),
    ]
    assert [data for _, _, _, data in requests[1::2]] == [b"\x01\x00\x00\x00"] * 3
    assert m.open_device is factory
    assert m.Mt7921u.uhw_rr is read
    assert m.Mt7921u.uhw_wr is write
