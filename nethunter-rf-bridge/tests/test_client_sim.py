import time

import pytest

from nethunter_rf.analysis import Analyzer, Packet
from nethunter_rf.client import DeviceError, RFBridgeClient
from nethunter_rf.simulator import SimulatedTransport


@pytest.fixture
def client():
    c = RFBridgeClient(SimulatedTransport(seed=1, packet_interval=0.05)).connect()
    yield c
    c.close()


def test_version_and_info(client):
    v = client.get_version()
    assert v["fw"] == "nethunter-rf-bridge" and v["proto"] == 1
    info = client.device_info()
    assert info["simulation"] is True
    assert set(info["pins"]) == {"sck", "mosi", "miso", "cs", "gdo0", "gdo2"}


def test_frequency_validation(client):
    assert client.set_frequency(868.3)["frequency_hz"] == 868_300_000
    with pytest.raises(DeviceError) as e:
        client.set_frequency(2400)
    assert e.value.code == "UNSUPPORTED_FREQUENCY"
    with pytest.raises(DeviceError):
        client.set_frequency(370)  # gap between CC1101 bands


def test_config(client):
    st = client.set_config(modulation="GFSK", data_rate_kbps=38.4, sync_word="2dd4", crc=True)
    assert st["modulation"] == "GFSK" and st["sync_word"] == "2DD4" and st["crc"] is True
    with pytest.raises(DeviceError):
        client.set_config(data_rate_kbps=9999)
    with pytest.raises(DeviceError):
        client.set_config(modulation="QPSK")


def test_receive_stream(client):
    got = []
    client.subscribe(lambda ev: got.append(ev) if ev.get("type") == "packet" else None)
    client.start_receive()
    assert client.radio_status()["state"] == "receiving"
    deadline = time.time() + 3
    while len(got) < 5 and time.time() < deadline:
        time.sleep(0.02)
    client.stop_receive()
    assert len(got) >= 5
    p = Packet.from_event(got[0])
    assert p.data and p.frequency_hz == 433_920_000


def test_rssi(client):
    assert -120 < client.get_rssi() < 0
    rs = []
    client.subscribe(lambda ev: rs.append(ev) if ev.get("type") == "rssi" else None)
    client.rssi_stream(50)
    time.sleep(0.4)
    client.rssi_stream(0)
    assert len(rs) >= 3
    with pytest.raises(DeviceError):
        client.rssi_stream(5)


def test_tx_requires_authorization(client):
    with pytest.raises(DeviceError) as e:
        client.tx_test(1, False)
    assert e.value.code == "NOT_AUTHORIZED"
    assert client.tx_test(2, True)["sent"] == 2
    with pytest.raises(DeviceError):
        client.tx_test(50, True)


def test_unknown_command(client):
    with pytest.raises(DeviceError) as e:
        client.command("FLY")
    assert e.value.code == "UNKNOWN_COMMAND"


def test_no_radio_reported():
    c = RFBridgeClient(SimulatedTransport(radio_present=False)).connect()
    try:
        assert c.radio_status()["present"] is False
        with pytest.raises(DeviceError) as e:
            c.start_receive()
        assert e.value.code == "NO_RADIO"
    finally:
        c.close()


class _DeadTransport(SimulatedTransport):
    def write_line(self, text):  # device never answers
        pass


def test_timeout():
    c = RFBridgeClient(_DeadTransport(), timeout=0.3).connect(handshake=False)
    try:
        with pytest.raises(DeviceError) as e:
            c.ping()
        assert e.value.code == "TIMEOUT"
    finally:
        c.close()


def test_garbage_lines_tolerated(client):
    client.transport._out.put("ESP-ROM:esp32s3-20210327")  # boot chatter
    client.transport._out.put("[1, 2]")
    assert client.ping()
    time.sleep(0.2)
    assert client.state.bad_lines >= 2


def test_disconnect_fails_pending_and_emits_event():
    t = SimulatedTransport()
    c = RFBridgeClient(t).connect()
    evs = []
    c.subscribe(evs.append)
    t.connected = False
    time.sleep(0.3)
    assert any(e.get("type") == "connection" and e["connected"] is False for e in evs)
    c.close()
