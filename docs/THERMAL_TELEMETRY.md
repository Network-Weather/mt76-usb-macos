# MT7925 read-only thermal telemetry

2026-09-05. UNI35 exposes working analog-die temperature and raw ADC queries
on the pinned MT7925 RAM firmware
`23ff53b4bb639b30481e2e06bb1688569ad1ba971b897936db539882abfbd120`.
These are useful health observations alongside radio measurements, not an
explanation of the earlier weak/variable RF link or calibrated ambient temperature.

## Exact working request and reply

The [pinned vendor implementation](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/nic/nic_uni_cmd_event.c#L7201)
uses UNI35 tag0 for analog-die temperature. The
[public request/action definitions](https://github.com/MotorolaMobilityLLC/vendor-mediatek-kernel_modules-connectivity-wlan-core-gen4m/blob/8fddb9d7d80112cf3f2b68c961536ed61f4ab0ec/include/nic_uni_cmd_event.h#L3783)
also name action1 as ADC. Send explicit QUERY_ACK option3, not a thermal SET:

```text
4 zero prefix bytes
u16 tag=0, u16 length=8
u8 format=0, u8 action=0(temperature) or1(ADC), u8 band=0, u8 reserved=0
```

Observed event EID35 uses the requested sequence on USB endpoint84. Its bounded
body is16 bytes: four zeros, tag0/length12, category0/three reserved zeros, then
u32 sensor result. `reply_body()` also includes USB tail bytes; the published
parser bounds by RXD declared length, verifies event type/sequence/TLV/category
and does not export padding. Temperature is reported in Celsius, consistent
with [Linux mt7996's temperature query](https://github.com/openwrt/mt76/blob/c5a3bd91aa735b669618610d5f0ebfa5786845a6/mt7996/mcu.c#L4807).
ADC stays a raw code; no temperature conversion or sensor-resolution claim.

| Trial | Temperature before | Raw ADC | Temperature after |
| --- | ---: | ---: | ---: |
| Initial | 45°C | 68 | 45°C |
| Strict-parser reproducer | 45°C | 68 | 47°C |

The small variation is retained, not forced to a constant or attributed to
our query. Separate MT7961 existing temperature reads returned32°C three times.
All normal-reload/alive checks pass. No power, cooling, thermal-protection,
throttling, sensor calibration, or RF-test settings were changed; no TX.

## Digital-die route: no result observed

The vendor defines tag12 for digital-die sensor queries and a different event
tag5. Its temperature event handler retains the raw value while the analog
handler multiplies by1000 for its caller; do not assume both raw results share
units. Using the source's format0/sensor0 request, both temperature action0 and
ADC action1 ended in synchronous `McuError` without a result. That is not an
explicit firmware rejection status.

To rule out the previously encountered sequence-zero/endpoint routing issue,
one more digital-die temperature query was bracketed by working analog queries
and polled on both84/85 at1ms timeouts for0.6s per query. The analog controls
each returned matching-sequence45°C events on84; the digital query yielded no
events. Other sensors, modes and longer delays remain untested. This does not
establish absence of a digital sensor or general firmware non-support.

The reproducer intentionally exposes **only the working tag0, band0, actions0/1**:
[`mt7925_thermal_probe.py`](../research/mt7925_thermal_probe.py). Offline tests
cover exact framing, unsigned raw ADC versus signed temperature interpretation,
padding exclusion, malformed/event mismatch rejection and wrong-chip/SET guards.
[Sanitized evidence](../research/evidence/thermal-telemetry-2026-09-05.json)
contains sensor values and narrow event summaries, no firmware bytes or ambient
payloads. Production Python/C APIs and default acquisition are unchanged.
