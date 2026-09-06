# Security policy

This project processes untrusted 802.11 frames and controls firmware-bearing USB hardware.
Please report memory/resource exhaustion, malformed-frame failures, unsafe device-state
transitions, or unintended transmission behavior through a private GitHub Security
Advisory when disclosure could put users or networks at risk. Ordinary crashes and capture
decode bugs can use the public issue tracker.

Never attach an unredacted ambient pcap to a public issue. Reduce it to a synthetic frame
or remove SSIDs, MAC addresses, payloads, credentials, and other third-party data first.

This also applies to raw USB/MCU event dumps and CSI reports. CSI transmitter
addresses, I/Q coefficients and derived fingerprints can identify a network or
its physical environment even when no packet payload is retained. Python's
default CSI representation hides addresses and coefficients; explicit
serialization, native structs and raw event queues still expose them. It is not
an anonymization boundary. Prefer synthetic parser fixtures and aggregate
counts, error categories and cleanup results when sharing measurement evidence.

Treat radio frames and firmware events as untrusted binary input. The bounded
parsers and queue limits do not establish measurement calibration or freshness,
and a successful command does not establish safe device reuse. Follow the
documented one-owner, stop and full-reload requirements for experimental
[CSI](docs/CSI_API.md) and [histogram](docs/HISTOGRAM_API.md) acquisition; retain
cleanup failures rather than silently reusing a possibly active device.

Only the latest commit on `main` is supported. This is research-grade software and does
not receive a production security-response SLA.
