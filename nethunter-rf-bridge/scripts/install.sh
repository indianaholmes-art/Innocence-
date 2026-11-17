#!/usr/bin/env bash
# Install the NetHunter RF Bridge host app (no root required).
# Works in the Kali NetHunter chroot, NetHunter Rootless (Termux) and desktop Linux.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${RFB_PREFIX:-$HOME/.local/share/nethunter-rf}"
BIN="${RFB_BIN:-$HOME/.local/bin}"

say() { printf '\033[1;36m[rfb]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[rfb]\033[0m %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null || die "python3 not found (apt install python3 / pkg install python)"
python3 - <<'PY' || die "Python >= 3.9 required"
import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)
PY

if python3 -m venv --help >/dev/null 2>&1 && python3 -m venv "$PREFIX" 2>/dev/null; then
  say "virtualenv: $PREFIX"
  "$PREFIX/bin/python" -m pip install -q --upgrade pip || true
  if ! "$PREFIX/bin/python" -m pip install -q "$ROOT/host"; then
    die "pip install failed (offline?). Try: sudo apt install python3-serial python3-rich"
  fi
  PY="$PREFIX/bin/python"
else
  say "python3-venv unavailable; trying system packages"
  if command -v apt-get >/dev/null && [ "$(id -u)" = 0 ]; then
    apt-get install -y python3-serial python3-rich
  fi
  python3 -c 'import serial, rich' 2>/dev/null || python3 -m pip install --user pyserial rich \
    || die "Install pyserial and rich manually"
  PY="python3"
  export PYTHONPATH="$ROOT/host"
fi

# Validate dependencies actually import.
PYTHONPATH="${PYTHONPATH:-}" "$PY" - <<'PY'
import serial, rich, serial.tools.list_ports
print("pyserial", serial.__version__, "| rich OK")
PY

mkdir -p "$BIN"
cat > "$BIN/nethunter-rf" <<SH
#!/usr/bin/env bash
PYTHONPATH="$ROOT/host\${PYTHONPATH:+:\$PYTHONPATH}" exec "$PY" -m nethunter_rf "\$@"
SH
chmod +x "$BIN/nethunter-rf"
say "installed launcher: $BIN/nethunter-rf"
case ":$PATH:" in *":$BIN:"*) ;; *) say "add to PATH:  export PATH=\"$BIN:\$PATH\"";; esac

say "self-test (simulation):"
"$BIN/nethunter-rf" --simulate --json version >/dev/null && say "OK - try: nethunter-rf doctor"
