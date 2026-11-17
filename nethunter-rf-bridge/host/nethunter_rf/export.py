"""Capture export (JSON / CSV) and diagnostic bundles."""
from __future__ import annotations

import csv
import json
import platform
import sys
import time
from pathlib import Path
from typing import Optional

from . import __version__
from .analysis import Analyzer, Packet

CSV_FIELDS = ["n", "host_time", "ts_us", "frequency_hz", "modulation", "len", "rssi_dbm", "lqi",
              "crc_ok", "protocol", "classification", "data"]


def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def default_path(directory: Path, stem: str, ext: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{stem}-{_ts()}.{ext}"


def export_json(path: Path, packets: list[Packet], meta: dict, analyzer: Optional[Analyzer] = None) -> Path:
    doc = {"format": "nethunter-rf-capture", "format_version": 1, "host_version": __version__,
           "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "meta": meta,
           "capture_type": "cc1101-packet-metadata (not raw RF)",
           "packets": [p.to_dict() for p in packets]}
    if analyzer is not None:
        doc["analysis"] = analyzer.summary()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2))
    return path


def export_csv(path: Path, packets: list[Packet]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for p in packets:
            w.writerow(p.to_dict())
    return path


def load_capture(path: Path) -> list[Packet]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        out = []
        with path.open() as f:
            for r in csv.DictReader(f):
                out.append(Packet(n=int(r["n"]), ts_us=int(r["ts_us"]), frequency_hz=int(r["frequency_hz"]),
                                  modulation=r["modulation"], data=bytes.fromhex(r["data"]),
                                  rssi_dbm=float(r["rssi_dbm"]), lqi=int(r["lqi"]),
                                  crc_ok=r["crc_ok"] in ("True", "true", "1"),
                                  host_time=float(r["host_time"] or 0)))
        return out
    doc = json.loads(path.read_text())
    if doc.get("format") != "nethunter-rf-capture":
        raise ValueError(f"{path} is not a nethunter-rf capture")
    return [Packet(n=d["n"], ts_us=d["ts_us"], frequency_hz=d["frequency_hz"], modulation=d["modulation"],
                   data=bytes.fromhex(d["data"]), rssi_dbm=d["rssi_dbm"], lqi=d["lqi"], crc_ok=d["crc_ok"],
                   host_time=d.get("host_time", 0.0)) for d in doc["packets"]]


def export_diagnostics(path: Path, client=None, extra: Optional[dict] = None) -> Path:
    from .transport import discover_ports, usb_environment_report
    diag = {"created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host_version": __version__,
            "python": sys.version, "platform": platform.platform(),
            "usb": usb_environment_report(), "ports": [p.to_dict() for p in discover_ports()]}
    if client is not None:
        st = client.state
        diag["connection"] = {"connected": st.connected, "port": st.port, "reconnects": st.reconnects,
                              "last_error": st.last_error, "bad_lines": st.bad_lines}
        for name, fn in (("device_info", client.device_info), ("radio_status", client.radio_status)):
            try:
                diag[name] = fn()
            except Exception as e:
                diag[name] = {"error": str(e)}
        diag["raw_tail"] = client.raw_log[-200:]
    if extra:
        diag.update(extra)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(diag, indent=2, default=str))
    return path
