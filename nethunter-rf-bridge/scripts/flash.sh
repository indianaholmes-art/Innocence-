#!/usr/bin/env bash
# Build and flash firmware. Usage: scripts/flash.sh [env] [port]
#   env: esp32s3_devkitc (default) | esp32s3_generic | esp32s3_sim | esp32c3_devkitm
set -euo pipefail
cd "$(dirname "$0")/../firmware"
ENV="${1:-esp32s3_devkitc}"
command -v pio >/dev/null || { echo "PlatformIO missing: pip install platformio" >&2; exit 1; }
if [ -n "${2:-}" ]; then pio run -e "$ENV" -t upload --upload-port "$2"; else pio run -e "$ENV" -t upload; fi
echo "Flashed $ENV. Verify with: nethunter-rf info"
