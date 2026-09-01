#!/usr/bin/env bash
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
set -u
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
  .venv/bin/python -c 'import usb.core' 2>/dev/null && echo "venv: ok" \
    || { echo "venv: pyusb import still failing"; exit 1; }
fi

# --- libusb backend (pyusb needs it; Homebrew supplies it on macOS) ---
if ! ls /opt/homebrew/lib/libusb-1.0*.dylib /usr/local/lib/libusb-1.0*.dylib >/dev/null 2>&1; then
  echo "libusb: NOT found — run 'brew install libusb' (pyusb needs the native backend)"
fi

# --- firmware (MediaTek-licensed; fetched, never committed) ---
FW="$ROOT/firmware"; mkdir -p "$FW"
BASE="https://gitlab.com/kernel-firmware/linux-firmware/-/raw/main/mediatek"
need=0
for f in WIFI_RAM_CODE_MT7961_1.bin WIFI_MT7961_patch_mcu_1_2_hdr.bin; do
  if [ -s "$FW/$f" ]; then
    echo "firmware: $f ok"
  else
    echo "firmware: fetching $f"
    if curl -fsSL "$BASE/$f" -o "$FW/$f"; then echo "firmware: $f ok"; else
      echo "firmware: FETCH FAILED for $f (get it from $BASE/$f)"; need=1; fi
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
