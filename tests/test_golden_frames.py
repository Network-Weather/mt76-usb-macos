# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""The MT7921 on-wire MCU frames must not change while the driver grows chip seams.

golden_mt7921_frames.json holds every USB bulk-OUT frame (endpoint, hex) that each
command produced on the implementation validated on hardware. This test replays the
same commands and compares byte for byte. If a case differs, either the MT7921 wire
format was changed deliberately (then regenerate the fixture and say so in the
commit) or a refactor broke it.
"""

import json
import struct
from pathlib import Path

import pytest

import mt7921u as m

GOLDEN = Path(__file__).with_name("golden_mt7921_frames.json")


class RecordingDevice(m.Mt7921uDevice):
    """Captures bulk-OUT frames; answers every command with a plausible reply."""

    def __init__(self):
        super().__init__()
        self.frames: list[tuple[int, str]] = []

    def bulk_out(self, ep, data, timeout=1000):
        self.frames.append((ep, bytes(data).hex()))
        return len(data)

    def mcu_wait(self, seq, cid, timeout=3000):
        reply = bytearray(self.MCU_RXD_LEN + 64)
        struct.pack_into("<I", reply, 0, m.PKT_TYPE_RX_EVENT << 27)
        reply[self.RXD_SEQ_OFFSET] = seq
        reply[self.RXD_STATUS_OFFSET] = m.PATCH_NOT_DL_SEM_SUCCESS
        return bytes(reply)


def cases(dev: RecordingDevice) -> dict:
    probe = m.build_probe_request(bytes.fromhex("02aabbccddee"), b"x", 7)
    return {
        "patch_sem_get": lambda: dev.patch_sem_ctrl(True),
        "patch_sem_release": lambda: dev.patch_sem_ctrl(False),
        "init_download_patch": lambda: dev.init_download(0x900000, 0x1000, 0x80000001),
        "init_download_ram": lambda: dev.init_download(0x200000, 0x2000, 0x80000000),
        "send_firmware": lambda: dev.send_firmware(bytes(range(256)) * 20),
        "start_patch": dev.start_patch,
        "start_firmware": lambda: dev.start_firmware(0, 1),
        "nic_power_ctrl": lambda: dev.nic_power_ctrl(1),
        "get_nic_capability": dev.get_nic_capability,
        "set_eeprom": dev.set_eeprom,
        "set_rxfilter_fif": lambda: dev.set_rxfilter(m.MONITOR_FILTER),
        "set_monitor_mode": dev.set_monitor_mode,
        "set_sniffer_on": lambda: dev.set_sniffer(True),
        "set_chan_info_6g_53_20": lambda: dev.set_chan_info(
            control_ch=53, center_ch=53, bw=m.CMD_CBW_20MHZ, band=2
        ),
        "set_chan_info_5g_36_80": lambda: dev.set_chan_info(
            control_ch=36, center_ch=42, bw=m.CMD_CBW_80MHZ, band=1
        ),
        "config_sniffer_6g_53_20": lambda: dev.config_sniffer(
            control_ch=53, center_ch=53, band_name="6GHz", bw=m.SNIFFER_BW_20
        ),
        "config_sniffer_5g_36_80": lambda: dev.config_sniffer(
            control_ch=36, center_ch=42, band_name="5GHz", bw=m.SNIFFER_BW_80
        ),
        "config_sniffer_5g_161_160": lambda: dev.config_sniffer(
            control_ch=161, center_ch=147, band_name="5GHz", bw=m.SNIFFER_BW_160
        ),
        "get_temperature": dev.get_temperature,
        "read_efuse": lambda: dev.read_efuse(0x0),
        "inject_probe": lambda: dev.inject(probe, m.EP_OUT_AC_BE, 7),
    }


def replay(name: str) -> list[list]:
    dev = RecordingDevice()
    dev.msg_seq = 0
    cases(dev)[name]()
    return [[ep, frame] for ep, frame in dev.frames]


GOLDEN_CASES = json.loads(GOLDEN.read_text())["cases"]


def test_every_command_has_a_golden_case():
    assert set(cases(RecordingDevice())) == set(GOLDEN_CASES)


@pytest.mark.parametrize("name", sorted(GOLDEN_CASES))
def test_mt7921_frames_match_golden(name):
    assert replay(name) == GOLDEN_CASES[name]
