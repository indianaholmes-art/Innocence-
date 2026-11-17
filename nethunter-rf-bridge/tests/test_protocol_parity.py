"""Ensure firmware, simulator and docs agree on the command set."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fw_cmds():
    src = (ROOT / "firmware/src/protocol.cpp").read_text()
    return set(re.findall(r'!strcmp\(cmd, "([A-Z_]+)"\)', src))


def _sim_cmds():
    src = (ROOT / "host/nethunter_rf/simulator.py").read_text()
    return set(re.findall(r'cmd (?:==|in) \(?"([A-Z_]+)"', src)) | set(re.findall(r'"([A-Z_]+)"\)', src))


def test_firmware_commands_documented():
    doc = (ROOT / "docs/PROTOCOL.md").read_text()
    missing = [c for c in _fw_cmds() if f"`{c}`" not in doc]
    assert not missing, missing


def test_simulator_implements_firmware_commands():
    fw = _fw_cmds() - {"REBOOT"}
    sim = _sim_cmds()
    assert fw <= sim, fw - sim
