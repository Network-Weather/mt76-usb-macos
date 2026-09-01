# Security policy

This project processes untrusted 802.11 frames and controls firmware-bearing USB hardware.
Please report memory/resource exhaustion, malformed-frame failures, unsafe device-state
transitions, or unintended transmission behavior through a private GitHub Security
Advisory when disclosure could put users or networks at risk. Ordinary crashes and capture
decode bugs can use the public issue tracker.

Never attach an unredacted ambient pcap to a public issue. Reduce it to a synthetic frame
or remove SSIDs, MAC addresses, payloads, credentials, and other third-party data first.

Only the latest commit on `main` is supported. This is research-grade software and does
not receive a production security-response SLA.

