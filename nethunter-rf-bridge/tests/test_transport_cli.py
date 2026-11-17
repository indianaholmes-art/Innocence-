import json
import os

import pytest

from nethunter_rf import cli, transport
from nethunter_rf.client import RFBridgeClient
from nethunter_rf.transport import PortInfo, SerialTransport, TransportError


class FakePort:
    def __init__(self, device, vid, pid=0x1001):
        self.device, self.vid, self.pid = device, vid, pid
        self.description, self.manufacturer, self.serial_number = "x", "y", "z"


def test_discovery_ranks_espressif_first(monkeypatch):
    monkeypatch.setattr(transport.list_ports, "comports",
                        lambda: [FakePort("/dev/ttyUSB0", 0x1A86), FakePort("/dev/ttyACM0", 0x303A),
                                 FakePort("/dev/ttyACM1", 0x1234)])
    monkeypatch.setattr(transport.glob, "glob", lambda pat: [])
    monkeypatch.setattr(transport, "_check_access", lambda p: (True, True, []))
    ports = transport.discover_ports()
    assert ports[0].device == "/dev/ttyACM0"
    assert any("unrecognised" in i for i in ports[-1].issues)


def test_permission_denied_reported(monkeypatch):
    monkeypatch.setattr(transport, "discover_ports",
                        lambda: [PortInfo("/dev/ttyACM0", 0x303A, issues=["no read/write permission"])])
    from nethunter_rf import client as client_mod
    monkeypatch.setattr(client_mod, "discover_ports", transport.discover_ports)
    with pytest.raises(TransportError) as e:
        RFBridgeClient.auto()
    assert "permission" in str(e.value) and e.value.hint


def test_open_missing_device():
    with pytest.raises(TransportError):
        SerialTransport("/dev/does-not-exist").open()


def test_serial_transport_with_pty():
    """Real pyserial transport over a pseudo-terminal pair."""
    import pty
    master, slave = pty.openpty()
    t = SerialTransport(os.ttyname(slave))
    t.open()
    try:
        os.write(master, b'{"type":"hello"}\npartial')
        assert t.read_line(1.0) == '{"type":"hello"}'
        t.write_line('{"cmd":"PING"}')
        assert os.read(master, 100).startswith(b'{"cmd":"PING"}\n')
    finally:
        t.close()
        os.close(master)
        os.close(slave)


def run(capsys, *argv):
    rc = cli.main(["--simulate", "--sim-interval", "0.05", *argv])
    return rc, capsys.readouterr().out


def test_cli_status_json(capsys):
    rc, out = run(capsys, "--json", "status")
    assert rc == 0 and json.loads(out)["chip"] == "SIM-CC1101"


def test_cli_global_flags_after_subcommand(capsys):
    rc, out = run(capsys, "version", "--json")
    assert rc == 0 and "host_version" in json.loads(out)


def test_cli_rx_and_analyze(capsys, tmp_path):
    cap = tmp_path / "cap.json"
    rc, _ = run(capsys, "rx", "-d", "1", "--freq", "868.35", "-o", str(cap))
    assert rc == 0 and cap.exists() and cap.with_suffix(".csv").exists()
    doc = json.loads(cap.read_text())
    assert doc["packets"] and doc["packets"][0]["frequency_hz"] == 868_350_000
    rc, out = run(capsys, "--json", "analyze", str(cap), "--length", "6")
    assert rc == 0 and json.loads(out)["packets"] == len(doc["packets"])


def test_cli_device_errors(capsys):
    assert cli.main(["--simulate", "set-freq", "2400"]) == 4
    assert cli.main(["--simulate", "tx-test"]) == 2
    assert cli.main(["--simulate", "tx-test", "--i-am-authorized", "-n", "2"]) == 0


def test_cli_raw(capsys):
    rc, out = run(capsys, "--json", "raw", "rssi_stream", '{"interval_ms": 100}')
    assert rc == 0 and json.loads(out)["interval_ms"] == 100
