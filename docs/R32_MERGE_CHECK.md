# R32 bounded merge check, 2026-09-08

**Verdict: hold PR #32, do not merge or release the complete slice yet.** The
user authorized a merge if the bounded acceptance checks passed. They did not:
the recovered ALFA lost most5/6GHz reception during the experimental sequence,
despite successful control restoration and firmware reload. No implementation
change, version bump, tag or release was made in this check.

[Structured, redacted evidence](../research/evidence/r32-bounded-merge-check-2026-09-08.json)
records source `ec8480e`, pinned firmware hashes, commands, phase counts, queue
statistics, cleanup and both positive and negative controls. Host: Apple M4 Max,
macOS26.6.1, Python3.14.7/PyUSB1.3.1. Both radios stayed attached; no additional
physical power cycle after the user's earlier recovery. One owner per radio,
different radios tested concurrently; no transmit operations or long soaks.

## Checks that passed

- Fresh current native rebuild, all2,027 Python tests, native tests and ASan/UBSan
  pass. The four CI jobs also pass at the tested source. TSan was not rerun here;
  earlier lifetime/race evidence remains separate.
- Initial Python and native passive5s dwells on channels1/36/53,20MHz, receive
  on all three bands on both radios with zero USB errors/timeouts. ALFA totals:
  Python1,645 / C1,960 frames. A9000: Python1,310 / C2,049 frames. This closes the
  earlier current-build A9000 bring-up check and establishes an initially healthy
  ALFA, not sustained recovery.
- Eight private pcaps (six Python3s single-band captures plus two native combined
  captures) contain5,651 packets. Wireshark4.6.4 capinfos/tshark agrees with writer
  counts and requested frequencies: strict timestamp order, radiotap encapsulation,
  no captured/original-length mismatch, malformed packet or error-severity expert
  result. No captures, addresses, SSIDs or raw CSI arrays are committed.
- ALFA Group5 baseline/enabled/restored counts are197/160/154 in Python and
  163/161/146 in C. All enabled-phase frames contain Group5; saved-bit restore
  succeeds, followed by healthy three-band reception. Python sees one buffered
  Group5 frame after restore; C records four restored-phase read timeouts. This
  positive result does not erase earlier near-silence or qualify dependable
  Group5 streaming, calibration or physical receiver labels.
- A9000 Python/C histogram checks on6/36 each complete three windows, stopped-bank
  agreement/restoration and reload. Python/C CSI checks accept39 selected-source
  reports each over two restarts, with normal capture/counter/thermal coexistence
  and no reports in stopped windows. All six fresh three-band post-checks pass
  with zero USB errors/timeouts. No new long-duration or combined CSI/histogram
  qualification is claimed.

## Blocking evidence: ALFA reception degrades during the histogram sequence

Each row is a **fresh Python bring-up and3s dwell per band after** the named
experiment. Counts are decoded frames, not a throughput comparison. Histogram
probes already perform their own final firmware reload before this new process.

| After experiment | ch1 /2.4GHz | ch36 /5GHz | ch53 /6GHz | USB read timeouts |
| --- | ---: | ---: | ---: | ---: |
| Python Group5 |311|72|478|0|
| Native Group5 |299|60|358|0|
| Python histogram6 |247|3|325|10|
| Python histogram36 |458|7|265|12|
| Native histogram6 |247|2|1|22|
| Native histogram36 |498|0|0|24|

The first degraded5GHz post-check has only three control frames and no
management frames; the next has seven control frames. A CLI exit0 for “at least
one frame on each band” is not persuasive RF-health acceptance in this sequence.
The final post-check exits2/inconclusive. All these checks have zero USB errors;
responsive transport is not evidence of working RF reception.

The final native histogram36 **baseline is already silent before activation**,
then its three windows remain silent and bin0-only. Its restoration, stable-bank
and register-aliveness checks still pass, exit0. That cannot qualify cleanup's
RF outcome or establish that this last activation caused the failure.

A final pair of overlapping passive5s/channel controls confirms the discrepancy:
ALFA410/0/2 frames with38 timeouts, versus A9000539/369/834 with no timeouts. The
reference observes management traffic on both high bands while ALFA observes none.
This supports a device-specific reception problem rather than merely quiet air;
different adapters are not a calibrated equal-sensitivity reference.

The ALFA Python histogram6 samples initially populate multiple bins, unlike the
previous bin0-only runs. Thus “old hardware only produces bin0” is not established.
Do not treat any histogram distribution as calibrated noise or proof of RF health.

## Review disposition and next discriminating work

Focused review of session ownership/deadline/shutdown paths, low-level ownership
hooks, CSI parser/lifetime and histogram bounds/restoration found no independent
must-fix code defect. C callback context survives worker completion; stop failure
retains device ownership; parsers check lengths before access; experimental guards
retain explicit reload requirements. This is a focused merge-risk review, not a
new exhaustive audit of every historical research file. Normal probe shutdown can
discard a few counted queued frames; the evidence does not call it lossless.

The **RF post-cleanup gate blocks the complete PR**: losing baseline reception
after opt-in measurement use has material impact even if the exact offending
operation is unknown. The temporal association begins after the first legacy
histogram experiment; it does not distinguish control writes, diagnostic reads,
repeated bring-up, channel switching or a prior interaction. Both Python and C
occur in the sequence; this is not proof of a C-only implementation bug.

Next, use a physically recovered ALFA to compare matched sequences: passive
bring-up/retune only, session with counter/thermal queries, then a minimal legacy
histogram guard without extra research diagnostics. Check both high bands after
each step and stop at the first degradation; retain the independent A9000 control.
Do not repeat the whole experiment batch or infer recovery from register reads.
If the unsafe path can be isolated, fix and repeat the relevant bounded gate.
Alternatively obtain an explicit decision to split/defer legacy histogram
acquisition and qualify the remaining slice; documentation alone does not close
this failed gate. No further physical cycle has been requested in this check.

The remaining two-hour Python/A9000 and both ALFA session runs stay release gates,
not the reason for this merge hold. Expanded TX, hot-unplug/sleep-wake, automatic
recovery, calibration and broad CSI remain unqualified. All bounded test processes
have exited and released the radios; no automatic soak or release is scheduled.
