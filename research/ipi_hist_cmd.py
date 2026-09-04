#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Can RDD_IPI_HIST_CTRL be made to report a noise floor? Not yet, and this is how far it got.

The MT7921 driver reports no noise floor at all: mt792x_mac.c:216 mt792x_phy_get_nf() is
`return 0;`. The firmware carries the machinery -- rdmGetIpiHist, rdmSetIpiHist -- and the
command that should reach it, EXT 0xa3, is implemented and accepted here. Its reply carries
eleven power bins from "<= -92 dBm" up to "> -55 dBm", plus a counter that free-runs once per
8 us and is the denominator that turns bin counts into dwell fractions.

**Settled, measured 2026-09-03.** The QUERY bit is required: without it the command returns a
16-byte acknowledgement, with it exactly 56 bytes matching the documented event layout, the
index correctly echoed for every value tried. So the transport and the reply format are
known.

**Open.** The sampler never starts. Every bin reads zero and so does the free-running counter,
which should tick regardless of what the radio hears. This script tries the starts that are
known about, reports which are accepted, refused or silent, and reads the histogram after
each, so the next attempt begins from evidence rather than from scratch.

**This sends SET commands** -- IPI init and reset, and optionally RDD start. All are
receive-side configuration; nothing transmits.

Usage: ipi_hist_cmd.py [--band 5GHz --channel 36] [--seconds 4] [--rdd]
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import mcu_stats as mcs  # noqa: E402
import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402

EXT_CMD_RDD_IPI_HIST_CTRL = 0xA3
EXT_CMD_RDD_ON_OFF_CTRL = 0x3A

#: ENUM_RDD_SET_IPI_HIST_TYPE: CR init, histogram reset, idle-power parameters.
IPI_SET_CR_INIT, IPI_SET_HIST_RESET, IPI_SET_IDLE_PWR = 0, 1, 2
#: ENUM_RDD_GET_IPI_HIST_TYPE: bins 0-10 individually, then a free-run counter and aggregates.
IPI_GET_FREE_RUN, IPI_GET_ALL, IPI_GET_0_TO_10 = 11, 12, 13
IPI_BIN_COUNT = 12
#: The reply is the documented event: u8 idx, u8 band, u8 rsv[2], u32 val[12], u32 tx_assert.
IPI_REPLY_LEN = 56
IPI_VALUES_AT = 4
#: Upper bound of each bin in dBm, from the vendor enum's own comments. The last is open
#: ended ("> -55"), so a mean computed from these is a lower bound on the true power.
IPI_BIN_UPPER_DBM = (-92, -89, -86, -83, -80, -75, -70, -65, -60, -55, -50)
#: mt76 mt7915/mt7915.h enum mt7915_rdd_cmd.
RDD_STOP, RDD_START = 0, 1
TIMEOUT_MS = 3000


def ipi_request(
    idx: int,
    band: int = 0,
    set_val: int = 0,
    thres: int = 0,
    max_cnt: int = 0,
    duration: int = 0,
    cmd_type: int = 0,
) -> bytes:
    """EXT_CMD_RDD_IPI_HIST_T, 20 bytes."""
    return struct.pack("<BBBBiIII", idx, band, set_val, 0, thres, max_cnt, duration, cmd_type)


def rdd_request(ctrl: int, idx: int = 0, rx_sel: int = 0, val: int = 0) -> bytes:
    """EXT_CMD_RDD_ON_OFF_CTRL_T, 8 bytes; identical to mt76_connac_mcu_rdd_cmd's struct."""
    return struct.pack("<BBBB4x", ctrl, idx, rx_sel, val)


def parse_histogram(body: bytes) -> dict | None:
    """The 12 counters and the TX-assert time, if this reply is the documented event."""
    if len(body) < IPI_REPLY_LEN:
        return None
    values = struct.unpack_from(f"<{IPI_BIN_COUNT}I", body, IPI_VALUES_AT)
    return {
        "echoed_idx": body[0],
        "band_idx": body[1],
        "bins": list(values[:11]),
        "free_run": values[11],
        "tx_assert_us": struct.unpack_from("<I", body, IPI_VALUES_AT + 4 * IPI_BIN_COUNT)[0],
    }


def mean_power_dbm(bins: list[int]) -> float | None:
    """Count-weighted mean of the bin upper bounds. A lower bound on the true mean power."""
    total = sum(bins)
    if not total:
        return None
    return round(sum(c * p for c, p in zip(bins, IPI_BIN_UPPER_DBM, strict=True)) / total, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--band", default="5GHz", choices=sorted(m.CHAN_BAND))
    parser.add_argument("--channel", type=int, default=36)
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument(
        "--rdd",
        action="store_true",
        help="also try starting the radar detector first; IPI sits under RDD",
    )
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        parser.error("--seconds must be between 1 and 60")

    dev = m.open_device()
    patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
    out: dict = {
        "tool": "ipi_hist_cmd",
        "mt76_usb_macos": m.__version__,
        "channel": f"{args.band}:{args.channel}",
        "steps": [],
        "reads": [],
    }

    def send(label: str, cid: int, payload: bytes, query: bool = False) -> bytes | None:
        cmd = m.MCU_EXT_CMD(cid) | (m.MCU_CMD_FIELD_QUERY if query else 0)
        try:
            body = dev.reply_body(dev.mcu_cmd_word(cmd, payload, timeout=TIMEOUT_MS))
        except (m.McuError, RuntimeError, usb.core.USBError) as exc:
            out["steps"].append({"step": label, "state": "silent", "detail": str(exc)[:60]})
            return None
        state = "refused" if mcs.is_refusal(body, cid) else "accepted"
        out["steps"].append({"step": label, "state": state, "reply_bytes": len(body)})
        return None if state == "refused" else body

    with dev:
        dev.bringup(patch, ram, log=lambda *a: None)
        dev.set_monitor_mode()
        dev.set_sniffer(True)
        dev.tune(args.band, args.channel, args.channel, 20)
        time.sleep(0.5)

        if args.rdd:
            send("RDD_START", EXT_CMD_RDD_ON_OFF_CTRL, rdd_request(RDD_START))
        send("IPI CR_INIT", EXT_CMD_RDD_IPI_HIST_CTRL, ipi_request(IPI_SET_CR_INIT, set_val=1))
        send(
            "IPI SET_IDLE_PWR",
            EXT_CMD_RDD_IPI_HIST_CTRL,
            ipi_request(IPI_SET_IDLE_PWR, set_val=1, thres=-92, max_cnt=0xFFFF, duration=100000),
        )
        send(
            "IPI HIST_RESET", EXT_CMD_RDD_IPI_HIST_CTRL, ipi_request(IPI_SET_HIST_RESET, set_val=1)
        )
        time.sleep(args.seconds)

        # The QUERY bit is what makes the histogram come back on the command itself.
        for idx, name in (
            (IPI_GET_ALL, "ALL"),
            (IPI_GET_0_TO_10, "0_TO_10"),
            (IPI_GET_FREE_RUN, "FREE_RUN"),
        ):
            body = send(f"IPI GET {name}", EXT_CMD_RDD_IPI_HIST_CTRL, ipi_request(idx), query=True)
            hist = parse_histogram(body) if body else None
            if hist:
                hist["get"] = name
                hist["mean_power_dbm"] = mean_power_dbm(hist["bins"])
                out["reads"].append(hist)
        if args.rdd:
            send("RDD_STOP", EXT_CMD_RDD_ON_OFF_CTRL, rdd_request(RDD_STOP))

    print(json.dumps(out, indent=2))
    sampling = any(sum(r["bins"]) or r["free_run"] for r in out["reads"])
    if not sampling:
        print(
            "\nThe sampler is still idle: every bin and the free-running counter read zero. "
            "That is the open question, not a failure of this run.",
            file=sys.stderr,
        )
    return 0 if sampling else 2


if __name__ == "__main__":
    sys.exit(main())
