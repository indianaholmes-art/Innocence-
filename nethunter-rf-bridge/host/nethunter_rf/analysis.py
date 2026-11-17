"""RF analysis on CC1101 *packet metadata*.

Important: the CC1101 is a packet transceiver, not an SDR. It only delivers
bytes that matched the configured modulation, data rate, sync word and length
rules, plus a per-packet RSSI/LQI. It cannot record raw IQ / waveform data, so
nothing here reconstructs signals; all analysis operates on demodulated
packets and RSSI samples.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class Packet:
    n: int
    ts_us: int
    frequency_hz: int
    modulation: str
    data: bytes
    rssi_dbm: float
    lqi: int
    crc_ok: bool
    host_time: float = 0.0
    protocol: str = ""
    classification: str = ""

    @classmethod
    def from_event(cls, ev: dict, host_time: float = 0.0) -> "Packet":
        return cls(n=int(ev.get("n", 0)), ts_us=int(ev.get("ts_us", ev.get("t_us", 0))),
                   frequency_hz=int(ev.get("frequency_hz", 0)), modulation=str(ev.get("modulation", "")),
                   data=bytes.fromhex(ev.get("data", "")), rssi_dbm=float(ev.get("rssi_dbm", 0)),
                   lqi=int(ev.get("lqi", 0)), crc_ok=bool(ev.get("crc_ok", True)), host_time=host_time)

    @property
    def hex(self) -> str:
        return self.data.hex().upper()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["data"] = self.hex
        d["len"] = len(self.data)
        return d


def shannon_entropy(data: bytes) -> float:
    """Bits per byte, 0..8."""
    if not data:
        return 0.0
    c = Counter(data)
    n = len(data)
    return -sum(v / n * math.log2(v / n) for v in c.values())


def hamming_bits(a: bytes, b: bytes) -> int:
    diff = sum(bin(x ^ y).count("1") for x, y in zip(a, b))
    return diff + 8 * abs(len(a) - len(b))


def diff_positions(a: bytes, b: bytes) -> list[int]:
    return [i for i in range(max(len(a), len(b)))
            if i >= len(a) or i >= len(b) or a[i] != b[i]]


# ---------------------------------------------------------------- signatures
@dataclass
class Signature:
    """A documented/public frame layout to match against packet bytes."""
    name: str
    description: str = ""
    prefix: str = ""                    # hex prefix
    lengths: list = field(default_factory=list)   # allowed payload lengths ([] = any)
    modulations: list = field(default_factory=list)
    bands_mhz: list = field(default_factory=list)  # [[lo, hi], ...]
    reference: str = ""

    def matches(self, p: Packet) -> bool:
        if self.prefix and not p.hex.startswith(self.prefix.upper()):
            return False
        if self.lengths and len(p.data) not in self.lengths:
            return False
        if self.modulations and p.modulation not in self.modulations:
            return False
        if self.bands_mhz:
            mhz = p.frequency_hz / 1e6
            if not any(lo <= mhz <= hi for lo, hi in self.bands_mhz):
                return False
        return True


BUILTIN_SIGNATURES = [
    Signature("RFB lab test pattern", "Bridge TX_TEST frame 'RFB-TEST-nnn'",
              prefix="5246422D544553542D", lengths=[12], reference="docs/PROTOCOL.md#tx_test"),
    Signature("RFB simulator sensor frame", "Synthetic frame emitted by simulation mode",
              prefix="A5014217", lengths=[6], reference="host/nethunter_rf/simulator.py"),
    Signature("TI SmartRF CC1101 default packet test", "SmartRF Studio packet-TX test: incrementing seq",
              lengths=[], reference="TI SWRU275"),
]


def load_signatures(path: Optional[Path]) -> list[Signature]:
    sigs = list(BUILTIN_SIGNATURES[:2])
    if path and Path(path).exists():
        raw = json.loads(Path(path).read_text())
        for s in raw.get("signatures", []):
            sigs.append(Signature(**s))
    return sigs


# ------------------------------------------------------------------- analyzer
class Analyzer:
    def __init__(self, signatures: Optional[list[Signature]] = None, rssi_history: int = 600,
                 recent: int = 200):
        self.signatures = signatures if signatures is not None else load_signatures(None)
        self.rssi: deque = deque(maxlen=rssi_history)        # (host_time, dBm)
        self.packets: list[Packet] = []
        self.recent: deque = deque(maxlen=recent)
        self.by_payload: dict[bytes, list[Packet]] = defaultdict(list)

    # ingestion ---------------------------------------------------------
    def add_rssi(self, t: float, dbm: float) -> None:
        self.rssi.append((t, dbm))

    def add_packet(self, p: Packet) -> Packet:
        p.protocol = self.identify(p)
        self.by_payload[p.data].append(p)
        p.classification = self.classify(p)
        self.packets.append(p)
        self.recent.append(p)
        if p.rssi_dbm:
            self.add_rssi(p.host_time, p.rssi_dbm)
        return p

    # identification ------------------------------------------------------
    def identify(self, p: Packet) -> str:
        for s in self.signatures:
            if s.matches(p):
                return s.name
        return "unknown"

    def classify(self, p: Packet) -> str:
        """Heuristic class for packets without a known signature."""
        if p.protocol != "unknown":
            return "identified"
        if not p.crc_ok:
            return "crc-failed"
        repeats = len(self.by_payload.get(p.data, []))
        if repeats >= 2:
            return "repeating-fixed"
        # near-duplicate of a recent frame (counter / sensor value changes)
        for q in reversed(list(self.recent)[-50:]):
            if len(q.data) == len(p.data) and q.data != p.data and hamming_bits(q.data, p.data) <= 8:
                return "repeating-variable"
        ent = shannon_entropy(p.data)
        if len(p.data) >= 8 and ent > 0.85 * math.log2(min(256, len(p.data))):
            return "high-entropy (noise/encrypted)"
        if all(b in (0x00, 0xFF) for b in p.data):
            return "degenerate (all 0x00/0xFF)"
        return "structured-unknown"

    # reports -------------------------------------------------------------
    def rssi_stats(self) -> dict:
        vals = [v for _, v in self.rssi]
        if not vals:
            return {"samples": 0}
        return {"samples": len(vals), "min": min(vals), "max": max(vals),
                "mean": round(statistics.fmean(vals), 2),
                "stdev": round(statistics.pstdev(vals), 2), "last": vals[-1]}

    def repeated(self, min_count: int = 2) -> list[dict]:
        out = []
        for payload, ps in self.by_payload.items():
            if len(ps) >= min_count:
                out.append({"data": payload.hex().upper(), "count": len(ps),
                            "protocol": ps[0].protocol,
                            "timing": timing_stats([q.ts_us for q in ps]),
                            "rssi_mean": round(statistics.fmean(q.rssi_dbm for q in ps), 1)})
        return sorted(out, key=lambda d: d["count"], reverse=True)

    def compare(self, a: Packet, b: Packet) -> dict:
        return {"a": a.n, "b": b.n, "identical": a.data == b.data, "len_a": len(a.data),
                "len_b": len(b.data), "hamming_bits": hamming_bits(a.data, b.data),
                "diff_byte_positions": diff_positions(a.data, b.data),
                "dt_ms": round((b.ts_us - a.ts_us) / 1000, 3)}

    def variable_fields(self, length: int) -> dict:
        """For a group of same-length frames, which byte positions vary?"""
        group = [p.data for p in self.packets if len(p.data) == length]
        if len(group) < 2:
            return {"length": length, "frames": len(group), "constant": [], "variable": []}
        const, var = [], []
        for i in range(length):
            (const if len({g[i] for g in group}) == 1 else var).append(i)
        return {"length": length, "frames": len(group), "constant": const, "variable": var}

    def summary(self) -> dict:
        return {
            "packets": len(self.packets),
            "unique_payloads": len(self.by_payload),
            "protocols": dict(Counter(p.protocol for p in self.packets)),
            "classes": dict(Counter(p.classification for p in self.packets)),
            "lengths": dict(sorted(Counter(len(p.data) for p in self.packets).items())),
            "rssi": self.rssi_stats(),
            "timing_all": timing_stats([p.ts_us for p in self.packets]),
            "repeated": self.repeated()[:20],
            "note": "CC1101 packet-mode metadata only; no raw RF waveform/IQ is captured.",
        }


def timing_stats(ts_us: Iterable[int]) -> dict:
    ts = sorted(ts_us)
    if len(ts) < 2:
        return {"intervals": 0}
    iv = [(b - a) / 1000.0 for a, b in zip(ts, ts[1:])]
    d = {"intervals": len(iv), "min_ms": round(min(iv), 3), "max_ms": round(max(iv), 3),
         "mean_ms": round(statistics.fmean(iv), 3), "median_ms": round(statistics.median(iv), 3),
         "jitter_ms": round(statistics.pstdev(iv), 3)}
    # Periodicity: low coefficient of variation suggests a beacon/sensor period.
    d["periodic"] = d["mean_ms"] > 0 and d["jitter_ms"] / d["mean_ms"] < 0.1
    return d


def sparkline(values: list[float], width: int = 60, lo: float = -110, hi: float = -20) -> str:
    bars = "▁▂▃▄▅▆▇█"
    vals = values[-width:]
    out = []
    for v in vals:
        x = (min(max(v, lo), hi) - lo) / (hi - lo)
        out.append(bars[min(len(bars) - 1, int(x * len(bars)))])
    return "".join(out)
