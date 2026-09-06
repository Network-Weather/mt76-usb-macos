#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Twenty bounded HE/HE-ER MCS0 frames, explicit spatial index1 throughout.

Channel6/20MHz, GI0/LTF1/BCC, no ACK, unchanged power,50ms pacing.
At least two exact HE baseline receipts required before candidate DCM/ER phases.
No association, RF mode, receiver writes beyond normal boot, or ambient export.
Optional upper106 suite brackets upper106/upper106-DCM with full-band ER controls.
Slot18 is read back after every rate change; both radios reload in finally.
SPE1 is a source-defined index, not an independently calibrated physical antenna.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import legacy_ics_probe as legacy
from research import phy_tx_probe as phy
from research import wideband_signal_probe as signal
from research.fixed_rate_readback import read_slot
from research.noise_self_tx_probe import packet
from research.txpower_register_probe import check_image, m

PHASES = (
    ("he1_before", 0x200),
    ("he1_dcm", 0x210),
    ("he_er1", 0x240),
    ("he_er1_dcm", 0x250),
    ("he1_after", 0x200),
)
UPPER106_PHASES = (
    ("er_full_before", 0x240),
    ("er_upper106", 0x260),
    ("er_full_middle", 0x240),
    ("er_upper106_dcm", 0x270),
    ("er_full_after", 0x240),
)


def program(dev, code):
    if (
        dev.CHIP != m.CHIP_MT7925
        or type(code) is not int
        or code not in {c for _, c in PHASES + UPPER106_PHASES}
    ):
        raise ValueError("only pinned MT7925 HE/ER MCS0 rates")
    phy.program_rate(dev, code, ltf=1, spe_idx=1)
    words = read_slot(dev, 18)
    if words != (code, 0x10080):
        raise ValueError("indexed fixed-rate table mismatch")
    return [hex(w) for w in words]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    parser.add_argument("--upper106", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_experimental_transmit:
        parser.error("explicit bounded transmit acknowledgment required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "maximum_submissions": 20,
        "channel": 6,
        "width_mhz": 20,
        "table_spatial_index": 1,
        "gi": 0,
        "ltf": 1,
        "ldpc": 0,
        "suite": "upper106" if args.upper106 else "dcm",
        "phases": [],
    }
    with contextlib.ExitStack() as stack:
        rx, tx = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        radios = (rx, tx)
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        check_image(images[1][1])
        if hashlib.sha256(images[0][1]).hexdigest() != legacy.OLD_RAM_SHA256:
            raise ValueError("pinned receiver firmware required")

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            for i in (0, 1):
                boot(i)
            nonce = os.urandom(8)
            for index, (name, code) in enumerate(UPPER106_PHASES if args.upper106 else PHASES):
                table = program(tx, code)
                packets = {i: packet(tx, i, nonce, 0) for i in range(index * 4, index * 4 + 4)}
                row = signal.acquire(tx, rx, packets)
                row.update(name=name, rate_code=hex(code), indexed_table=table)
                out["phases"].append(row)
                if not index and len(row["good_receipts"]) < 2:
                    raise ValueError("at least two exact normal HE control receipts required")
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            out["cleanup_reload_alive"] = []
            for i in (0, 1):
                try:
                    boot(i)
                    out["cleanup_reload_alive"].append(radios[i].alive())
                except Exception:
                    out["cleanup_reload_alive"].append(False)
    print(json.dumps(out, indent=2))
    return int("error_type" in out or not all(out["cleanup_reload_alive"]))


if __name__ == "__main__":
    raise SystemExit(main())
