# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Primatech Paper Co LLC d/b/a Network Weather
# Run from any directory; requires Visual Studio C++ tools and the Windows SDK.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installation) { throw 'Visual Studio C++ tools were not found.' }
$vcvars = Join-Path $installation 'VC\Auxiliary\Build\vcvars64.bat'
$output = Join-Path $repo 'build\windows'
New-Item -ItemType Directory -Force $output | Out-Null
$batch = Join-Path $output 'compile-probe.cmd'
@"
@echo off
call "$vcvars" >nul
if errorlevel 1 exit /b %errorlevel%
cl /nologo /W4 /WX /std:c17 /O2 /Fe:build\windows\winusb_probe.exe /Fo:build\windows\winusb_probe.obj research\windows\winusb_probe.c /link setupapi.lib winusb.lib ole32.lib user32.lib
"@ | Set-Content -Encoding ascii $batch
Push-Location $repo
try {
    & $batch
    if ($LASTEXITCODE -ne 0) { throw "Probe compilation failed: $LASTEXITCODE" }
} finally {
    Pop-Location
}
