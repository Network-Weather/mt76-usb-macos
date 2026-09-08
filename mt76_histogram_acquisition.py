# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Opt-in histogram control guard; execute methods through session.call.

One histogram owner per device; no retune, reset or out-of-band controls during
the guard lifetime. Caller routes events and bounds elapsed acquisition time.
Shared histories are destroyed. STOP/restoration cannot recover those histories.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

from mt76_histogram import (
    HistogramBins,
    build_histogram_request,
    parse_histogram_ack,
    parse_histogram_event,
    parse_legacy_histogram,
)

_CONTROL = 0x83082004
_RESET = 0x83088230
_OPTIONS = 0x83088234
_OLD_MASKS = {_CONTROL: 7, _RESET: 1 << 29, _OPTIONS: 0x30000}
_NEW_MASKS = {_CONTROL: 7, _RESET: 1 << 29, 0x83092004: 7, 0x83098230: 1 << 29}
_CHANNELS = {("2.4GHz", channel, channel, 20) for channel in (1, 6, 11)} | {("5GHz", 36, 36, 20)}


@dataclass(frozen=True)
class HistogramSample:
    bins: HistogramBins
    command_open_us: int
    command_closed_us: int
    read_open_us: int
    read_closed_us: int
    coverage_fraction: float | None = None
    sample_period_ns: int | None = None


class HistogramGuard:
    """begin -> bounded caller acquisition -> finish -> restore.

    MT7925 finish requires its complete asynchronous event, then verifies stopped
    controls and matching timer banks. There is no known timer-cancel command:
    restore refuses while pending. Stop the USB worker and reload firmware if a
    pending modern acquisition fails/times out. Legacy restore can stop its engine.
    Restore failures retain active for retry. needs_reload stays true after any
    activation; explicitly reload after the experiment, never under a live worker.
    """

    def __init__(self, dev):
        if dev.CHIP not in ("mt7921", "mt7925"):
            raise ValueError("unsupported histogram chip")
        self.dev = dev
        self.modern = dev.CHIP == "mt7925"
        self._masks = _NEW_MASKS if self.modern else _OLD_MASKS
        self.active = self.pending = self.ready = self.needs_reload = False
        self._saved = {}
        self.command_open_us = self.command_closed_us = 0

    def _read_control(self, address):
        word = self.dev.rr(address)
        if type(word) is not int or not 0 <= word < 0xFFFFFFFF:
            raise RuntimeError("invalid histogram control read")
        return word

    def _set(self, address, bits):
        mask = self._masks[address]
        word = self._read_control(address)
        self.dev.wr(address, word & ~mask | bits)
        if self._read_control(address) & mask != bits:
            raise RuntimeError("histogram control readback mismatch")

    def begin(self):
        if self.active:
            raise RuntimeError("histogram guard already active")
        channel = getattr(self.dev, "_capture_channel", None)
        if channel not in _CHANNELS:
            raise ValueError("histogram requires a qualified20MHz channel")
        if self.modern and self.dev.uni_option(0x36) != 7:
            raise ValueError("histogram requires SET_ACK option7")
        saved = {
            address: self._read_control(address) & mask for address, mask in self._masks.items()
        }
        if any(bits for address, bits in saved.items() if address != _OPTIONS):
            raise RuntimeError("histogram already enabled or reset asserted")
        self._saved, self._channel = saved, channel
        self.active = self.pending = self.needs_reload = True
        self.ready = False
        self.command_open_us = time.monotonic_ns() // 1000
        if self.modern:
            raw = self.dev.mcu_uni(0x36, build_histogram_request("mt7925"), timeout=1000)
            if parse_histogram_ack("mt7925", raw, self.dev.msg_seq):
                raise RuntimeError("histogram command rejected")
        else:
            self._set(_CONTROL, 0)
            for bits in (0, 1 << 29, 0):
                word = self._read_control(_RESET)
                self.dev.wr(_RESET, word & ~(1 << 29) | bits)
            if self._read_control(_RESET) & (1 << 29):
                raise RuntimeError("histogram reset remained asserted")
            if any(self.dev.rr(0x83088600 + 4 * i) for i in range(11)):
                raise RuntimeError("histogram did not reset")
            self._set(_OPTIONS, 0x30000)
            self._set(_CONTROL, 5)
        self.command_closed_us = time.monotonic_ns() // 1000
        self.ready = True

    def finish(self, raw_event=None):
        if not self.active or not self.pending or not self.ready:
            raise RuntimeError("no pending histogram acquisition")
        if getattr(self.dev, "_capture_channel", None) != self._channel:
            raise RuntimeError("histogram channel changed")
        if not self.modern and raw_event is not None:
            raise ValueError("legacy histogram does not use an event")
        if self.modern and raw_event is None:
            raise ValueError("modern histogram requires its completed event")
        report = parse_histogram_event("mt7925", raw_event) if self.modern else None
        opened = time.monotonic_ns() // 1000
        if self.modern:
            if any(self._read_control(a) & mask for a, mask in self._masks.items()):
                raise RuntimeError("histogram timer has not stopped")
            observed = tuple(
                tuple(self.dev.rr(base + 4 * i) for i in range(11))
                for base in (0x83001000, 0x83011000)
            )
            if observed != report.bins:
                raise RuntimeError("histogram event/bank mismatch")
        else:
            self._set(_CONTROL, 0)
            words = tuple(self.dev.rr(0x83088600 + 4 * i) for i in range(11))
            report = parse_legacy_histogram("mt7921", struct.pack("<11I", *words))
        self.pending = False
        self.ready = False
        return HistogramSample(
            report,
            self.command_open_us,
            self.command_closed_us,
            opened,
            time.monotonic_ns() // 1000,
        )

    def restore(self):
        if not self.active:
            return
        self.ready = False
        if self.modern and self.pending:
            raise RuntimeError("pending histogram timer requires firmware reload")
        errors = []
        # Stop legacy first; restore enable bits last. Attempt every saved mask.
        if not self.modern:
            try:
                self._set(_CONTROL, 0)
            except Exception as exc:
                errors.append(exc)
        order = [a for a in self._masks if a not in (_CONTROL, 0x83092004)]
        order += [a for a in self._masks if a in (_CONTROL, 0x83092004)]
        for address in order:
            try:
                self._set(address, self._saved[address])
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError("histogram restore failed") from errors[0]
        self.active = self.pending = False
