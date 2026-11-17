"""Command-line entry point: `nethunter-rf <command>` / `python -m nethunter_rf`."""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import __version__
from .analysis import Analyzer, Packet, load_signatures
from .client import DeviceError, RFBridgeClient
from .config import load_config
from .export import default_path, export_csv, export_diagnostics, export_json, load_capture
from .transport import TransportError, discover_ports, usb_environment_report

console = Console(stderr=False)
err = Console(stderr=True)


def _client(args) -> RFBridgeClient:
    sim_kwargs = {"packet_interval": args.sim_interval} if args.simulate else {}
    c = RFBridgeClient.auto(port=args.port, simulate=args.simulate, timeout=args.timeout,
                            **({"sim_kwargs": sim_kwargs} if args.simulate else {}))
    return c.connect()


def _out(args, data) -> None:
    if args.json:
        print(json.dumps(data, indent=2, default=str))
    elif isinstance(data, dict):
        t = Table(show_header=False, box=None)
        for k, v in data.items():
            t.add_row(f"[cyan]{k}[/]", json.dumps(v) if isinstance(v, (dict, list)) else str(v))
        console.print(t)
    else:
        console.print(data)


def _apply_config(c: RFBridgeClient, cfg: dict) -> None:
    radio = cfg.get("radio", {})
    if radio:
        c.set_config(**radio)


# ------------------------------------------------------------------ commands
def cmd_list(args) -> int:
    ports = discover_ports()
    if args.json:
        _out(args, [p.to_dict() for p in ports])
        return 0
    if not ports:
        err.print("[yellow]No USB serial devices found.[/] Run `nethunter-rf doctor`.")
        return 1
    t = Table("device", "VID:PID", "vendor", "description", "access", "issues")
    for p in ports:
        vp = f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else "?"
        acc = "[green]rw[/]" if p.readable and p.writable else "[red]denied[/]"
        t.add_row(p.device, vp, p.vendor, p.description, acc, "; ".join(p.issues))
    console.print(t)
    return 0


def cmd_doctor(args) -> int:
    rep = usb_environment_report()
    rep["ports"] = [p.to_dict() for p in discover_ports()]
    try:
        import rich  # noqa: F401
        rep["rich"] = True
    except ImportError:
        rep["rich"] = False
    ok = bool(rep["ports"]) and any(p["readable"] and p["writable"] for p in rep["ports"])
    if not args.simulate and ok:
        try:
            with RFBridgeClient.auto(port=args.port, timeout=args.timeout) as c:
                rep["device"] = c.device_info()
                rep["radio"] = c.radio_status()
        except (TransportError, DeviceError) as e:
            rep["device_error"] = str(e)
            ok = False
    _out(args, rep)
    if not args.json:
        console.print("[green]READY[/]" if ok else "[red]NOT READY[/] - see docs/USB_TROUBLESHOOTING.md")
    return 0 if ok else 2


def cmd_info(args) -> int:
    with _client(args) as c:
        _out(args, c.device_info())
    return 0


def cmd_version(args) -> int:
    with _client(args) as c:
        d = c.get_version()
        d["host_version"] = __version__
        _out(args, d)
    return 0


def cmd_status(args) -> int:
    with _client(args) as c:
        _out(args, c.radio_status())
    return 0


def cmd_set_freq(args) -> int:
    with _client(args) as c:
        _out(args, c.set_frequency(args.mhz))
    return 0


def cmd_config(args) -> int:
    with _client(args) as c:
        cfg = {}
        if args.file:
            cfg = load_config(Path(args.file)).get("radio", {})
        cli = {"frequency_mhz": args.mhz, "modulation": args.modulation, "data_rate_kbps": args.rate,
               "deviation_khz": args.deviation, "rx_bandwidth_khz": args.bandwidth, "sync_word": args.sync,
               "max_packet_len": args.max_len}
        if args.crc is not None:
            cli["crc"] = args.crc == "on"
        if args.sync_required is not None:
            cli["sync_required"] = args.sync_required == "on"
        cfg.update({k: v for k, v in cli.items() if v is not None})
        _out(args, c.set_config(**cfg) if cfg else c.radio_status())
    return 0


def cmd_rssi(args) -> int:
    with _client(args) as c:
        if args.freq:
            c.set_frequency(args.freq)
        vals = []
        for _ in range(args.count):
            v = c.get_rssi()
            vals.append(v)
            if args.json:
                print(json.dumps({"t": time.time(), "rssi_dbm": v}))
            else:
                bar = "#" * max(0, int((v + 110) / 2))
                console.print(f"{v:7.1f} dBm {bar}")
            time.sleep(args.interval)
        if not args.json and vals:
            console.print(f"min {min(vals):.1f}  max {max(vals):.1f}  mean {sum(vals) / len(vals):.1f} dBm")
    return 0


def cmd_rx(args) -> int:
    cfg = load_config(Path(args.config)) if args.config else {}
    an = Analyzer(load_signatures(Path(args.signatures) if args.signatures else None))
    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *a: stop.update(flag=True))
    with _client(args) as c:
        _apply_config(c, cfg)
        if args.freq:
            c.set_frequency(args.freq)
        if args.modulation:
            c.set_config(modulation=args.modulation)
        status = c.radio_status()

        def on_ev(ev):
            if ev.get("type") == "packet":
                p = an.add_packet(Packet.from_event(ev, time.time()))
                if args.json:
                    try:
                        print(json.dumps(p.to_dict()), flush=True)
                    except BrokenPipeError:  # e.g. piped into `head`
                        stop["flag"] = True
                else:
                    console.print(f"[bold]#{p.n:<5}[/] {p.ts_us / 1000:10.1f}ms len={len(p.data):<3} "
                                  f"rssi={p.rssi_dbm:6.1f} lqi={p.lqi:<3} {p.protocol}/{p.classification} "
                                  f"[green]{p.hex}[/]")
            elif ev.get("type") == "connection":
                err.print(f"[yellow]link event: {ev}[/]")

        c.subscribe(on_ev)
        if not args.json:
            console.print(f"Receiving on {status['frequency_hz'] / 1e6:.4f} MHz {status['modulation']} "
                          f"(packet mode; Ctrl-C to stop)")
        c.start_receive()
        t_end = time.time() + args.duration if args.duration else None
        while not stop["flag"] and (t_end is None or time.time() < t_end) and \
                (not args.max_packets or len(an.packets) < args.max_packets):
            time.sleep(0.1)
        c.stop_receive()
        out_dir = Path(args.out_dir)
        meta = {"radio": status, "device": c.get_version()}
        if args.save or args.out_dir != ".":
            j = export_json(Path(args.save) if args.save else default_path(out_dir, "capture", "json"),
                            an.packets, meta, an)
            cpath = export_csv(j.with_suffix(".csv"), an.packets)
            err.print(f"Saved {len(an.packets)} packets → {j} and {cpath}")
    if not args.json:
        _out(args, {k: v for k, v in an.summary().items() if k != "repeated"})
    return 0


def cmd_analyze(args) -> int:
    an = Analyzer(load_signatures(Path(args.signatures) if args.signatures else None))
    for p in load_capture(Path(args.capture)):
        an.add_packet(p)
    summ = an.summary()
    if args.length:
        summ["variable_fields"] = an.variable_fields(args.length)
    if args.compare:
        a, b = args.compare
        idx = {p.n: p for p in an.packets}
        if a not in idx or b not in idx:
            err.print("packet number not in capture")
            return 1
        summ["comparison"] = an.compare(idx[a], idx[b])
    _out(args, summ)
    return 0


def cmd_dashboard(args) -> int:
    from .dashboard import Dashboard
    cfg = load_config(Path(args.config)) if args.config else {}
    an = Analyzer(load_signatures(Path(args.signatures) if args.signatures else None))
    with _client(args) as c:
        _apply_config(c, cfg)
        Dashboard(c, an, Path(args.out_dir), rssi_interval_ms=args.rssi_ms).run()
    return 0


def cmd_diag(args) -> int:
    path = Path(args.output) if args.output else default_path(Path(args.out_dir), "diagnostics", "json")
    c = None
    try:
        c = _client(args)
    except (TransportError, DeviceError) as e:
        err.print(f"[yellow]device unavailable ({e}); writing host-only diagnostics[/]")
    try:
        export_diagnostics(path, c)
    finally:
        if c:
            c.close()
    console.print(f"Diagnostics written to {path}")
    return 0


def cmd_tx_test(args) -> int:
    if not args.i_am_authorized:
        err.print("[red]Refusing:[/] pass --i-am-authorized to confirm this is a controlled lab test on a "
                  "frequency/power you are permitted to use. Payload is a fixed 'RFB-TEST-nnn' pattern.")
        return 2
    with _client(args) as c:
        _out(args, c.tx_test(args.count, True))
    return 0


def cmd_raw(args) -> int:
    with _client(args) as c:
        _out(args, c.command(args.cmd.upper(), json.loads(args.args) if args.args else None))
    return 0


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nethunter-rf", description="NetHunter RF Bridge (ESP32-S3 + CC1101) host tool")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-p", "--port", help="serial device (default: auto-detect)")
    p.add_argument("--simulate", action="store_true", help="use the built-in hardware simulator")
    p.add_argument("--sim-interval", type=float, default=1.0, help=argparse.SUPPRESS)
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.add_argument("--timeout", type=float, default=3.0, help="command timeout seconds")
    p.add_argument("-v", "--verbose", action="store_true")
    # Allow global options after the subcommand too (`nethunter-rf rx --json`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-p", "--port", default=argparse.SUPPRESS)
    common.add_argument("--simulate", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--sim-interval", type=float, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--timeout", type=float, default=argparse.SUPPRESS)
    common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="command", required=True)
    _orig = sub.add_parser
    sub.add_parser = lambda *a, **k: _orig(*a, parents=[common], **k)

    sub.add_parser("list", help="list USB serial devices").set_defaults(fn=cmd_list)
    sub.add_parser("doctor", help="check USB/OTG/permissions setup").set_defaults(fn=cmd_doctor)
    sub.add_parser("info", help="DEVICE_INFO").set_defaults(fn=cmd_info)
    sub.add_parser("version", help="GET_VERSION").set_defaults(fn=cmd_version)
    sub.add_parser("status", help="RADIO_STATUS").set_defaults(fn=cmd_status)

    s = sub.add_parser("set-freq", help="SET_FREQUENCY")
    s.add_argument("mhz", type=float)
    s.set_defaults(fn=cmd_set_freq)

    s = sub.add_parser("config", help="SET_CONFIG from flags and/or a config file")
    s.add_argument("-f", "--file")
    s.add_argument("--mhz", type=float)
    s.add_argument("--modulation", choices=["ASK/OOK", "OOK", "2-FSK", "GFSK", "4-FSK", "MSK"])
    s.add_argument("--rate", type=float, help="data rate kBaud")
    s.add_argument("--deviation", type=float, help="FSK deviation kHz")
    s.add_argument("--bandwidth", type=float, help="RX filter bandwidth kHz")
    s.add_argument("--sync", help="sync word, 4 hex digits")
    s.add_argument("--sync-required", choices=["on", "off"])
    s.add_argument("--crc", choices=["on", "off"])
    s.add_argument("--max-len", type=int)
    s.set_defaults(fn=cmd_config)

    s = sub.add_parser("rssi", help="poll RSSI")
    s.add_argument("-n", "--count", type=int, default=20)
    s.add_argument("-i", "--interval", type=float, default=0.25)
    s.add_argument("--freq", type=float, help="MHz")
    s.set_defaults(fn=cmd_rssi)

    s = sub.add_parser("rx", help="receive packets and optionally save capture")
    s.add_argument("--freq", type=float, help="MHz")
    s.add_argument("--modulation")
    s.add_argument("-d", "--duration", type=float, help="seconds (default: until Ctrl-C)")
    s.add_argument("--max-packets", type=int)
    s.add_argument("-c", "--config", help="JSON config file")
    s.add_argument("--signatures", help="protocol signature JSON")
    s.add_argument("-o", "--save", help="capture .json path (CSV written alongside)")
    s.add_argument("--out-dir", default=".", help="directory for auto-named captures")
    s.set_defaults(fn=cmd_rx)

    s = sub.add_parser("analyze", help="offline analysis of a saved capture")
    s.add_argument("capture")
    s.add_argument("--signatures")
    s.add_argument("--length", type=int, help="show constant/variable byte fields for this frame length")
    s.add_argument("--compare", type=int, nargs=2, metavar=("N1", "N2"))
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("dashboard", help="interactive terminal dashboard")
    s.add_argument("-c", "--config")
    s.add_argument("--signatures")
    s.add_argument("--out-dir", default=str(Path.home() / "rf-captures"))
    s.add_argument("--rssi-ms", type=int, default=200)
    s.set_defaults(fn=cmd_dashboard)

    s = sub.add_parser("diag", help="export a diagnostic log bundle")
    s.add_argument("-o", "--output")
    s.add_argument("--out-dir", default=".")
    s.set_defaults(fn=cmd_diag)

    s = sub.add_parser("tx-test", help="send fixed lab test frames (authorized use only)")
    s.add_argument("-n", "--count", type=int, default=1)
    s.add_argument("--i-am-authorized", action="store_true")
    s.set_defaults(fn=cmd_tx_test)

    s = sub.add_parser("raw", help="send a raw protocol command")
    s.add_argument("cmd")
    s.add_argument("args", nargs="?", help="JSON args object")
    s.set_defaults(fn=cmd_raw)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    try:
        return args.fn(args)
    except TransportError as e:
        err.print(f"[red]Connection error:[/] {e}")
        if e.hint:
            err.print(f"[yellow]Hint:[/] {e.hint}")
        return 3
    except DeviceError as e:
        err.print(f"[red]Device error:[/] {e}")
        return 4
    except KeyboardInterrupt:
        return 130
