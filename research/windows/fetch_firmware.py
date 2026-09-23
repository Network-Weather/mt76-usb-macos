#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Fetch only the MT7961 blobs pinned in mt7921u, checking hashes before writing."""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import mt7921u as m  # noqa: E402


def main() -> None:
    base = (
        "https://gitlab.com/kernel-firmware/linux-firmware/-/raw/"
        f"{m.LINUX_FIRMWARE_COMMIT}/mediatek/"
    )
    for relative, expected in m.FIRMWARE_FILES[m.CHIP_MT7921]:
        path = ROOT / "firmware" / relative
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            print(f"{relative}: SHA-256 verified")
            continue
        # The URL comes solely from the fixed HTTPS origin and repository constants.
        with urllib.request.urlopen(base + relative, timeout=60) as response:  # noqa: S310
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"{relative}: downloaded firmware SHA-256 mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"{relative}: downloaded and SHA-256 verified")


if __name__ == "__main__":
    main()
