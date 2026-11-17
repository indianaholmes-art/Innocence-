"""In-process device simulator speaking the exact firmware protocol.

Lets the host app, dashboard and tests run with no ESP32 or CC1101 attached.
"""
from __future__ import annotations

import json
import queue
import random
import threading
import time
from typing import Optional

BANDS = [(300_000_000, 348_000_000), (387_000_000, 464_000_000), (779_000_000, 928_000_000)]
MODULATIONS = {"2-FSK": "2-FSK", "FSK": "2-FSK", "2FSK": "2-FSK", "GFSK": "GFSK", "ASK/OOK": "ASK/OOK",
               "ASK": "ASK/OOK", "OOK": "ASK/OOK", "4-FSK": "4-FSK", "4FSK": "4-FSK", "MSK": "MSK"}


def freq_supported(hz: int) -> bool:
    return any(lo <= hz <= hi for lo, hi in BANDS)


class SimulatedTransport:
    """Drop-in replacement for SerialTransport."""

    port = "sim://cc1101"

    def __init__(self, seed: Optional[int] = None, packet_interval: float = 1.0, radio_present: bool = True):
        self.rng = random.Random(seed)
        self.packet_interval = packet_interval
        self.radio_present = radio_present
        self._out: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.connected = False
        self.last_error = None
        self.t0 = time.monotonic()
        self.seq = 0
        self.packets = 0
        self.rx = False
        self.rssi_ms = 0
        self.cfg = {"frequency_hz": 433_920_000, "modulation": "ASK/OOK", "data_rate_kbps": 4.8,
                    "deviation_khz": 47.6, "rx_bandwidth_khz": 203.0, "sync_word": "D391",
                    "sync_required": True, "crc": False, "max_packet_len": 61}

    # -- transport API --------------------------------------------------
    def open(self) -> None:
        self.connected = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="rfb-sim")
        self._thread.start()
        self._event("hello", {"fw": "nethunter-rf-bridge", "version": "1.0.0-sim", "proto": 1,
                              "radio": "SIM-CC1101", "radio_present": self.radio_present})

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self.connected = False

    def read_line(self, timeout: float = 0.1) -> Optional[str]:
        try:
            return self._out.get(timeout=timeout)
        except queue.Empty:
            return None

    def write_line(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not text.startswith("{"):
            text = json.dumps({"cmd": text})
        try:
            req = json.loads(text)
        except json.JSONDecodeError as e:
            return self._emit({"type": "response", "ok": False, "error": {"code": "BAD_JSON", "message": str(e)}})
        with self._lock:
            self._emit(self._dispatch(req))

    # -- internals -------------------------------------------------------
    def _t_us(self) -> int:
        return int((time.monotonic() - self.t0) * 1e6)

    def _emit(self, doc: dict) -> None:
        doc["seq"] = self.seq
        self.seq += 1
        self._out.put(json.dumps(doc, separators=(",", ":")))

    def _event(self, typ: str, data: dict) -> None:
        d = dict(data)
        d["type"] = typ
        d["t_us"] = self._t_us()
        self._emit(d)

    def _status(self) -> dict:
        return dict(self.cfg, chip="SIM-CC1101", present=self.radio_present,
                    state="receiving" if self.rx else "idle", packets=self.packets,
                    crc_errors=0, rssi_stream_ms=self.rssi_ms)

    def _rssi(self) -> float:
        return round(-105 + self.rng.random() * 8, 1)

    def _dispatch(self, req: dict) -> dict:
        cmd = req.get("cmd")
        args = req.get("args") or {}
        resp = {"type": "response", "cmd": cmd, "ok": True, "data": {}}
        if "id" in req:
            resp["id"] = req["id"]

        def fail(code, msg):
            resp.pop("data", None)
            resp["ok"] = False
            resp["error"] = {"code": code, "message": msg}
            return resp

        d = resp["data"]
        if cmd == "PING":
            d["pong"] = True
        elif cmd == "GET_VERSION":
            d.update(fw="nethunter-rf-bridge", version="1.0.0-sim", proto=1, build="simulator")
        elif cmd == "DEVICE_INFO":
            d.update(fw="nethunter-rf-bridge", version="1.0.0-sim", proto=1, board="SIMULATOR",
                     chip_model="ESP32-S3 (simulated)", chip_rev=0, mac="000000000000",
                     flash_bytes=8 << 20, psram_bytes=0, free_heap=300000,
                     uptime_ms=int((time.monotonic() - self.t0) * 1000), radio="SIM-CC1101",
                     radio_version=0x14, simulation=True,
                     pins={"sck": 12, "mosi": 11, "miso": 13, "cs": 10, "gdo0": 4, "gdo2": 5})
        elif cmd == "RADIO_STATUS":
            d.update(self._status())
        elif cmd == "SET_FREQUENCY":
            hz = args.get("hz") or (int(round(args["mhz"] * 1e6)) if "mhz" in args else None)
            if not hz:
                return fail("BAD_ARGS", "SET_FREQUENCY requires args.hz or args.mhz")
            if not freq_supported(int(hz)):
                return fail("UNSUPPORTED_FREQUENCY", "CC1101 bands: 300-348, 387-464, 779-928 MHz")
            self.cfg["frequency_hz"] = int(hz)
            d["frequency_hz"] = int(hz)
        elif cmd in ("SET_MODULATION", "SET_CONFIG"):
            new = dict(self.cfg)
            if "frequency_mhz" in args:
                new["frequency_hz"] = int(round(args["frequency_mhz"] * 1e6))
            if "frequency_hz" in args:
                new["frequency_hz"] = int(args["frequency_hz"])
            if "modulation" in args:
                m = MODULATIONS.get(str(args["modulation"]).upper())
                if not m:
                    return fail("BAD_ARGS", "unknown modulation")
                new["modulation"] = m
            for k, lo, hi in (("data_rate_kbps", 0.6, 500), ("deviation_khz", 1.5, 381),
                              ("rx_bandwidth_khz", 58, 812), ("max_packet_len", 1, 61)):
                if k in args:
                    if not lo <= args[k] <= hi:
                        return fail("BAD_ARGS", f"{k} must be {lo}..{hi}")
                    new[k] = args[k]
            for k in ("sync_required", "crc"):
                if k in args:
                    new[k] = bool(args[k])
            if "sync_word" in args:
                s = str(args["sync_word"])
                if len(s) != 4 or any(c not in "0123456789abcdefABCDEF" for c in s):
                    return fail("BAD_ARGS", "sync_word must be 4 hex digits")
                new["sync_word"] = s.upper()
            if not freq_supported(new["frequency_hz"]):
                return fail("UNSUPPORTED_FREQUENCY", "frequency outside CC1101 bands")
            self.cfg = new
            d.update(self._status())
        elif cmd == "START_RECEIVE":
            if not self.radio_present:
                return fail("NO_RADIO", "CC1101 not detected (simulated fault)")
            self.rx = True
            d["state"] = "receiving"
        elif cmd == "STOP_RECEIVE":
            self.rx = False
            d["state"] = "idle"
        elif cmd == "GET_RSSI":
            if not self.radio_present:
                return fail("NO_RADIO", "CC1101 not detected (simulated fault)")
            d.update(rssi_dbm=self._rssi(), frequency_hz=self.cfg["frequency_hz"])
        elif cmd == "RSSI_STREAM":
            ms = int(args.get("interval_ms", 0))
            if ms != 0 and not 20 <= ms <= 10000:
                return fail("BAD_ARGS", "interval_ms 0 (off) or 20..10000")
            self.rssi_ms = ms
            d["interval_ms"] = ms
        elif cmd == "RESET_RADIO":
            self.rx = False
            d.update(self._status())
        elif cmd == "TX_TEST":
            if not args.get("confirm_authorized"):
                return fail("NOT_AUTHORIZED", "set args.confirm_authorized=true")
            n = int(args.get("count", 1))
            if not 1 <= n <= 10:
                return fail("BAD_ARGS", "count must be 1..10")
            d["sent"] = n
        else:
            return fail("UNKNOWN_COMMAND", f"unknown cmd: {cmd}")
        return resp

    def _make_packet(self) -> dict:
        self.packets += 1
        kind = self.packets % 3
        if kind != 0:
            data = bytes([0xA5, 0x01, 0x42, 0x17, (self.packets // 10) & 0xFF, 0x5A])
        else:
            data = bytes(self.rng.getrandbits(8) for _ in range(self.rng.randint(4, 15)))
        return {"n": self.packets, "ts_us": self._t_us(), "frequency_hz": self.cfg["frequency_hz"],
                "modulation": self.cfg["modulation"], "len": len(data),
                "rssi_dbm": round(-60 - self.rng.random() * 30, 1), "lqi": self.rng.randint(0, 47),
                "crc_ok": True, "data": data.hex().upper()}

    def _run(self) -> None:
        next_pkt = time.monotonic() + self.packet_interval
        next_rssi = time.monotonic()
        next_hb = time.monotonic() + 5
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                if self.rx and now >= next_pkt:
                    self._event("packet", self._make_packet())
                    next_pkt = now + self.packet_interval * (0.5 + self.rng.random())
                if self.rssi_ms and now >= next_rssi:
                    self._event("rssi", {"rssi_dbm": self._rssi(), "frequency_hz": self.cfg["frequency_hz"]})
                    next_rssi = now + self.rssi_ms / 1000
                if now >= next_hb:
                    self._event("heartbeat", {"state": "receiving" if self.rx else "idle",
                                              "packets": self.packets, "free_heap": 300000})
                    next_hb = now + 5
            time.sleep(0.01)
