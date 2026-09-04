#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
"""Capture on two channels at once with two adapters, into one timeline.

One radio cannot watch both channels of a roam. The steering exchange, the deauth or
disassoc, and the client's last data frame happen on the current AP's channel; only the
authentication and reassociation happen on the target. This runs one adapter on each and
merges what they hear into a single ordered event log, so both halves of a transition are
in one file with a common clock.

  dual_capture.py --radio 2:20=5GHz:132@80 --radio 2:9=6GHz:53@160 --duration 120

Each --radio is SELECTOR=BAND:CHANNEL[@WIDTH]. A SELECTOR is either a USB id
("0e8d:7961", four hex digits each side) or a port address ("2:21", the "bus:addr" that
`--list` prints). Prefer the USB id: it is a property of the model and does not change.
The port address is what tells two adapters of the *same* model apart without reading a
serial number, but it is reassigned whenever the adapter re-enumerates, which every
firmware boot does, so list immediately before a run rather than hard-coding it.

With --client, the address set is shared across radios: a link address learned from a
Multi-Link element on one radio is matched on the other from that moment. An 802.11be
client uses a different address per link, so this is what lets both radios agree they are
watching the same station.

Output is a JSON result on stdout. It carries counts, event names, and timings only.
Addresses and SSIDs appear only with --identify, which is opt-in because a capture of
someone's network is sensitive; see docs/PRIVACY notes in README.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import usb.core  # noqa: E402

import mt7921u as m  # noqa: E402
import rxd  # noqa: E402

READ_TIMEOUT_MS = 250
FTYPE_DATA = 2


class Timeline:
    """Events from every radio, ordered by one clock.

    Each radio runs in its own thread, so the list and the shared client address set are
    guarded. `start` is captured once, before any thread runs, so every timestamp is
    comparable across radios; a per-thread start would put the two radios on clocks that
    differ by however long the second firmware download took.
    """

    def __init__(self, client: str | None):
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.client_addresses = {client} if client else set()
        self.learned: list[dict] = []
        self.start = time.monotonic()

    def stamp(self) -> float:
        return round(time.monotonic() - self.start, 4)

    def add(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)

    def matches_client(self, addresses: set[str]) -> bool:
        """True if any of these addresses is the client. Empty set means no filter."""
        with self.lock:
            return not self.client_addresses or bool(addresses & self.client_addresses)

    def learn(self, radio: str, transmitted: set[str]) -> list[str]:
        """Fold a frame's transmitter addresses into the client set if it is the client.

        Only ever called with the addresses of one station, from a frame that station
        transmitted, so an AP's own Multi-Link element cannot join the client's identity.
        """
        with self.lock:
            if not self.client_addresses or not transmitted & self.client_addresses:
                return []
            new = sorted(transmitted - self.client_addresses)
            self.client_addresses |= transmitted
            for address in new:
                self.learned.append({"at": self.stamp(), "radio": radio, "address": address})
            return new


USB_ID_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$")
PORT_ADDRESS_RE = re.compile(r"^\d+:\d+$")


class Radio:
    """One adapter locked to one channel for the run."""

    def __init__(self, selector: str, band: str, channel: int, width: int):
        self.selector = selector
        self.band = band
        self.channel = channel
        self.width = width
        self.label = f"{band}:{channel}@{width}"
        # A USB id names a model; a port address names where one is plugged in. Only the
        # second can separate two identical adapters, and only the first survives a
        # re-enumeration, so a caller picks whichever its situation needs. Either way the
        # selector is resolved to one port before the radio opens anything.
        self.usb_id = selector if USB_ID_RE.match(selector) else None
        self.port: str | None = None

    def resolve(self, port: str) -> None:
        """Bind this radio to the one adapter its selector named."""
        self.port = port
        self.counts = {
            "frames": 0,
            "off_channel": 0,
            "management_events": 0,
            "client_data_frames": 0,
            "usb_timeouts": 0,
            "usb_errors": 0,
        }
        self.chip: str | None = None
        self.error: str | None = None
        self.last_client_data: float | None = None

    def run(self, timeline: Timeline, duration: float, identify: bool) -> None:
        try:
            self._run(timeline, duration, identify)
        except Exception as exc:  # a failed radio must not take the other one down
            self.error = f"{type(exc).__name__}: {exc}"

    def _run(self, timeline: Timeline, duration: float, identify: bool) -> None:
        if self.port is None:
            raise ValueError(f"radio {self.selector} was never resolved to an adapter")
        # By port, and by nothing else. open_device() would fall back to $MT76_USB_ID and
        # $MT76_USB_ADDR, and a variable left exported from a single-radio run would then
        # make one of these two radios fail to open an adapter the inventory just listed.
        dev = m.open_device_at(self.port)
        self.chip = dev.CHIP
        # The chip is only known once a device is chosen, so this cannot happen during
        # argument parsing. It happens before the firmware download because a width this
        # chip cannot capture returns no transfers rather than an error, and a radio that
        # reports zero frames with no error looks like a quiet channel.
        if self.width > dev.MAX_WIDTH_MHZ:
            raise ValueError(
                f"the {dev.CHIP} at {self.selector} captures up to {dev.MAX_WIDTH_MHZ} MHz; "
                f"{self.width} MHz would tune a radio that returns no frames"
            )
        patch, ram = m.load_firmware(dev.CHIP, m.firmware_dir())
        with dev:
            dev.bringup(patch, ram, log=lambda *a: None)
            dev.set_monitor_mode()
            dev.set_sniffer(True)
            center = m.center_channel(self.band, self.channel, self.width)
            if center is None:
                raise ValueError(
                    f"no {self.width} MHz channel on {self.band} contains "
                    f"control channel {self.channel}"
                )
            dev.tune(self.band, self.channel, center, self.width)
            decode = m.decoder_for(dev)
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                try:
                    raw = bytes(dev.rx_read(timeout=READ_TIMEOUT_MS))
                except usb.core.USBTimeoutError:
                    self.counts["usb_timeouts"] += 1
                    continue
                except usb.core.USBError:
                    # Frames can be missed after a transport failure; count it rather
                    # than letting the run look clean.
                    self.counts["usb_errors"] += 1
                    continue
                descriptor = decode(raw)
                if not descriptor or not descriptor.get("frame"):
                    continue
                if len(descriptor["frame"]) < 10:
                    continue
                self.counts["frames"] += 1
                self._handle(descriptor, timeline, identify)

    def _handle(self, descriptor: dict, timeline: Timeline, identify: bool) -> None:
        if descriptor.get("band") != self.band or descriptor.get("channel") != self.channel:
            # Queued from before the tune, or an adjacent 2.4 GHz channel. Evidence for a
            # locked channel must exclude it.
            self.counts["off_channel"] += 1
            return
        parsed = rxd.parse_80211(descriptor["frame"])
        transmitted = rxd.station_addresses(parsed)
        for address in timeline.learn(self.label, transmitted):
            if identify:
                timeline.add(
                    {
                        "at": timeline.stamp(),
                        "radio": self.label,
                        "event": "client_address_learned",
                        "address": address,
                    }
                )

        if parsed.get("ftype") == FTYPE_DATA:
            seen = {parsed.get("addr1"), parsed.get("addr2")} - {None}
            if timeline.matches_client(seen) and timeline.client_addresses:
                self.counts["client_data_frames"] += 1
                self.last_client_data = timeline.stamp()
            return

        event = rxd.management_event(parsed)
        if event is None:
            return
        name, detail = event
        involved = {parsed.get("addr1"), parsed.get("addr2"), parsed.get("addr3")} - {None}
        if not timeline.matches_client(involved):
            return
        self.counts["management_events"] += 1
        record = {
            "at": timeline.stamp(),
            "radio": self.label,
            "chip": self.chip,
            "event": name,
            "rssi": descriptor.get("rssi"),
        }
        if identify:
            record["from"] = parsed.get("addr2")
            record["to"] = parsed.get("addr1")
            record["bssid"] = parsed.get("addr3")
            record["detail"] = detail
        timeline.add(record)


def parse_radio(text: str) -> Radio:
    selector, _, target = text.partition("=")
    if not selector or not target:
        raise argparse.ArgumentTypeError(
            f"--radio wants SELECTOR=BAND:CHANNEL[@WIDTH], got {text!r}"
        )
    # The inventory reports USB ids in lowercase, so an accepted uppercase selector must
    # be folded here rather than failing to match later. A port address is digits only.
    selector = selector.lower()
    if not USB_ID_RE.match(selector) and not PORT_ADDRESS_RE.match(selector):
        raise argparse.ArgumentTypeError(
            f"{selector!r} is neither a USB id (0e8d:7961) nor a port address (2:21); "
            "--list prints both for every attached adapter"
        )
    channel_part, _, width_text = target.partition("@")
    band, _, channel_text = channel_part.partition(":")
    if band not in m.CHAN_BAND or not channel_text.isdigit():
        raise argparse.ArgumentTypeError(f"bad band or channel in {text!r}, for example 5GHz:132")
    width = int(width_text) if width_text else 20
    if width not in m.WIDTH_TO_SNIFFER_BW:
        raise argparse.ArgumentTypeError(
            f"width must be one of {sorted(m.WIDTH_TO_SNIFFER_BW)} MHz, got {width}"
        )
    channel = int(channel_text)
    if channel not in m.CONTROL_CHANNELS[band]:
        raise argparse.ArgumentTypeError(f"{band} has no channel {channel}")
    if m.center_channel(band, channel, width) is None:
        raise argparse.ArgumentTypeError(
            f"no {width} MHz channel on {band} contains control channel {channel}"
        )
    return Radio(selector, band, channel, width)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list", action="store_true", help="print attached adapters and exit")
    parser.add_argument(
        "--radio",
        action="append",
        default=[],
        metavar="SELECTOR=BAND:CHANNEL[@WIDTH]",
        help="an adapter and the channel to lock it to; repeat for each radio. SELECTOR "
        "is a USB id (0e8d:7961) or a port address (2:21) as printed by --list",
    )
    parser.add_argument("--client", metavar="MAC", help="only report events involving this station")
    parser.add_argument("--duration", type=float, default=120.0, help="seconds to capture")
    parser.add_argument(
        "--identify",
        action="store_true",
        help="include addresses and event detail; off by default because a capture of a "
        "real network is sensitive",
    )
    args = parser.parse_args()

    if args.list:
        for entry in m.describe_supported_devices():
            print(f"{entry['address']:<8} {entry['usb_id']}  {entry['chip']}")
        return 0

    if len(args.radio) < 2:
        parser.error("give at least two --radio arguments; use --list to see attached adapters")
    if not 1 <= args.duration <= 3600:
        parser.error("--duration must be between 1 and 3600 seconds")

    try:
        radios = [parse_radio(text) for text in args.radio]
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    inventory = m.describe_supported_devices()
    resolved: dict[str, str] = {}
    for radio in radios:
        matched = [
            entry for entry in inventory if radio.selector in (entry["address"], entry["usb_id"])
        ]
        if not matched:
            parser.error(
                f"no supported adapter matches {radio.selector!r}; --list shows what is attached"
            )
        if len(matched) > 1:
            where = ", ".join(entry["address"] for entry in matched)
            parser.error(
                f"{radio.selector!r} matches {len(matched)} attached adapters (at {where}); "
                "use a port address to pick one"
            )
        # Two different selectors can name one adapter: its USB id, and the port it is
        # plugged into. Comparing selector strings would accept that pair and then have
        # both threads claim the same interface, so compare what each one resolves to.
        port = matched[0]["address"]
        if port in resolved:
            parser.error(
                f"--radio {radio.selector!r} and {resolved[port]!r} are the same adapter, "
                f"at {port}; each radio needs a different one"
            )
        resolved[port] = radio.selector
        radio.resolve(port)

    client = args.client.lower() if args.client else None
    timeline = Timeline(client)
    threads = [
        threading.Thread(target=radio.run, args=(timeline, args.duration, args.identify))
        for radio in radios
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    result = {
        "duration_s": args.duration,
        "identify": args.identify,
        "radios": [
            {
                "selector": radio.selector,
                "chip": radio.chip,
                "band": radio.band,
                "channel": radio.channel,
                "width_mhz": radio.width,
                "error": radio.error,
                "last_client_data_s": radio.last_client_data,
                **radio.counts,
            }
            for radio in radios
        ],
        "client_addresses_learned": len(timeline.learned),
        "events": sorted(timeline.events, key=lambda event: event["at"]),
    }
    if args.identify:
        result["client_addresses"] = sorted(timeline.client_addresses)
        result["learned"] = timeline.learned
    json.dump(result, sys.stdout, indent=2)
    print()
    return 1 if any(radio.error for radio in radios) else 0


if __name__ == "__main__":
    sys.exit(main())
