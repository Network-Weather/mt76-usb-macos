#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Experimental MT7961 WinUSB bring-up with two explicit register aliases.

Run from the repository root with the libusb DLL on PATH. This is a hardware
experiment, not a supported transport. It boots firmware and optionally captures;
no association or packet injection is requested. A failed reset may need a replug.
"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import mt7921u as m  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=("boot", "capture"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    read_uhw = m.Mt7921u.uhw_rr
    write_uhw = m.Mt7921u.uhw_wr
    aliases = {m.MT_SSUSB_EPCTL_CSR_EP_RST_OPT, m.MT_UDMA_CONN_INFRA_STATUS_SEL}

    def read(self, address):
        if address in aliases:
            return self.rr(address)
        return read_uhw(self, address)

    def write(self, address, value):
        if address in aliases:
            return self.wr(address, value)
        return write_uhw(self, address, value)

    # Keep reset assertion/deassertion on the UHW bus; ordinary access may stop
    # responding while the subsystem is held in reset.
    m.Mt7921u.uhw_rr = read
    m.Mt7921u.uhw_wr = write
    path = ROOT / (
        "scripts/firmware_boot.py" if args.tool == "boot" else "examples/sniff_to_pcap.py"
    )
    sys.argv = [str(path), *args.args]
    try:
        runpy.run_path(str(path), run_name="__main__")
    finally:
        m.Mt7921u.uhw_rr = read_uhw
        m.Mt7921u.uhw_wr = write_uhw


if __name__ == "__main__":
    main()
