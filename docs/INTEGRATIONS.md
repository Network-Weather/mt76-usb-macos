# Integration opportunities

No project below is presumed to want this code, and no integration is claimed until its
maintainers accept one. These are technically plausible consumers, ordered by fit. The current
safest interchange format is a radiotap pcap file; neither a live API nor a compatibility policy
is stable yet.

## Works today through capture files

### Wireshark and tshark

This is the strongest immediate fit. `examples/sniff_to_pcap.py` emits link type 127 radiotap
pcap that Wireshark has independently decoded in the attached-hardware test. Wireshark's
[extcap developer interface](https://www.wireshark.org/docs/wsdg_html_chunked/ChCaptureExtcap.html)
is explicitly intended to make external scripts and unusual hardware appear as capture sources,
so Roadmap R6 is a natural next integration rather than a custom GUI.

Potential contribution: an executable extcap script that enumerates the USB device and valid
channels, reports the radiotap DLT, exposes conservative configuration, and streams into the
FIFO Wireshark supplies.

### Scapy

Scapy already [reads/writes pcap and supports configurable sockets](https://scapy.readthedocs.io/en/stable/usage.html)
and has a radiotap/802.11 model. It can consume current capture files without modifying either
project. After the long-lived capture API exists, a small receive-only
[`SuperSocket`](https://scapy.readthedocs.io/en/stable/api/scapy.supersocket.html) adapter could
let Scapy scripts sniff directly from the MT7921U without pretending it is a libpcap interface.

Potential contribution: keep the adapter thin and downstream first. Upstream discussion only
makes sense after lifecycle, timestamps, exceptions, and the supported API are stable.

## Plausible adapters after the capture API stabilizes

### Kismet

Kismet supports out-of-process capture sources over an IPC/network protocol, including capture
code written in Python; its [datasource documentation](https://www.kismetwireless.net/docs/dev/datasources/)
describes packet-producing helpers and its
[capture framework](https://www.kismetwireless.net/docs/dev/capframework/) handles device
enumeration, configuration, and packet transport. That makes an MT7921U source plausible, but it
is more work than piping pcap: it needs the Kismet datasource protocol, channel-control semantics,
unique device identity, and robust long-running behavior.

Potential contribution: a separate `kismet_cap_mt7921u` helper after Roadmap R1, R2, R5, and R8.
Kismet's remote-capture model could then make a Mac-attached 6 GHz sensor useful to a central
Kismet server.

### wifit3

[wifit3](https://github.com/derv82/wifit3) is the closest language-level peer: a broader Python
userspace Wi-Fi auditing project with its own MT7921AU implementation. It is more likely to
benefit from narrowly reusable artifacts than from replacing its driver wholesale:

- measured endpoint-routing, sniffer-command, efuse, and initialization findings;
- sanitized parser fixtures and independent 6 GHz evidence;
- descriptor discovery or a fake-USB transport once those exist; and
- a stable passive capture primitive if its maintainers prefer sharing one.

Any transfer must retain provenance to mt76 and distinguish independently discovered facts from
code derived here or there. [RELATED_WORK.md](../RELATED_WORK.md) records the current relationship;
no wifit3 code is incorporated in this repository.

### wifikit

[wifikit](https://github.com/RLabs-Inc/wifikit) is the closest native macOS peer and already has
broader chipset and workflow coverage in Rust. Python code is not directly reusable there, but
protocol findings, test vectors, failure cases, and hardware matrices are. Conversely, its
operational experience should inform this project's lifecycle and usability work without copying
implementation.

Potential contribution: exchange reproducible, redacted device/firmware observations and compare
6 GHz/bandwidth behavior. This project should not duplicate wifikit's broad application or active
engine surface.

## Components that could reuse knowledge, not the Python package

- **Rust or Swift macOS capture applications** could implement the documented firmware/USB
  sequence and validate against the sanitized fixtures. They would normally not embed Python.
- **Other MT76 userspace ports** can use the measured endpoint transition, descriptor layout,
  patch semaphore, sniffer command, and efuse requirements as hypotheses to reproduce.
- **Driver and firmware researchers** can use small parsing functions and test vectors to inspect
  MCU/RX structures without first extracting them from a kernel driver.
- **Radio-environment tools** can consume the research scripts' aggregate JSON for primary CCA,
  decoded airtime and ED-active time. The counters cover the primary 20 MHz; a wider-channel
  consumer must sample each constituent primary, and must not label ED-active or
  CCA-minus-decoded time as non-Wi-Fi interference. The evidence boundary is documented in
  [MT7925_MIB.md](MT7925_MIB.md).
- **Offline 802.11 analysis tools** can consume pcap output, but this project should avoid custom
  adapters when a standards-based capture file is sufficient.

## Poor fits and boundaries

- **libpcap itself:** the adapter is not a macOS network interface. A private libpcap backend would
  add a large maintenance surface; extcap or a documented stream is the more honest boundary.
- **CoreWLAN/NetworkExtension:** these system APIs do not turn a userspace USB firmware driver into
  a managed Wi-Fi interface. Association and normal networking are explicit non-goals.
- **Linux mt76:** mt76 is the foundational source and the right Linux driver. Linux should use it,
  not this Python port.
- **Broad attack-suite integration:** transmit remains unstable and unqualified. No downstream
  project should build active workflows on it until the gated transmit criteria in the roadmap
  are met.

## Contract needed before downstream adoption

A supported integration API should provide typed capability/device records, explicit channel and
bandwidth validation, a context-managed capture session, radiotap bytes plus timestamps, bounded
queues and drop counters, structured exceptions, cancellation, and a compatibility policy. Until
then, the pcap format and documented measured findings are the safest reusable outputs.
