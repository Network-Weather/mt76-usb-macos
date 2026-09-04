#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Which MCU commands does this firmware actually implement? Ask it.

A dispatch slot in the firmware image says a command *might* be implemented; it is not proof.
`RX_AIRTIME_CTRL` (0x4a) has exactly one slot and the firmware refuses it outright. What does
settle the question is the reply: an unimplemented command id returns 16 bytes, the echoed
ext_cid then 0xfe, produced at dispatch before any handler runs.

This calibrates that signature in both directions on every run, because a probe whose oracle
is untested is worth nothing: two commands known to work must not produce the refusal, and
two ids with no dispatch slot in the image must produce it exactly. If a control disagrees,
the run says so and stops rather than reporting confident nonsense.

**This sends commands.** The probe list is deliberately short and read-shaped; it is not a
sweep of the whole id space, because sending an arbitrary id with an arbitrary payload runs
whatever handler is behind it. Adding an id here is a decision, not a parameter.

Usage: mcu_command_probe.py [--band 5GHz --channel 36]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import mcu_stats as mcs  # noqa: E402
import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402

#: Commands known to work on this part, via the driver's own code paths. Neither may produce
#: the refusal signature; if one does, the oracle is wrong and every other result is void.
POSITIVE_CONTROLS = (
    (0x2C, "THERMAL_CTRL", struct.pack("<BBB5x", 2, 0, 0), False),
    (0x01, "EFUSE_ACCESS", struct.pack("<II", 4, 0) + bytes(16), True),
)
#: Ids with no dispatch slot anywhere in the firmware image (fw_triage.py --command-map).
#: Both must produce the refusal, or the oracle is not detecting what it claims to.
NEGATIVE_CONTROLS = (
    (0x7C, "SET_RADAR_TH", bytes(8)),
    (0x38, "SET_FEATURE_CTRL", bytes(8)),
)
#: The commands under investigation. Read-shaped: each asks for a value or acknowledges.
#: See docs/FIRMWARE_RECON.md for why each is here and what is still unknown about it.
PROBES = (
    (0x5A, "GET_MIB_INFO", struct.pack("<IIQ", 0, 11, 0), False),
    (0xAD, "PHY_STAT_INFO", struct.pack("<BBH", 2, 0, 0), False),
    (0x4A, "RX_AIRTIME_CTRL", bytes(136), False),
    (0xA3, "RDD_IPI_HIST_CTRL", struct.pack("<BBBBiIII", 12, 0, 0, 0, 0, 0, 0, 0), True),
    (0x70, "EDCCA_CTRL", struct.pack("<BBBB", 0, 0, 0, 0), False),
)
TIMEOUT_MS = 2500


def send(dev, cid: int, payload: bytes, query: bool = False) -> dict:
    cmd = m.MCU_EXT_CMD(cid) | (m.MCU_CMD_FIELD_QUERY if query else 0)
    try:
        body = dev.reply_body(dev.mcu_cmd_word(cmd, payload, timeout=TIMEOUT_MS))
    except (m.McuError, RuntimeError, usb.core.USBError) as exc:
        # Neither answered nor refused. RDD_ON_OFF_CTRL behaves this way and it is the one
        # outcome the refusal oracle cannot interpret, so it gets its own state.
        return {"cid": cid, "state": "silent", "detail": str(exc)[:80]}
    if mcs.is_refusal(body, cid):
        return {"cid": cid, "state": "refused", "reply_bytes": len(body)}
    return {
        "cid": cid,
        "state": "answered",
        "reply_bytes": len(body),
        "reply_head": body[:24].hex(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--band", default="5GHz", choices=sorted(m.CHAN_BAND))
    parser.add_argument("--channel", type=int, default=36)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dev = m.open_device()
    patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
    out: dict = {
        "tool": "mcu_command_probe",
        "mt76_usb_macos": m.__version__,
        "chip": dev.CHIP,
        "controls": [],
        "probes": [],
    }
    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.tune(args.band, args.channel, args.channel, 20)

        oracle_ok = True
        for cid, name, payload, query in POSITIVE_CONTROLS:
            r = send(dev, cid, payload, query) | {"name": name, "expect": "answered"}
            r["control_held"] = r["state"] == "answered"
            oracle_ok &= r["control_held"]
            out["controls"].append(r)
        for cid, name, payload in NEGATIVE_CONTROLS:
            r = send(dev, cid, payload) | {"name": name, "expect": "refused"}
            r["control_held"] = r["state"] == "refused"
            oracle_ok &= r["control_held"]
            out["controls"].append(r)
        out["oracle_calibrated"] = oracle_ok

        if oracle_ok:
            for cid, name, payload, query in PROBES:
                out["probes"].append(send(dev, cid, payload, query) | {"name": name})

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("controls (the oracle must hold in both directions):")
        for r in out["controls"]:
            mark = "ok " if r["control_held"] else "FAIL"
            print(
                f"  {mark} 0x{r['cid']:02x} {r['name']:<20} expected {r['expect']:<9} "
                f"got {r['state']}"
            )
        if not oracle_ok:
            print(
                "\nrefusing to report probe results: the oracle did not calibrate", file=sys.stderr
            )
            return 2
        print("\nprobes:")
        for r in out["probes"]:
            extra = f"  {r.get('reply_bytes', '')}B {r.get('reply_head', '')[:32]}"
            print(f"  0x{r['cid']:02x} {r['name']:<20} {r['state']:<9}{extra}")
    return 0 if oracle_ok else 2


if __name__ == "__main__":
    sys.exit(main())
