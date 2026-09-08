# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Offline composition checks, not live RF qualification."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import mt7921u as m
from mt76_measurements import CounterReading, CounterSample, counter_descriptors
from mt76_session import SessionError


@pytest.fixture
def example(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "examples" / "measurements.py"
    spec = importlib.util.spec_from_file_location("measurement_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock = iter(i / 10 for i in range(1000))
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    return module


class Session:
    def __init__(self, chip, change=False, fail=False, quiet=False):
        self.dev = SimpleNamespace(CHIP=chip)
        self.change, self.fail, self.quiet = change, fail, quiet
        self.called = False

    def read(self, *, timeout, events=False):
        return None if events or self.quiet else object()

    def snapshot(self):
        return {
            "state": "running",
            "epoch_ns": 1,
            "channel_generation": int(self.change and self.called),
            "requested_channel": ("2.4GHz", 6, 6, 20),
            "counts": {"frames_dropped": 3},
        }

    def call(self, callback):
        self.called = True
        if self.fail:
            raise SessionError("synthetic transport failure")
        return callback(self.dev)


@pytest.mark.parametrize("chip", [m.CHIP_MT7921, m.CHIP_MT7925])
def test_example_raw_intervals_and_visible_loss(example, monkeypatch, chip):
    def counters(dev, names):
        readings = tuple(
            CounterReading(d, 0) for d in counter_descriptors(dev.CHIP) if d.counter in names
        )
        return CounterSample(dev.CHIP, readings, 10, 20, 0)

    monkeypatch.setattr(example, "read_counters", counters)
    monkeypatch.setattr(
        example,
        "read_thermal",
        lambda _: SimpleNamespace(reported_temperature_c=38, opened_us=21, closed_us=30),
    )
    rows = []
    assert example.collect(Session(chip), 1, rows.append) > 0
    row = json.loads(rows[0])
    assert row["counter_closed_us"] < row["thermal_opened_us"]
    assert row["session"]["counts"]["frames_dropped"] == 3
    assert row["channel_busy_fraction"] is None
    assert all(r["raw"] == 0 and r["tick_ns"] is None for r in row["counters"])
    assert {r["name"] for r in row["counters"]} == {"rx_mpdu", "primary_cca"}


@pytest.mark.parametrize("seconds", [0, 61, True, 1.5])
def test_example_rejects_duration_before_session_use(example, seconds):
    with pytest.raises(ValueError, match=r"integer in 1\.\.60"):
        example.collect(None, seconds)


def test_example_transport_failure_emits_no_sample(example):
    rows = []
    with pytest.raises(SessionError):
        example.collect(Session(m.CHIP_MT7925, fail=True), 1, rows.append)
    assert rows == []


@pytest.fixture(scope="module")
def native_example(tmp_path_factory):
    compiler = shutil.which("clang")
    if sys.platform != "darwin" or compiler is None:
        pytest.skip("native macOS headers and compiler required")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path_factory.mktemp("measurement-example") / "example"
    subprocess.run(  # noqa: S603 — fixed local synthetic test harness
        [
            compiler,
            "-Wall",
            "-Wextra",
            "-Werror",
            "-std=c11",
            "-I" + str(root / "c"),
            str(root / "tests" / "c_measurement_example.c"),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
    )
    return binary


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
def test_native_example(native_example, mode):
    result = subprocess.run(  # noqa: S603 — built local synthetic test harness
        [str(native_example), str(mode)], check=True, capture_output=True, text=True
    )
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    if mode in (1, 2):
        assert rows == []
    else:
        assert rows
        row = rows[0]
        assert row["frames_dropped"] == 3
        assert row["channel_busy_fraction"] is None
        assert row["counter_closed_us"] < row["thermal_opened_us"]
        assert all(r["raw"] == 0 and r["tick_ns"] is None for r in row["counters"])
        assert bool(row["frames_consumed"]) == (mode == 0)


def test_example_context_change_emits_no_sample(example, monkeypatch):
    monkeypatch.setattr(example, "read_counters", lambda *_: None)
    monkeypatch.setattr(example, "read_thermal", lambda *_: None)
    rows = []
    with pytest.raises(SessionError):
        example.collect(Session(m.CHIP_MT7925, change=True), 1, rows.append)
    assert rows == []
