import json

import pytest

from nethunter_rf.analysis import Analyzer, Packet, load_signatures
from nethunter_rf.config import ConfigError, load_config
from nethunter_rf.export import export_csv, export_diagnostics, export_json, load_capture
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _packets():
    return [Packet(n=i, ts_us=i * 1000, frequency_hz=433_920_000, modulation="ASK/OOK", data=bytes([i, 0xAA]),
                   rssi_dbm=-70.5, lqi=3, crc_ok=True, host_time=1.5) for i in range(1, 4)]


def test_json_roundtrip(tmp_path):
    a = Analyzer()
    for p in _packets():
        a.add_packet(p)
    path = export_json(tmp_path / "c.json", a.packets, {"x": 1}, a)
    doc = json.loads(path.read_text())
    assert doc["capture_type"].startswith("cc1101-packet-metadata")
    back = load_capture(path)
    assert [p.data for p in back] == [p.data for p in a.packets]


def test_csv_roundtrip(tmp_path):
    path = export_csv(tmp_path / "c.csv", _packets())
    back = load_capture(path)
    assert len(back) == 3 and back[0].data == bytes([1, 0xAA]) and back[0].crc_ok


def test_bad_capture(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}")
    with pytest.raises(ValueError):
        load_capture(p)


def test_diagnostics_without_device(tmp_path):
    p = export_diagnostics(tmp_path / "d.json")
    d = json.loads(p.read_text())
    assert "usb" in d and "ports" in d


def test_example_configs_valid():
    for f in (ROOT / "config").glob("*.json"):
        if f.name.startswith("signatures"):
            assert load_signatures(f)
        else:
            assert "radio" in load_config(f)


def test_config_rejects_unknown(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"radio": {"frequncy_mhz": 433}}))
    with pytest.raises(ConfigError):
        load_config(p)
