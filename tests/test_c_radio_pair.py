# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Supervisor tests use fake processes, never attached hardware."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import c_radio_pair as pair


@pytest.mark.parametrize("fail", [False, True])
def test_pair_records_success_or_timeout(monkeypatch, tmp_path, fail):
    processes = []

    class Process:
        def __init__(self, cmd, stdout):
            self.tx = "--transmit" in cmd
            self.returncode = None
            self.stopped = False
            processes.append(self)
            rows = [
                {"event": "ready"},
                {
                    "event": "dwell",
                    "submitted": 20 if self.tx else 0,
                    "synthetic_unique": 20,
                    "synthetic_rate_matches": 20,
                    "synthetic_exact": 20,
                },
                {"event": "cleanup", "alive_before_cleanup": True, "firmware_reloaded": True},
            ]
            for row in rows:
                stdout.write(json.dumps(row) + "\n")
            stdout.flush()

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            if self.tx and fail and not self.stopped:
                raise subprocess.TimeoutExpired("fake", timeout)
            self.returncode = 0

        def terminate(self):
            self.stopped = True

        def kill(self):
            pytest.fail("cooperative process should not need SIGKILL")

    monkeypatch.setattr(pair.subprocess, "Popen", Process)
    args = SimpleNamespace(transmitter=pair.IDS[1], fw=tmp_path, channel=36, rate="ofdm6", count=20)
    report = pair.run_pair(args, 0)
    assert report["pass"] == (not fail)
    assert report["error"] == ("TimeoutExpired" if fail else None)
    assert len(report["receiver"]) == len(report["transmitter"]) == 3
    assert len(processes) == 2
    if fail:
        assert all(p.stopped for p in processes)
