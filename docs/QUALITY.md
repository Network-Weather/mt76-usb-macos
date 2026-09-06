# Engineering quality

This project handles untrusted binary data, controls external RF hardware, and can produce
sensitive captures. Passing a linter is necessary but is not the quality bar by itself. This
page separates checks enforced today from work that remains.

## Enforced today

| Area | Current check |
|---|---|
| Python formatting | `ruff format --check .` in macOS CI |
| Python linting | Ruff `E`, `F`, `W`, import sorting, upgrades, bugbear, comprehensions, executable-bit, refurb, security, simplify, pie, pytest, and Ruff-specific rules |
| Shell syntax | `bash -n setup.sh` in CI; `shellcheck setup.sh` in the local release check when ShellCheck is installed |
| Offline behavior | 2,008 pytest cases on the R32 integration branch, including synthetic Python/C parity and injectable USB/register faults; no adapter or firmware required |
| Native robustness | Native unit/fault tests, ASan/UBSan malformed-input harnesses and separate session/CSI ThreadSanitizer replay checks |
| Distribution | PEP 517 wheel and source-distribution build on every CI matrix member; the local check reuses installed development backends rather than silently downloading them |
| Platform matrix | macOS runners only, at the oldest/newest declared Python versions |
| Hardware evidence | Dated, exact-device results kept separately in [TESTING.md](TESTING.md) |
| Firmware supply chain | Pinned linux-firmware revision and SHA-256 verification in `setup.sh` |

Run the same publication checks locally with:

```bash
./scripts/check.sh
```

CI cannot validate RF behavior. A green badge means the package, pure parsers, and tests pass
on macOS; it does not mean an adapter was present.

## Known engineering gaps

These are publication disclosures, not hidden backlog:

- **Static typing is not clean.** A diagnostic mypy run currently reports many errors. The
  main causes are runtime method attachment to `Mt7921uDevice`, an optional/untyped PyUSB
  handle, and heterogeneous dictionaries used as protocol results. Broad ignores would hide the
  design problem, so type checking is not yet advertised or made cosmetic. Roadmap R4 replaces
  these boundaries before adding a type-check gate.
- **Coverage has limits.** Shared synthetic wire fixtures, exhaustive profile truncations,
  structured malformed cases and seeded Python/native fuzz harnesses exist. There is still
  no coverage threshold, reviewed live golden USB corpus or broad property-based gate.
  None of those parser checks establishes calibration or sensor freshness.
- **Physical negative paths remain separate.** Injectable USB/register boundaries now cover
  short writes, timeouts/disconnect failures, delayed/stale replies, queue overflow,
  cancellation and restoration faults. Physical hot-unplug and sleep/wake are unqualified;
  deterministic failure injection is not a substitute for exercising those conditions.
- **Observability is scoped.** Session snapshots and redacted probe NDJSON expose queues,
  drops, matched replies, errors, requested channel/generation and latency. Native soaks
  report current/peak memory; Python runs can be measured by the owned-process supervisor.
  There is no stable application-level logging schema or complete RF-loss accounting.
- **Long-run and RF acceptance remain open.** Two-hour acceptance is in progress on the
  A9000. The attached MT7921 became RF-silent in both legacy baseline drivers despite
  responsive MCU/reset controls; its current acceptance is blocked. See the
  [preserved negative evidence](TESTING.md#r32-current-mt7921-rf-failure-and-soak-status-2026-09-06).
  No automatic recovery, physical recovery or multi-hour pass is claimed yet.
- **Release automation is minimal.** There is a changelog, tag/version check, and dependency
  update bot, but no signed release procedure, code-coverage report, API reference site, or
  compatibility/deprecation policy yet. Publication remains a manual checklist in
  [PUBLISHING.md](PUBLISHING.md).
- **Documentation tooling is partial.** Local Markdown targets and JSON syntax are gated, but
  prose style, external links, spelling, example commands, CFF semantics, and GitHub-specific
  YAML semantics still rely on review or the hosting service.

## Quality expected of a Python networking/driver project

The following expectations guide the roadmap and reviews.

### Binary and protocol correctness

- Every length, offset, alignment, bit field, byte order, and reserved value is validated before
  access, with malformed and truncated fixtures for every parser.
- Parsed results have explicit types and units. Unknown hardware values remain unknown; they are
  not silently turned into zero or plausible-looking measurements.
- MCU sequence matching, retries, stale replies, and unsolicited events have defined behavior.
- Protocol structures cite the exact upstream mt76 revision/file/symbol or measured experiment.

### Streaming behavior

- Capture has bounded queues and a documented backpressure/drop policy.
- Shutdown, Ctrl-C, retune, timeout, USB stall, and removal release interfaces and finalize output.
- Timestamps state their clock, resolution, conversion, and limitations.
- Statistics distinguish USB transfers, decoded MPDUs, aggregates, malformed inputs, FCS failures,
  and application-side drops.

### Test strategy

- Pure unit tests cover frame and firmware boundaries.
- A fake USB transport drives deterministic success, timeout, short-transfer, and disconnect tests.
- Sanitized golden captures are checked by both this project and an independent decoder such as
  Wireshark/tshark.
- Property-based/fuzz tests target every length-controlled parser and serializer.
- Hardware smoke, bandwidth qualification, retune/soak, and recovery tests produce redacted,
  machine-readable evidence; they remain separate from hosted CI.

### Packaging and API discipline

- Supported Python/macOS/hardware combinations are explicit and narrow.
- Public APIs use typed records, stable exceptions, context-managed lifetimes, and semantic
  versioning. Internal register access is clearly distinguished from supported API.
- Dependencies and firmware are pinned or bounded with provenance and integrity checks; source
  and wheel contents are inspected before release.
- One command reproduces formatting, linting, tests, shell checks, and package construction.

### Safety, privacy, and responsible RF behavior

- Passive captures are treated as potentially sensitive data; examples avoid public identifiers
  and payload retention unless requested.
- Transmit paths fail closed, are rate-limited and observable, and document regulatory assumptions.
- Security reports have a private path, and malformed device/air input is in the threat model.
- Claims distinguish offline synthetic coverage, observed hardware behavior, and untested behavior.

The roadmap tracks in [ROADMAP.md](../ROADMAP.md) turn the most important gaps above into acceptance criteria rather than a vague
promise to “improve quality.”
