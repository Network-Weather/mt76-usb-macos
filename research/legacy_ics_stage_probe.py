#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Twenty known HT frames across existing RF entry/setup/start/stop operations.

No new RF selectors or register writes. Reassert known CE93 ICS per stage because
mode entry may reset it; this is an operation-level test, not single-bit causality.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import legacy_ics_own_probe as own
from research import legacy_ics_probe as legacy
from research.legacy_ics_rf_probe import frequency_request
from research.noise_self_tx_probe import packet
from research.testmode_receiver_probe import rx_setting
from research.txpower_register_probe import check_image, m

STAGES = ("normal_ics", "rf_entered", "rf_configured", "rf_started", "rf_stopped")


def stage_commands(stage):
    if stage not in STAGES:
        raise ValueError("only five fixed stages")
    if stage == "rf_entered":
        return [struct.pack("<B3xII", 0, 1, 0)]
    if stage == "rf_configured":
        return [
            rx_setting(1, 0),
            rx_setting(104, 0),
            rx_setting(106, 3 << 16),
            frequency_request(6),
            rx_setting(15, 0),
        ]
    if stage in ("rf_started", "rf_stopped"):
        return [rx_setting(1, 2 if stage == "rf_started" else 0)]
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-rf-stages", action="store_true")
    parser.add_argument("--acknowledge-experimental-transmit", action="store_true")
    args = parser.parse_args()
    if not (args.activate_rf_stages and args.acknowledge_experimental_transmit):
        parser.error("explicit RF stages and transmit acknowledgments required")
    out = {
        "date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "max_submissions": 20,
        "channel": 6,
        "phases": [],
    }
    originals, attempted, rf_attempted = {}, False, False
    with contextlib.ExitStack() as stack:
        rx, tx = [stack.enter_context(m.open_device(uid)) for uid in ("0e8d:7961", "0846:9072")]
        radios = (rx, tx)
        images = [m.load_firmware(dev.CHIP, m.firmware_dir()) for dev in radios]
        check_image(images[1][1])
        if hashlib.sha256(images[0][1]).hexdigest() != legacy.OLD_RAM_SHA256:
            raise ValueError("pinned MT7961 required")

        def boot(i):
            dev = radios[i]
            dev.bringup(*images[i], log=lambda *_: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            dev.tune("2.4GHz", 6, 6, 20)

        try:
            for i in (0, 1):
                boot(i)
            out["verified_receiver"] = legacy.verify(rx)
            originals = {a: legacy.valid_word(rx.rr(a)) & mask for a, mask in legacy.MASKS.items()}
            if originals[0x820E50D0] or originals[0x820E705C] or rx.rr(0x820E4120) & 1:
                raise ValueError("ICS already active")
            own.phy.program_rate(tx, 0x488)
            nonce = os.urandom(8)
            for index, stage in enumerate(STAGES):
                if stage == "rf_entered":
                    rf_attempted = True
                for request in stage_commands(stage):
                    rx.mcu_cmd_word(m.MCU_CE_CMD(1), request, wait=False)
                    time.sleep(0.2 if stage == "rf_entered" else 0.1)
                attempted = True
                legacy.send(rx, True)
                time.sleep(0.05)
                before = legacy.masks(rx)
                if before["0x820e50d0"] != 1 or before["0x820e705c"] != 1 << 24:
                    raise ValueError("ICS reassertion did not read back")
                packets = {i: packet(tx, i, nonce, 0) for i in range(index * 4, index * 4 + 4)}
                phase = own.acquire(tx, rx, packets)
                phase.update(
                    {"stage": stage, "masks_before": before, "masks_after": legacy.masks(rx)}
                )
                out["phases"].append(phase)
                if not index and len(phase["exact_good_phy"]) != 4:
                    raise ValueError("four normal full-payload good-FCS controls required")
        except Exception as exc:
            out["error_type"] = type(exc).__name__
        finally:
            if rf_attempted:
                try:
                    rx.mcu_cmd_word(m.MCU_CE_CMD(1), rx_setting(1, 0), wait=False)
                except Exception as exc:
                    out["rf_stop_error_type"] = type(exc).__name__
            if attempted:
                try:
                    legacy.send(rx, False)
                    out["restored"] = legacy.restore(rx, originals)
                except Exception as exc:
                    out["restore_error_type"] = type(exc).__name__
            out["cleanup_reload_alive"] = []
            for i in (0, 1):
                try:
                    boot(i)
                    out["cleanup_reload_alive"].append(radios[i].alive())
                except Exception:
                    out["cleanup_reload_alive"].append(False)
    print(json.dumps(out, indent=2))
    return int(
        any(k.endswith("error_type") for k in out)
        or not all(out.get("cleanup_reload_alive", [False]))
        or not all(out.get("restored", {}).values())
    )


if __name__ == "__main__":
    raise SystemExit(main())
