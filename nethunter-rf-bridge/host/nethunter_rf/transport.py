"""USB serial discovery and line-oriented transport.

No root is assumed. Missing permissions and unsupported devices are reported
as structured diagnostics rather than tracebacks.
"""
from __future__ import annotations

import glob
import os
import queue
import stat
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - reported by `doctor`
    serial = None
    list_ports = None

# Known USB vendor IDs for ESP32 boards and their USB-UART bridges.
KNOWN_VIDS = {
    0x303A: "Espressif (native USB CDC / USB-Serial-JTAG)",
    0x10C4: "Silicon Labs CP210x bridge",
    0x1A86: "WCH CH340/CH343 bridge",
    0x0403: "FTDI bridge",
}
ESPRESSIF_VID = 0x303A


class TransportError(Exception):
    """Raised for unrecoverable transport problems (with a hint)."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


@dataclass
class PortInfo:
    device: str
    vid: Optional[int] = None
    pid: Optional[int] = None
    description: str = ""
    manufacturer: str = ""
    serial_number: str = ""
    readable: bool = False
    writable: bool = False
    issues: list = field(default_factory=list)

    @property
    def vendor(self) -> str:
        return KNOWN_VIDS.get(self.vid or -1, "unknown")

    @property
    def likely_bridge(self) -> bool:
        return self.vid in KNOWN_VIDS

    @property
    def score(self) -> int:
        s = 0
        if self.vid == ESPRESSIF_VID:
            s += 10
        elif self.likely_bridge:
            s += 5
        if self.readable and self.writable:
            s += 3
        if "ACM" in self.device:
            s += 1
        return s

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "vid": f"{self.vid:04X}" if self.vid is not None else None,
            "pid": f"{self.pid:04X}" if self.pid is not None else None,
            "vendor": self.vendor,
            "description": self.description,
            "manufacturer": self.manufacturer,
            "serial_number": self.serial_number,
            "readable": self.readable,
            "writable": self.writable,
            "issues": self.issues,
        }


def _check_access(path: str) -> tuple[bool, bool, list]:
    issues = []
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return False, False, ["device node missing"]
    except PermissionError:
        return False, False, ["cannot stat device node (SELinux/chroot restriction?)"]
    if not stat.S_ISCHR(st.st_mode):
        issues.append("not a character device")
    r = os.access(path, os.R_OK)
    w = os.access(path, os.W_OK)
    if not (r and w):
        issues.append(
            f"no read/write permission (mode {oct(st.st_mode & 0o777)}, gid {st.st_gid}); "
            "add your user to the 'dialout' group or use the NetHunter root shell"
        )
    return r, w, issues


def discover_ports() -> list[PortInfo]:
    """Enumerate candidate serial ports, best candidates first."""
    found: dict[str, PortInfo] = {}
    if list_ports is not None:
        try:
            for p in list_ports.comports():
                found[p.device] = PortInfo(
                    device=p.device, vid=p.vid, pid=p.pid,
                    description=p.description or "", manufacturer=p.manufacturer or "",
                    serial_number=p.serial_number or "",
                )
        except Exception:  # sysfs often unreadable in chroot
            pass
    # In NetHunter chroots /sys may be hidden; fall back to globbing /dev.
    for path in glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"):
        found.setdefault(path, PortInfo(device=path, description="(no sysfs metadata)"))
    out = []
    for info in found.values():
        if not (("ttyACM" in info.device) or ("ttyUSB" in info.device) or info.vid):
            continue
        info.readable, info.writable, issues = _check_access(info.device)
        info.issues.extend(issues)
        if info.vid is not None and not info.likely_bridge:
            info.issues.append("unrecognised USB vendor; may not be an RF Bridge")
        out.append(info)
    out.sort(key=lambda p: p.score, reverse=True)
    return out


def usb_environment_report() -> dict:
    """Facts helpful for troubleshooting Android USB OTG + chroot setups."""
    rep = {
        "pyserial": serial is not None,
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "groups": os.getgroups() if hasattr(os, "getgroups") else [],
        "dev_ttyACM": sorted(glob.glob("/dev/ttyACM*")),
        "dev_ttyUSB": sorted(glob.glob("/dev/ttyUSB*")),
        "sysfs_usb_visible": os.path.isdir("/sys/bus/usb/devices"),
        "cdc_acm_driver": os.path.isdir("/sys/bus/usb/drivers/cdc_acm"),
        "android": os.path.exists("/system/build.prop") or "ANDROID_ROOT" in os.environ,
        "notes": [],
    }
    if not rep["dev_ttyACM"] and not rep["dev_ttyUSB"]:
        rep["notes"].append(
            "No /dev/ttyACM* or /dev/ttyUSB* nodes. Either the board is not attached, the OTG "
            "cable is charge-only, or the kernel lacks CONFIG_USB_ACM (see docs/USB_TROUBLESHOOTING.md)."
        )
    if rep["sysfs_usb_visible"] and not rep["cdc_acm_driver"]:
        rep["notes"].append("cdc_acm driver not registered in this kernel; ESP32-S3 native USB needs it.")
    return rep


class SerialTransport:
    """Newline-framed serial transport with a background reader thread."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.2):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser = None
        self._rx: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._wlock = threading.Lock()
        self.connected = False
        self.last_error: Optional[str] = None

    def open(self) -> None:
        if serial is None:
            raise TransportError("pyserial not installed", "pip install pyserial  (or run scripts/install.sh)")
        r, w, issues = _check_access(self.port)
        if not (r and w):
            raise TransportError(f"Cannot access {self.port}: {'; '.join(issues)}",
                                 "See docs/USB_TROUBLESHOOTING.md#permissions")
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout,
                                      write_timeout=2, dsrdtr=False, rtscts=False)
        except serial.SerialException as e:
            raise TransportError(f"Failed to open {self.port}: {e}",
                                 "Device busy (another app?) or unsupported serial driver") from e
        # DTR asserted + RTS released: native USB CDC needs DTR to consider the
        # host "present"; on CP210x/CH340 boards RTS low avoids holding EN in reset.
        # Some drivers (and ptys) don't support modem-control ioctls: ignore.
        for attr, val in (("dtr", True), ("rts", False)):
            try:
                setattr(self._ser, attr, val)
            except (OSError, serial.SerialException):
                pass
        self._stop.clear()
        self.connected = True
        self._thread = threading.Thread(target=self._reader, name="rfb-reader", daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(self._ser.in_waiting or 1)
            except Exception as e:  # unplugged
                self.last_error = str(e)
                self.connected = False
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", "replace").strip()
                if text:
                    self._rx.put(text)
            if len(buf) > 65536:
                buf = b""

    def write_line(self, text: str) -> None:
        if not self.connected or self._ser is None:
            raise TransportError("not connected")
        with self._wlock:
            try:
                self._ser.write(text.encode() + b"\n")
                self._ser.flush()
            except Exception as e:
                self.connected = False
                self.last_error = str(e)
                raise TransportError(f"write failed: {e}") from e

    def read_line(self, timeout: float = 0.1) -> Optional[str]:
        try:
            return self._rx.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self.connected = False


def wait_for_port(predicate=None, timeout: float = 10.0) -> Optional[PortInfo]:
    """Poll until a suitable port appears (used for reconnection)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for p in discover_ports():
            if p.readable and p.writable and (predicate is None or predicate(p)):
                return p
        time.sleep(0.5)
    return None
