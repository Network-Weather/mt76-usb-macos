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

- Native C dispatcher/session and shared replay parity.
- Both radios: sustained capture with MIB reads, repeated retunes and explicit accounting.
- Multi-hour passive soak, cancellation and clean reinitialization evidence.
- Keep hot-unplug and warm adoption explicitly unqualified until exercised.
