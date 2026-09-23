# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
# Dot-source to retain the session-local libusb DLL search path:
#   . .\research\windows\setup.ps1
# Requires uv. This does not install or change Windows device drivers.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repo '.venv\Scripts\python.exe'
Push-Location $repo
try {
    if (-not (Test-Path -LiteralPath $python)) {
        uv venv --python 3.14 .venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }
    uv pip install --python $python 'pyusb==1.3.1' 'libusb-package==1.0.30.0'
    if ($LASTEXITCODE -ne 0) { throw 'USB dependency installation failed.' }
    $dll = & $python -c 'import libusb_package; print(libusb_package.get_library_path().parent)'
    if ($LASTEXITCODE -ne 0) { throw 'The packaged libusb DLL was not found.' }
    $env:PATH = "$dll;$env:PATH"
    $env:PYTHONUTF8 = '1'
    & $python (Join-Path $PSScriptRoot 'fetch_firmware.py')
    if ($LASTEXITCODE -ne 0) { throw 'Firmware preparation failed.' }
    Write-Output 'Python/libusb and MT7961 firmware ready; interface 3 needs a WinUSB binding.'
} finally {
    Pop-Location
}
