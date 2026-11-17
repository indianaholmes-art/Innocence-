#!/usr/bin/env bash
# Compiles the firmware sources natively (stubbed Arduino core, real
# ArduinoJson) and runs protocol/driver tests. Usage:
#   ARDUINOJSON_DIR=/path/to/ArduinoJson/src tests/native/build_and_run.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
FW="$HERE/../../firmware"
: "${ARDUINOJSON_DIR:?set ARDUINOJSON_DIR to ArduinoJson v7 src/ directory}"
OUT="${OUT_DIR:-$(mktemp -d)}"
CXX="${CXX:-g++}"
"$CXX" -std=gnu++17 -Wall -Wextra -Wno-unused-parameter -O1 -g \
  -DARDUINO=10819 -DARDUINOJSON_ENABLE_PROGMEM=0 -DRFB_BOARD_DEVKITC1 -DCONFIG_IDF_TARGET_ESP32S3 \
  -I"$HERE/stubs" -I"$FW/include" -I"$ARDUINOJSON_DIR" \
  "$FW/src/radio_common.cpp" "$FW/src/cc1101.cpp" "$FW/src/sim_radio.cpp" "$FW/src/protocol.cpp" \
  "$HERE/native_stubs.cpp" "$HERE/test_firmware.cpp" -o "$OUT/fw_native_test"
"$OUT/fw_native_test"
