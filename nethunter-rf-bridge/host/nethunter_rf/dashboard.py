"""Interactive Rich terminal dashboard.

Keys:  r start/stop receive   f set frequency   m cycle modulation
       s save capture         c clear           d diagnostics   q quit
"""
from __future__ import annotations

import os
import select
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .analysis import Analyzer, Packet, sparkline
from .client import DeviceError, RFBridgeClient
from .export import default_path, export_csv, export_diagnostics, export_json

MODULATIONS = ["ASK/OOK", "2-FSK", "GFSK", "4-FSK", "MSK"]


class _RawTerminal:
    """Non-blocking single-key input on POSIX terminals (Termux/NetHunter)."""

    def __init__(self):
        self.enabled = sys.stdin.isatty() and os.name == "posix"
        self.old = None

    def __enter__(self):
        if self.enabled:
            import termios
            import tty
            self.old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *a):
        if self.enabled and self.old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)

    def key(self) -> Optional[str]:
        if not self.enabled:
            return None
        r, _, _ = select.select([sys.stdin], [], [], 0)
        return sys.stdin.read(1) if r else None

    def line(self, prompt: str) -> str:
        if self.enabled:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)
        try:
            return input(prompt)
        finally:
            if self.enabled:
                import tty
                tty.setcbreak(sys.stdin.fileno())


class Dashboard:
    def __init__(self, client: RFBridgeClient, analyzer: Analyzer, out_dir: Path,
                 rssi_interval_ms: int = 200, console: Optional[Console] = None):
        self.c = client
        self.a = analyzer
        self.out_dir = out_dir
        self.rssi_interval_ms = rssi_interval_ms
        self.console = console or Console()
        self.info: dict = {}
        self.status: dict = {}
        self.receiving = False
        self.message = "Press [r] to start receiving, [q] to quit"
        self.lock = threading.Lock()
        self.last_hb = 0.0
        self.link = "connected"
        client.subscribe(self._on_event)

    # events -----------------------------------------------------------------
    def _on_event(self, ev: dict) -> None:
        now = time.time()
        with self.lock:
            t = ev.get("type")
            if t == "packet":
                self.a.add_packet(Packet.from_event(ev, now))
            elif t == "rssi":
                self.a.add_rssi(now, float(ev["rssi_dbm"]))
            elif t == "heartbeat":
                self.last_hb = now
            elif t == "connection":
                self.link = "connected" if ev.get("connected") else f"LOST ({ev.get('error', '')}) - reconnecting…"
                self.message = f"Link: {self.link}"

    def refresh_status(self) -> None:
        try:
            self.status = self.c.radio_status()
            self.receiving = self.status.get("state") == "receiving"
        except Exception as e:
            self.message = f"status error: {e}"

    # rendering -----------------------------------------------------------------
    def _hw_panel(self) -> Panel:
        t = Table.grid(padding=(0, 1))
        t.add_column(style="bold cyan")
        t.add_column()
        i, s = self.info, self.status
        link_style = "green" if self.c.state.connected else "red"
        t.add_row("Link", Text(f"{self.link} {self.c.state.port}", style=link_style))
        t.add_row("Board", f"{i.get('board', '?')} ({i.get('chip_model', '?')})")
        t.add_row("Firmware", f"{i.get('fw', '?')} v{i.get('version', '?')} proto {i.get('proto', '?')}")
        t.add_row("Radio", f"{s.get('chip', '?')} present={s.get('present')}"
                  + ("  [yellow]SIMULATION[/]" if i.get("simulation") else ""))
        st = s.get("state", "?")
        t.add_row("State", Text(st, style="bold green" if st == "receiving" else "yellow"))
        t.add_row("Frequency", f"{s.get('frequency_hz', 0) / 1e6:.4f} MHz")
        t.add_row("Modulation", f"{s.get('modulation', '?')}  {s.get('data_rate_kbps', '?')} kBaud  "
                  f"BW {s.get('rx_bandwidth_khz', '?')} kHz  dev {s.get('deviation_khz', '?')} kHz")
        t.add_row("Sync/CRC", f"{s.get('sync_word', '?')} req={s.get('sync_required')} crc={s.get('crc')}")
        if s.get("last_error"):
            t.add_row("Radio msg", Text(str(s["last_error"]), style="red"))
        return Panel(t, title="Hardware / Radio", border_style="cyan")

    def _rssi_panel(self) -> Panel:
        vals = [v for _, v in self.a.rssi]
        st = self.a.rssi_stats()
        last = f"{vals[-1]:.1f} dBm" if vals else "-"
        txt = Text()
        txt.append(f"Live RSSI: {last}   ", style="bold")
        if st.get("samples"):
            txt.append(f"min {st['min']:.1f}  max {st['max']:.1f}  mean {st['mean']:.1f}\n")
        txt.append(sparkline(vals, width=max(20, self.console.width - 8)), style="green")
        return Panel(txt, title="Signal strength history (-110..-20 dBm)", border_style="green")

    def _packets_panel(self) -> Panel:
        t = Table(expand=True, show_edge=False, pad_edge=False)
        for col, kw in (("#", {"justify": "right"}), ("t (ms)", {"justify": "right"}), ("len", {"justify": "right"}),
                        ("RSSI", {"justify": "right"}), ("LQI", {"justify": "right"}), ("CRC", {}),
                        ("protocol / class", {"overflow": "ellipsis", "no_wrap": True, "max_width": 22}), ("data", {"overflow": "ellipsis", "no_wrap": True})):
            t.add_column(col, **kw)
        rows = list(self.a.recent)[-12:]
        for p in reversed(rows):
            t.add_row(str(p.n), f"{p.ts_us / 1000:.0f}", str(len(p.data)), f"{p.rssi_dbm:.1f}", str(p.lqi),
                      "ok" if p.crc_ok else "[red]bad[/]",
                      p.protocol if p.protocol != "unknown" else f"[dim]{p.classification}[/]", p.hex)
        return Panel(t, title=f"Recent packets ({len(self.a.packets)} total, "
                              f"{len(self.a.by_payload)} unique)", border_style="magenta")

    def _footer(self) -> Panel:
        keys = r"\[r] rx on/off  \[f] freq  \[m] modulation  \[s] save  \[c] clear  \[d] diag  \[q] quit"
        return Panel(Text.from_markup(f"{keys}\n[bold]{self.message}[/]"), border_style="white")

    def render(self):
        lay = Layout()
        lay.split_column(Layout(self._hw_panel(), size=11), Layout(self._rssi_panel(), size=5),
                         Layout(self._packets_panel()), Layout(self._footer(), size=4))
        return lay

    # actions -------------------------------------------------------------------
    def toggle_rx(self):
        try:
            if self.receiving:
                self.c.stop_receive()
                self.message = "Receive stopped"
            else:
                self.c.start_receive()
                self.message = "Receiving (packet mode: only frames matching sync/modulation are shown)"
        except DeviceError as e:
            self.message = f"[red]{e}[/]"
        self.refresh_status()

    def cycle_modulation(self):
        cur = self.status.get("modulation", "ASK/OOK")
        nxt = MODULATIONS[(MODULATIONS.index(cur) + 1) % len(MODULATIONS)] if cur in MODULATIONS else MODULATIONS[0]
        try:
            self.c.set_config(modulation=nxt)
            self.message = f"Modulation → {nxt}"
        except DeviceError as e:
            self.message = f"[red]{e}[/]"
        self.refresh_status()

    def set_freq(self, term: _RawTerminal, live: Live):
        live.stop()
        try:
            s = term.line("Frequency MHz (300-348, 387-464, 779-928): ").strip()
            if s:
                self.c.set_frequency(float(s))
                self.message = f"Frequency → {float(s):.4f} MHz"
        except (ValueError, DeviceError) as e:
            self.message = f"[red]{e}[/]"
        finally:
            live.start()
        self.refresh_status()

    def save(self):
        with self.lock:
            pk = list(self.a.packets)
        meta = {"device": self.info, "radio": self.status}
        j = export_json(default_path(self.out_dir, "capture", "json"), pk, meta, self.a)
        c = export_csv(j.with_suffix(".csv"), pk)
        self.message = f"Saved {len(pk)} packets → {j} , {c.name}"

    def run(self) -> None:
        try:
            self.info = self.c.device_info()
        except Exception as e:
            self.message = f"DEVICE_INFO failed: {e}"
        self.refresh_status()
        try:
            self.c.rssi_stream(self.rssi_interval_ms)
        except Exception as e:
            self.message = f"RSSI stream unavailable: {e}"
        last_status = 0.0
        with _RawTerminal() as term, Live(self.render(), console=self.console, refresh_per_second=8,
                                          screen=True) as live:
            if not term.enabled:
                self.message = "stdin is not a TTY: keys disabled (Ctrl-C to quit)"
            while True:
                k = term.key()
                if k == "q":
                    break
                elif k == "r":
                    self.toggle_rx()
                elif k == "m":
                    self.cycle_modulation()
                elif k == "f":
                    self.set_freq(term, live)
                elif k == "s":
                    self.save()
                elif k == "c":
                    with self.lock:
                        self.a.__init__(self.a.signatures)
                    self.message = "Cleared"
                elif k == "d":
                    p = export_diagnostics(default_path(self.out_dir, "diagnostics", "json"), self.c)
                    self.message = f"Diagnostics → {p}"
                if time.time() - last_status > 2 and self.c.state.connected:
                    last_status = time.time()
                    self.refresh_status()
                with self.lock:
                    live.update(self.render())
                time.sleep(0.05)
        try:
            self.c.rssi_stream(0)
        except Exception:
            pass
