#!/usr/bin/env bash
# Runs Python tests and (if ARDUINOJSON_DIR or network is available) the
# native firmware tests.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 -m pytest -q "$ROOT/tests"
if [ -z "${ARDUINOJSON_DIR:-}" ]; then
  TMP="$(mktemp -d)"
  if git clone -q --depth 1 --branch v7.2.1 https://github.com/bblanchon/ArduinoJson.git "$TMP/aj" 2>/dev/null; then
    ARDUINOJSON_DIR="$TMP/aj/src"
  fi
fi
if [ -n "${ARDUINOJSON_DIR:-}" ] && command -v g++ >/dev/null; then
  ARDUINOJSON_DIR="$ARDUINOJSON_DIR" "$ROOT/tests/native/build_and_run.sh"
else
  echo "skipping native firmware tests (need g++ and ArduinoJson v7 source)"
fi
