# Windows MT7961 capture experiment

This spike targets the ALFA AWUS036AXML (`0e8d:7961`, Wi-Fi interface 3) on
Windows 11 x64. It is not a Windows support claim. The production driver remains
unchanged; the native SDK probe isolates USB access from Python and libusb.

## Prepare the Python tools

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run
from the repository root in PowerShell:

```powershell
. .\research\windows\setup.ps1
.\.venv\Scripts\python.exe scripts\usb_descriptors.py --chip-id --json
.\.venv\Scripts\python.exe scripts\firmware_boot.py --usb-id 0e8d:7961 --rx 3
```

The setup script creates `.venv`, installs pinned PyUSB/libusb-package versions,
adds the packaged DLL directory to this session's PATH, enables Python UTF-8
mode, and fetches only the MT7961 firmware using the commit and SHA-256 hashes in
`mt7921u.py`. Firmware remains in the ignored `firmware/` directory. See
[NOTICE.md](../../NOTICE.md) for firmware licensing. Rerun the setup script in a
new shell to restore its session environment.

The Wi-Fi interface must be bound to WinUSB. For this experiment use the signed
[Zadig release](https://github.com/pbatard/libwdi/releases/tag/v1.5.1), select
**WiFi_If (Interface 3)**, verify **0E8D / 7961 / 03**, and install WinUSB. Do not
replace the composite parent or Bluetooth interface. Device installation needs
Windows elevation; capture runs in an ordinary user process.

For a packaged application, provide a signed, interface-specific driver package
and an installer instead of asking users to select a device in Zadig. Microsoft's
[WinUSB installation guide](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/winusb-installation)
describes the INF, catalog signing, and device interface GUID requirements.

## Native read-only probe

Requires Visual Studio C++ tools and the Windows SDK. Build with warnings treated
as errors and run against the installed interface's GUID:

```powershell
.\research\windows\build_probe.ps1
$wifi = @(Get-PnpDevice -PresentOnly | Where-Object {
    $_.InstanceId -like 'USB\VID_0E8D&PID_7961&MI_03*'
})
if ($wifi.Count -ne 1) { throw 'Connect exactly one MT7961 Wi-Fi interface.' }
$key = "HKLM:\SYSTEM\CurrentControlSet\Enum\$($wifi[0].InstanceId)\Device Parameters"
$guid = (Get-ItemProperty -LiteralPath $key).DeviceInterfaceGUIDs[0]
.\build\windows\winusb_probe.exe $guid
```

The probe uses SetupAPI and WinUSB directly. It checks interface identity, lists
endpoints, and reads chip ID, revision and endpoint reset options with the
repository's control request encoding. It does not install drivers, load firmware,
write device registers or print device serials. Exit 0 means all reads succeeded;
1 means a probe failure, 2 invalid arguments, and 3 no matching interface.

## Bounded register-alias experiment

```powershell
.\.venv\Scripts\python.exe research\windows\boot_alias_probe.py boot --usb-id 0e8d:7961 --rx 3
# Only after bring-up succeeds:
.\.venv\Scripts\python.exe research\windows\boot_alias_probe.py capture 6 10 build\windows\capture.pcap 2.4GHz
```

This opt-in wrapper substitutes ordinary register reads/writes for two addresses:
endpoint reset options and the connection-infrastructure status selector. Reset
assertion and deassertion retain the UHW request encoding. The wrapper restores
the Python methods on exit. This is an unqualified hardware experiment; if the
adapter stops responding, unplug it and reconnect it before another attempt.

## Evidence and limits

On Windows 11 Pro build 26200, Python 3.14.2, PyUSB 1.3.1 and libusb-package
1.0.30.0, binding WinUSB clears interface 3's Code 28. Both PyUSB and the native
SDK probe read chip ID `0x7961` and revision `0x8a10`. The attached connection
reports USB high speed with 512-byte bulk maximum packets.

The unmodified firmware boot stops at the UHW read of `0x74011890`
(`bmRequestType=0xde`, request `0x01`). Native WinUSB independently returns error
87 for this read; libusb reports an I/O error. The ordinary register read of the
same address succeeds. A broad substitution of all UHW accesses with ordinary
accesses fails during reset and leaves register reads timing out. These results
do not establish whether WinUSB or the composite parent rejects the request.

The initial offline suite has 1,487 passes, 139 skips and two failures caused by
implicit Windows cp1252 decoding of UTF-8 documentation. All four tests in that
documentation module pass with `python -X utf8`. C compilation passes
`/W4 /WX /std:c17`. Packet capture is not yet demonstrated by these results.
