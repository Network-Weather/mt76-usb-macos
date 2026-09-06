# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Same register/command boundary and fault stages through Python and native C."""

import ctypes as ct
import struct
import sys

import pytest

from mt76_histogram_acquisition import HistogramGuard
from tests.test_c_parity import HistogramBins
from tests.test_c_parity import native as native
from tests.test_csi_measurements import event
from tests.test_histogram import histogram_event

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native IOKit C build")
READ = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.c_uint32, ct.POINTER(ct.c_uint32))
WRITE = ct.CFUNCTYPE(ct.c_int, ct.c_void_p, ct.c_uint32, ct.c_uint32)
ACTIVATE = ct.CFUNCTYPE(ct.c_int, ct.c_void_p)


class RegIO(ct.Structure):
    _fields_ = [("ctx", ct.c_void_p), ("read", READ), ("write", WRITE), ("pause", ct.c_void_p)]


class HistIO(ct.Structure):
    _fields_ = [("registers", RegIO), ("command_ctx", ct.c_void_p), ("activate", ACTIVATE)]


class Guard(ct.Structure):
    _fields_ = [
        ("io", HistIO),
        ("dev", ct.c_void_p),
        ("chip", ct.c_int),
        ("saved", ct.c_uint32 * 4),
        ("channel_key", ct.c_uint32),
        ("command_open_us", ct.c_uint64),
        ("command_closed_us", ct.c_uint64),
        ("active", ct.c_bool),
        ("pending", ct.c_bool),
        ("ready", ct.c_bool),
        ("needs_reload", ct.c_bool),
    ]


class Sample(ct.Structure):
    _fields_ = [
        ("bins", HistogramBins),
        ("command_open_us", ct.c_uint64),
        ("command_closed_us", ct.c_uint64),
        ("read_open_us", ct.c_uint64),
        ("read_closed_us", ct.c_uint64),
        ("coverage_known", ct.c_bool),
        ("coverage_fraction", ct.c_double),
        ("sample_period_ns", ct.c_uint),
    ]


class Device:
    def __init__(self, modern, fail_at=0):
        self.CHIP = "mt7925" if modern else "mt7921"
        self._capture_channel = ("2.4GHz", 6, 6, 20)
        self.msg_seq = 9
        self.modern, self.fail_at = modern, fail_at
        self.operations = []
        self.regs = dict.fromkeys(
            (0x83082004, 0x83088230, 0x83088234, 0x83092004, 0x83098230), 0x40000000
        )
        self.regs[0x83088234] |= 0x10000

    def note(self, *operation):
        self.operations.append(operation)
        if len(self.operations) == self.fail_at:
            raise RuntimeError("injected transport failure")

    def rr(self, address):
        self.note("read", address)
        return self.regs.get(address, 0)

    def wr(self, address, value):
        # Failure can be reported even after a write reached hardware.
        self.regs[address] = value
        if address == 0x83088230 and value & (1 << 29):
            for i in range(11):
                self.regs[0x83088600 + 4 * i] = 0
        self.note("write", address, value)

    def uni_option(self, _cid):
        return 7

    def mcu_uni(self, cid, request, **_kwargs):
        assert cid == 0x36
        assert request == bytes.fromhex("0000000002000400")
        self.regs[0x83082004] |= 5
        self.regs[0x83092004] |= 5
        self.note("activate")
        return event(struct.pack("<II", 0x36, 0), eid=1, sequence=9)

    def complete(self):
        if self.modern:
            self.regs[0x83082004] &= ~7
            self.regs[0x83092004] &= ~7
        for view, base in enumerate((0x83001000, 0x83011000) if self.modern else (0x83088600,)):
            for i in range(11):
                self.regs[base + 4 * i] = view * 11 + i
        return histogram_event(list(range(22))) if self.modern else None


class Adapter:
    def __init__(self, native, modern, use_c, fail_at=0):
        self.dev = Device(modern, fail_at)
        self.use_c, self.modern = use_c, modern
        self.sample = None
        if not use_c:
            self.guard = HistogramGuard(self.dev)
            return
        self.lib = native
        self.guard = Guard()

        @READ
        def read(_ctx, address, out):
            try:
                out[0] = self.dev.rr(address)
                return 0
            except RuntimeError:
                return -1

        @WRITE
        def write(_ctx, address, value):
            try:
                self.dev.wr(address, value)
                return 0
            except RuntimeError:
                return -1

        @ACTIVATE
        def activate(_ctx):
            try:
                self.dev.mcu_uni(0x36, bytes.fromhex("0000000002000400"))
                return 0
            except RuntimeError:
                return -1

        self.callbacks = read, write, activate
        self.io = HistIO(RegIO(None, read, write, None), None, activate)
        native.mt_histogram_begin.argtypes = [ct.POINTER(Guard), ct.c_int, HistIO]
        native.mt_histogram_finish.argtypes = [
            ct.POINTER(Guard),
            ct.c_void_p,
            ct.c_size_t,
            ct.POINTER(Sample),
        ]
        native.mt_histogram_restore.argtypes = [ct.POINTER(Guard)]

    def begin(self):
        if self.use_c:
            return self.lib.mt_histogram_begin(ct.byref(self.guard), int(self.modern), self.io)
        try:
            self.guard.begin()
            return 0
        except (RuntimeError, ValueError):
            return -1

    def finish(self, raw):
        if self.use_c:
            out = Sample()
            ct.memset(ct.byref(out), 0xA5, ct.sizeof(out))
            before = bytes(out)
            rc = self.lib.mt_histogram_finish(
                ct.byref(self.guard), raw, len(raw) if raw else 0, ct.byref(out)
            )
            if rc:
                assert bytes(out) == before
            else:
                self.sample = out
            return rc
        try:
            self.sample = self.guard.finish(raw)
            return 0
        except (RuntimeError, ValueError):
            return -1

    def restore(self):
        if self.use_c:
            return self.lib.mt_histogram_restore(ct.byref(self.guard))
        try:
            self.guard.restore()
            return 0
        except RuntimeError:
            return -1


@pytest.mark.parametrize("modern", [False, True])
def test_histogram_guard_success_and_exact_io_parity(native, modern):
    adapters = [Adapter(native, modern, c) for c in (False, True)]
    for a in adapters:
        original = a.dev.regs.copy()
        assert a.begin() == 0
        assert (a.guard.active, a.guard.pending, a.guard.ready, a.guard.needs_reload) == (
            True,
            True,
            True,
            True,
        )
        assert a.begin() == -1
        assert a.finish(a.dev.complete()) == 0
        assert (a.guard.pending, a.guard.ready) == (False, False)
        assert a.finish(None) == -1
        sample = a.sample
        assert (
            sample.command_open_us
            <= sample.command_closed_us
            <= sample.read_open_us
            <= sample.read_closed_us
        )
        if a.use_c:
            assert not sample.coverage_known
            assert sample.sample_period_ns == 0
        else:
            assert sample.coverage_fraction is sample.sample_period_ns is None
        # Unrelated bits changed since begin must survive masked restoration.
        a.dev.regs[0x83082004] |= 0x100
        assert a.restore() == 0
        assert (a.guard.active, a.guard.needs_reload) == (False, True)
        assert a.restore() == 0
        for address, value in original.items():
            assert a.dev.regs[address] == value | (0x100 if address == 0x83082004 else 0)
        assert a.begin() == 0
        assert a.finish(a.dev.complete()) == 0
        assert a.restore() == 0
    assert adapters[0].dev.operations == adapters[1].dev.operations


@pytest.mark.parametrize("modern", [False, True])
def test_every_begin_transport_failure_preserves_cleanup_state(native, modern):
    baseline = Adapter(native, modern, False)
    assert baseline.begin() == 0
    for stage in range(1, len(baseline.dev.operations) + 1):
        for use_c in (False, True):
            a = Adapter(native, modern, use_c, stage)
            assert a.begin() == -1
            assert not a.guard.ready
            assert a.finish(a.dev.complete()) == -1
            assert len(a.dev.operations) == stage
            a.dev.fail_at = 0
            if a.guard.active:
                assert (a.guard.needs_reload, a.guard.pending) == (True, True)
                before = len(a.dev.operations)
                assert a.restore() == (-1 if modern else 0)
                if modern:
                    assert len(a.dev.operations) == before
            else:
                assert not a.guard.needs_reload
                assert a.restore() == 0


@pytest.mark.parametrize("modern", [False, True])
def test_every_finish_and_restore_transport_failure(native, modern):
    baseline = Adapter(native, modern, False)
    assert baseline.begin() == 0
    raw = baseline.dev.complete()
    before = len(baseline.dev.operations)
    assert baseline.finish(raw) == 0
    finish_ops = len(baseline.dev.operations) - before
    before = len(baseline.dev.operations)
    assert baseline.restore() == 0
    restore_ops = len(baseline.dev.operations) - before
    for finishing, total in ((True, finish_ops), (False, restore_ops)):
        for stage in range(1, total + 1):
            for use_c in (False, True):
                a = Adapter(native, modern, use_c)
                assert a.begin() == 0
                raw = a.dev.complete()
                if not finishing:
                    assert a.finish(raw) == 0
                a.dev.fail_at = len(a.dev.operations) + stage
                assert (a.finish(raw) if finishing else a.restore()) == -1
                assert (a.guard.active, a.guard.needs_reload) == (True, True)
                a.dev.fail_at = 0
                if not (modern and finishing):
                    assert a.restore() == 0


def test_modern_pending_missing_mismatched_event_refuses_without_unsafe_restore(native):
    for use_c in (False, True):
        a = Adapter(native, True, use_c)
        assert a.begin() == 0
        assert a.finish(None) == -1
        assert a.finish(histogram_event(list(range(22)))) == -1  # Still enabled.
        raw = a.dev.complete()
        assert a.finish(histogram_event()) == -1  # Different bank contents.
        assert a.guard.pending
        assert a.finish(raw) == 0
        assert a.restore() == 0
        assert a.begin() == 0
        before = len(a.dev.operations)
        assert a.restore() == -1
        assert len(a.dev.operations) == before
        assert (a.guard.ready, a.guard.active, a.guard.pending) == (False, True, True)


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize(
    ("address", "bits"), [(0x83082004, 5), (0x83088230, 1 << 29), (0x83082004, 0xFFFFFFFF)]
)
def test_preexisting_or_invalid_controls_never_write(native, modern, address, bits):
    for use_c in (False, True):
        a = Adapter(native, modern, use_c)
        a.dev.regs[address] |= bits
        assert a.begin() == -1
        assert (a.guard.active, a.guard.needs_reload) == (False, False)
        assert all(operation[0] == "read" for operation in a.dev.operations)


@pytest.mark.parametrize(
    "channel", [None, ("5GHz", 36, 42, 80), ("6GHz", 1, 1, 20), ("5GHz", 149, 149, 20)]
)
def test_python_guard_refuses_unqualified_channel_without_io(channel):
    dev = Device(True)
    dev._capture_channel = channel
    guard = HistogramGuard(dev)
    with pytest.raises(ValueError, match="channel"):
        guard.begin()
    assert not dev.operations
