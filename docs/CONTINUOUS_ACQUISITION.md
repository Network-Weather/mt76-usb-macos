# Continuous acquisition (R5)

Implementation branch: `feat/continuous-acquisition`, based on `main` at `055e881`.
This is an additive acquisition API, not a networking driver or a claim of lossless RF.

## Contract

- Explicit bring-up precedes every session. No adoption of retained firmware, automatic
  reset/recovery, or transparent continuation across USB loss. Stop before closing USB.
- One worker owns the device and serializes commands. The same dispatcher reads frames
  while awaiting MCU responses. Existing non-session APIs retain their behavior.
- Frame and event queues are separately bounded, drop newest on overflow, and report
  received/delivered/dropped counts, depths and high-water marks. Full consumer queues
  never block the MCU response path. Raw queued data is sensitive and stays in memory.
  Legacy MCU/MIB drop fields retain their narrow command-reader meaning; use the
  session's frame/event drop counters for consumer-queue overflow.
- Command deadlines include queueing and I/O. A missing reply, short write, or transport
  failure invalidates the session, even if a callback catches the exception. Do not reuse
  the four-bit sequence after an ambiguous timeout; do a fresh bring-up instead.
- Match only the current command. Idle/unmatched replies are observable events, never
  candidates for future matching. Command-specific payload checks remain with the existing
  command helpers: event IDs are not generally command IDs. This does not prove immunity
  to arbitrary duplicate firmware replies after a previously successful command.
- Packets carry host receive time, a session epoch, a channel-command generation and an
  in-command transition flag. Decode actual band/channel from the descriptor. Generation
  identifies host control state, **not** proof that buffered data came from the new channel.
  A command acknowledgment does not prove that the radio was listening throughout retune.
- Raw 32-bit device timestamps remain raw. Their ~72-minute wrap must not be mistaken for
  a reset or stretched into ranging. No cross-reset or cross-radio clock fit is implied.
- Worker callbacks are short driver operations only. Arbitrary callbacks can block or
  sleep; neither implementation can promise to forcibly cancel arbitrary application code.
  A stop timeout leaves ownership attached: the caller must not free or close the device.

## Python checkpoint

`mt76_session.AcquisitionSession` owns an already booted device. Firmware loading, monitor
configuration and the initial tune still use the existing APIs before session start.

```python
from mt76_session import AcquisitionSession

# dev has been opened, booted, and configured for passive capture.
with AcquisitionSession(dev, frame_capacity=256, event_capacity=64) as session:
    session.tune("5GHz", 36)
    packet = session.read(timeout=1)
    if packet is not None:
        decoded = decoder(packet.raw)  # use decoder_for(dev), outside the USB worker
    # Other short operations: session.call(lambda d: existing_query(d), timeout=3)
    counters = session.snapshot()  # redacted; no frame bytes or exception payloads
# Close dev only after the worker has stopped.
```

The command queue defaults to 16 entries; a full queue raises `queue.Full` without sending
anything. A command or shutdown failure is not silently retried. After stopping, buffered
packets may still be drained with `read()`. Call `snapshot()` to distinguish a quiet timeout
from a stopped/failed session. Raw replies and callback results are not inherently redacted.

Initial offline checkpoint: 576 tests pass (22 new session tests), including both chip
profiles, wrap over 32 commands, concurrent callers, frame/event overflow, malformed DMA
records, stale replies, transport failure, short writes, ownership guards and stop races.
These are replay tests, not hardware qualification.

## Remaining acceptance work

- Python and C have passed short hardware runs with MIB queries and retunes;
  C also passed five-minute stress runs. Both passed cancellation and clean reinitialization.
  See [dated acceptance evidence](TESTING.md#continuous-acquisition-sessions-2026-09-04).
- Multi-hour passive soak and leak evidence remain outstanding.
- Keep hot-unplug and warm adoption explicitly unqualified until exercised.

## Native C checkpoint

`c/mt76_session.h` exposes an opaque worker-owned session. `mt_session_start` consumes
the successful bring-up marker; `mt_session_call` executes a driver callback, and
`mt_session_read` returns copied packets rather than pointers into worker buffers.
Pass `retune=true` for a channel-changing callback. Snapshot channel geometry is requested,
acknowledged host state, not proof of every buffered frame's RF channel.

C has one command slot (`MT_SESSION_BUSY` on concurrent submission); Python has a bounded
command queue. Their packet routing, drop-newest policy and failure semantics are shared.
C queue capacities are 1..4096 records; Python accepts 1..65536. Each record is at most
16 KiB. Size queues for memory budgets rather than using the largest accepted setting.

Native call retains callback/context lifetime until the worker returns, even after a
deadline expires. This prevents use-after-return of caller-owned memory. Arbitrary blocking
C callbacks therefore cannot have a guaranteed return deadline. After successful stop,
drain remaining packets, then destroy the session and close the device. Serialize lifecycle
calls and ensure all API callers have returned before destroying the session.

Latest offline checkpoint: 613 pytest tests, native tests, ASan/UBSan and a separate native
ThreadSanitizer replay run pass. Shared routing fixtures cover all 32 packet types,
flag variants, descriptor boundaries, and 2,000 deterministic malformed records.
Native replay covers overflow, stale replies, 32-command sequence wrap, timeouts,
swallowed errors, write failure, too-small reply buffers and stop/callback races.

## Passive qualification commands

Both probes print redacted NDJSON and have no transmit path. The current hardware
envelope is 5 GHz control channels 36/149 at 20 MHz, one process per reference adapter.
Set `--hop-seconds 0` for a locked-channel run, or `--mib-seconds 0` for capture alone.
`--seconds` accepts up to four hours. Never run two processes against the same dongle.

```sh
python scripts/session_probe.py --usb-id 0e8d:7961 --fw /path/to/firmware --seconds 60
make -C c mt76_session_probe
c/mt76_session_probe --usb-id 0846:9072 --fw /path/to/firmware --seconds 60
```

Quiet receive timeouts are not USB errors. Counters distinguish software overflow,
malformed input and undecoded frames. Off-requested-channel observations are retained
and counted, not automatically treated as decoding faults. Delivery latency includes
consumer scheduling/command waits; it is not over-the-air latency. Heartbeats do not perform
the final register-health check (native `register_alive_after` is null until the summary).

`scripts/session_lifecycle.py --implementation c|python --usb-id VID:PID --fw DIR`
tests SIGTERM on its own child followed by fresh bring-up. Stopping the worker stops host
acquisition; it does not promise firmware power-down or preservation of device FIFO contents.
