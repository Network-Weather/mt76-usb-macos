#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-3-Clause-Clear
# Copyright (c) 2026 Network Weather, Inc.
# One-time, idempotent setup. Creates a repo-local venv and fetches the MediaTek
# firmware into a gitignored directory. Re-runnable: skips what already exists.
#
#   bash setup.sh
#
# Creates:
#   .venv/           python venv with pyusb           (gitignored)
#   firmware/*.bin   MediaTek MT7961 blobs, fetched   (gitignored; NOT committed, licensed)
#
# Examples default MT7921_FW_DIR to ./firmware, so no env var is needed after this.
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || { echo "cannot cd to repo root"; exit 1; }

echo "== mt7921u-macos setup ($ROOT) =="

# --- venv + pyusb ---
if [ -x .venv/bin/python ] && .venv/bin/python -c 'import usb.core' 2>/dev/null; then
  echo "venv: ok"
else
  echo "venv: creating + installing pyusb"
  python3 -m venv .venv || { echo "venv creation failed"; exit 1; }
  ./.venv/bin/pip -q install --upgrade pip >/dev/null 2>&1 || true
  ./.venv/bin/pip -q install pyusb || { echo "pyusb install failed"; exit 1; }
  if .venv/bin/python -c 'import usb.core' 2>/dev/null; then
    echo "venv: ok"
  else
    echo "venv: pyusb import still failing"
    exit 1
  fi
fi

# --- libusb backend (pyusb needs it; Homebrew supplies it on macOS) ---
libusb_found=0
for lib in /opt/homebrew/lib/libusb-1.0.dylib /usr/local/lib/libusb-1.0.dylib; do
  if [ -e "$lib" ]; then libusb_found=1; break; fi
done
if [ "$libusb_found" = 0 ]; then
  echo "libusb: NOT found — run 'brew install libusb' (pyusb needs the native backend)"
else
  echo "libusb: ok"
fi

# --- firmware (MediaTek-licensed; fetched, never committed) ---
FW="$ROOT/firmware"; mkdir -p "$FW"
# Pinned for repeatability. Update the commit and both hashes together, then
# record the hardware validation in docs/TESTING.md.
LINUX_FIRMWARE_COMMIT="e981caea6ed33c48d25b7dbf473327dbd01df163"
BASE="https://gitlab.com/kernel-firmware/linux-firmware/-/raw/$LINUX_FIRMWARE_COMMIT/mediatek"
need=0
for entry in \
  "WIFI_RAM_CODE_MT7961_1.bin b94217a951518a9c14095765f367bc5dd7698f2dc033941d6f18fc2ebd6a2ab9" \
  "WIFI_MT7961_patch_mcu_1_2_hdr.bin a276c06c2b772adb50b86639d33c82824ff4c21d617feb78caea74c040b873f6"; do
  f=${entry%% *}
  expected=${entry#* }
  actual=""
  if [ -s "$FW/$f" ]; then
    actual=$(shasum -a 256 "$FW/$f" | awk '{print $1}')
  fi
  if [ "$actual" = "$expected" ]; then
    echo "firmware: $f ok (sha256 verified)"
  else
    if [ -n "$actual" ]; then
      echo "firmware: $f checksum mismatch; fetching pinned copy"
    fi
    echo "firmware: fetching $f"
    tmp="$FW/$f.tmp.$$"
    if curl -fsSL "$BASE/$f" -o "$tmp"; then
      actual=$(shasum -a 256 "$tmp" | awk '{print $1}')
      if [ "$actual" = "$expected" ]; then
        mv "$tmp" "$FW/$f"
        echo "firmware: $f ok (sha256 verified)"
      else
        rm -f "$tmp"
        echo "firmware: CHECKSUM FAILED for $f"; need=1
      fi
    else
      rm -f "$tmp"
      echo "firmware: FETCH FAILED for $f (get it from $BASE/$f)"; need=1
    fi
  fi
done

echo
if [ "$need" = 0 ]; then
  echo "READY. Firmware is at: $FW"
  echo "  Try:  ./.venv/bin/python examples/scan.py"
else
  echo "INCOMPLETE — resolve the firmware fetch above, then re-run."
  exit 1
fi
