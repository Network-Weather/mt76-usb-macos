# Capture-plus-measurement examples

These are small composition examples, not additional installed APIs or a new
qualification harness. They consume normal classified RX packets while querying
named RX MPDU / primary CCA counters and reported temperature once per second.
The commands run inside the existing session worker; no second USB reader exists.
Counters and temperature have separate host observation intervals, not a common
hardware latch. Unknown CCA tick conversion stays null; no busy percentage is
invented. A valid raw zero remains zero. Output is aggregate NDJSON without frame
bytes, SSIDs, MAC addresses or CSI coefficients.

## Python

Install the package into an environment, then run
[examples/measurements.py](../examples/measurements.py) from anywhere:

```sh
MT76_FW_DIR=/absolute/path/to/firmware python /absolute/path/to/examples/measurements.py --usb-id 0846:9072 --seconds 10
```

The script imports installed modules without adjusting `sys.path` and checks the
pinned firmware hashes. It explicitly starts passive channel6/20MHz capture. Its
inner session context stops the worker before the outer device context closes
USB; device close refuses if a failed stop still owns USB. Exceptions propagate,
not successful zero-valued samples. Return2 means no classified RX packets arrived,
which is inconclusive, not a healthy receiver result. Ctrl-C unwinds the contexts.

The reusable `collect(session, seconds, emit)` body also accepts a caller-owned
running session. Its snapshot includes epoch, requested channel/generation, queue
depth/loss and command diagnostics. The caller must serialize retunes and other
consumers; the before/after context check is a guard, not an arbitrary concurrency
contract. Classified RX counts do not establish good-FCS decoding.

## Native C

[examples/measurements.c](../examples/measurements.c) exposes a small application
function `example_measurements(session, seconds, output)`. It deliberately accepts
an already running session rather than duplicating firmware loading, device
selection and shutdown code. Its caller uses the normal pinned-firmware bring-up,
monitor/sniffer, tune and `mt_session_start` sequence, and must emit its selected
chip/firmware/channel profile alongside these records. Link against the same
driver objects/frameworks as `c/mt76_session_probe`; a standalone compile check is:

```sh
clang -Wall -Wextra -Werror -std=c11 -Ic -c examples/measurements.c -o /tmp/mt76-measurements-example.o
```

The function returns0 with RX,2 for a completed RF-silent window, or-1 on error.
It does not close or destroy caller-owned objects. After every return, stop the
session, then destroy it, then close the device. A failed stop retains ownership:
do not close/free the device, callback context or session; retry orderly stop.
Native output carries the same raw selected values and interval semantics as
Python, with explicit frame/event drops and USB errors. Their JSON envelopes are
example-specific, not a promised cross-language export schema.

## Checks and limits

[Shared example tests](../tests/test_measurement_examples.py) exercise valid
raw zeros, unknown conversion, visible queue loss, invalid duration, command
failure and changed configuration. The native synthetic harness links no USB
transport and writes only temporary test artifacts. These checks are not live RF
qualification. The established session probes supply the live acceptance harness;
the [release scope](MEASUREMENT_RELEASE_SCOPE.md) records the current old-radio
RF silence and unfinished long-session gates.
