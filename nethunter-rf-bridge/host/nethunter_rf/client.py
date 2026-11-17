"""High-level client for the RF Bridge JSON protocol (docs/PROTOCOL.md)."""
from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import PROTOCOL_VERSION
from .transport import SerialTransport, TransportError, discover_ports, wait_for_port

log = logging.getLogger("nethunter_rf")


class DeviceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class ConnectionState:
    connected: bool = False
    port: str = ""
    reconnects: int = 0
    last_rx: float = 0.0
    last_error: str = ""
    bad_lines: int = 0


class RFBridgeClient:
    """Thread-safe request/response + event stream client.

    `transport` may be a SerialTransport or SimulatedTransport.
    Events (packet/rssi/heartbeat/hello) are delivered to subscribers from a
    dispatcher thread.
    """

    def __init__(self, transport, auto_reconnect: bool = True, timeout: float = 3.0):
        self.transport = transport
        self.auto_reconnect = auto_reconnect and isinstance(transport, SerialTransport)
        self.timeout = timeout
        self.state = ConnectionState(port=getattr(transport, "port", ""))
        self._ids = itertools.count(1)
        self._pending: dict[int, dict] = {}
        self._cv = threading.Condition()
        self._subs: list[Callable[[dict], None]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.hello: Optional[dict] = None
        self.raw_log: list[str] = []  # bounded diagnostic trail
        self._receiving = False

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def auto(cls, port: Optional[str] = None, simulate: bool = False, **kw) -> "RFBridgeClient":
        if simulate:
            from .simulator import SimulatedTransport
            return cls(SimulatedTransport(**kw.pop("sim_kwargs", {})), **kw)
        if port is None:
            ports = discover_ports()
            if not ports:
                raise TransportError("No USB serial devices found",
                                     "Check the OTG cable/adapter and run `nethunter-rf doctor`.")
            usable = [p for p in ports if p.readable and p.writable]
            if not usable:
                raise TransportError(
                    "Serial device(s) found but none accessible: "
                    + "; ".join(f"{p.device}: {', '.join(p.issues)}" for p in ports),
                    "See docs/USB_TROUBLESHOOTING.md#permissions")
            port = usable[0].device
        return cls(SerialTransport(port), **kw)

    def connect(self, handshake: bool = True) -> "RFBridgeClient":
        self.transport.open()
        self.state.connected = True
        self.state.port = getattr(self.transport, "port", "")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="rfb-dispatch")
        self._thread.start()
        if handshake:
            info = self.get_version()
            if info.get("proto") != PROTOCOL_VERSION:
                log.warning("Protocol mismatch: device %s, host %s", info.get("proto"), PROTOCOL_VERSION)
            if info.get("fw") != "nethunter-rf-bridge":
                raise TransportError(f"{self.state.port} answered but is not an RF Bridge ({info.get('fw')})")
        return self

    def close(self) -> None:
        try:
            if self.state.connected and self._receiving:
                self.stop_receive()
        except Exception:
            pass
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
        self.transport.close()
        self.state.connected = False

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        self._subs.append(fn)

    # -- core loop -----------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.transport.connected:
                self.state.connected = False
                self.state.last_error = getattr(self.transport, "last_error", "") or "disconnected"
                self._fail_pending("DISCONNECTED", self.state.last_error)
                self._publish({"type": "connection", "connected": False, "error": self.state.last_error})
                if not self.auto_reconnect or not self._reconnect():
                    return
                continue
            line = self.transport.read_line(timeout=0.1)
            if line is None:
                continue
            self.state.last_rx = time.time()
            self.raw_log.append(line)
            if len(self.raw_log) > 2000:
                del self.raw_log[:500]
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Boot ROM chatter, ESP-IDF logs etc. are tolerated.
                self.state.bad_lines += 1
                continue
            if not isinstance(msg, dict):
                self.state.bad_lines += 1
                continue
            if msg.get("type") == "response" and "id" in msg:
                with self._cv:
                    if msg["id"] in self._pending:
                        self._pending[msg["id"]] = msg
                        self._cv.notify_all()
                continue
            if msg.get("type") == "hello":
                self.hello = msg
            self._publish(msg)

    def _publish(self, msg: dict) -> None:
        for fn in list(self._subs):
            try:
                fn(msg)
            except Exception:  # never let a UI bug kill the link
                log.exception("subscriber failed")

    def _fail_pending(self, code: str, message: str) -> None:
        with self._cv:
            for k, v in self._pending.items():
                if v is None:
                    self._pending[k] = {"ok": False, "error": {"code": code, "message": message}}
            self._cv.notify_all()

    def _reconnect(self) -> bool:
        port = self.state.port
        self.transport.close()
        for attempt in range(1, 61):
            if self._stop.is_set():
                return False
            p = wait_for_port(lambda p: p.device == port, timeout=1.0) or wait_for_port(timeout=1.0)
            if p is None:
                continue
            try:
                self.transport = SerialTransport(p.device, self.transport.baudrate)
                self.transport.open()
            except TransportError as e:
                self.state.last_error = str(e)
                continue
            self.state.connected = True
            self.state.port = p.device
            self.state.reconnects += 1
            self._publish({"type": "connection", "connected": True, "port": p.device, "attempt": attempt})
            if self._receiving:  # restore state after a USB glitch / board reset
                threading.Thread(target=self._restore, daemon=True).start()
            return True
        return False

    def _restore(self) -> None:
        try:
            time.sleep(0.5)
            self.start_receive()
        except Exception as e:
            log.warning("restore after reconnect failed: %s", e)

    # -- commands --------------------------------------------------------------
    def command(self, cmd: str, args: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        if not self.state.connected:
            raise TransportError("not connected")
        rid = next(self._ids)
        req = {"id": rid, "cmd": cmd}
        if args:
            req["args"] = args
        with self._cv:
            self._pending[rid] = None
        self.transport.write_line(json.dumps(req, separators=(",", ":")))
        deadline = time.monotonic() + (timeout or self.timeout)
        with self._cv:
            while self._pending[rid] is None:
                left = deadline - time.monotonic()
                if left <= 0:
                    del self._pending[rid]
                    raise DeviceError("TIMEOUT", f"no response to {cmd} within {timeout or self.timeout}s")
                self._cv.wait(left)
            resp = self._pending.pop(rid)
        if not resp.get("ok"):
            err = resp.get("error", {})
            raise DeviceError(err.get("code", "ERROR"), err.get("message", ""))
        return resp.get("data", {})

    def ping(self) -> bool:
        return bool(self.command("PING").get("pong"))

    def get_version(self) -> dict:
        return self.command("GET_VERSION")

    def device_info(self) -> dict:
        return self.command("DEVICE_INFO")

    def radio_status(self) -> dict:
        return self.command("RADIO_STATUS")

    def set_frequency(self, mhz: float) -> dict:
        return self.command("SET_FREQUENCY", {"hz": int(round(mhz * 1e6))})

    def set_config(self, **cfg) -> dict:
        return self.command("SET_CONFIG", {k: v for k, v in cfg.items() if v is not None})

    def start_receive(self) -> dict:
        r = self.command("START_RECEIVE")
        self._receiving = True
        return r

    def stop_receive(self) -> dict:
        r = self.command("STOP_RECEIVE")
        self._receiving = False
        return r

    def get_rssi(self) -> float:
        return float(self.command("GET_RSSI")["rssi_dbm"])

    def rssi_stream(self, interval_ms: int) -> dict:
        return self.command("RSSI_STREAM", {"interval_ms": int(interval_ms)})

    def reset_radio(self) -> dict:
        return self.command("RESET_RADIO", timeout=5)

    def tx_test(self, count: int, confirm_authorized: bool) -> dict:
        return self.command("TX_TEST", {"count": count, "confirm_authorized": confirm_authorized}, timeout=10)
