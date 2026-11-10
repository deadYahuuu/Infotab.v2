#!/usr/bin/env python3
"""
InfoTab - single-file system / gaming info panel.

Tabs:
  * System Info  - FPS (PresentMon + 1%/0.1% lows + sparkline), ping graph,
                   CPU/RAM/disk/net/GPU live stats, temps, fans, battery.
  * Processes    - top processes by CPU/RAM with a kill button.
  * Settings     - theme presets + per-color pickers, always-on-top,
                   compact HUD, CSV logging, reset.
  * Credits      - owner, links, license notice, version.

Drop PresentMon.exe next to this file (or on PATH) for real game FPS.
"""

import tkinter as tk
from tkinter import ttk, colorchooser, messagebox, filedialog

import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque

# ---------------------------------------------------------------------------
#  Platform helpers
# ---------------------------------------------------------------------------

SYSTEM = platform.system().lower()
CREATE_NO_WINDOW = 0x08000000  # Windows: don't flash a console window

try:
    import psutil
except Exception:
    psutil = None


def _hidden_kwargs():
    if SYSTEM == "windows":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


def _run_out(cmd, timeout=10):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, **_hidden_kwargs())
        return res.stdout or ""
    except Exception:
        return ""


def _powershell(script, timeout=15):
    return _run_out(["powershell", "-NoProfile", "-NonInteractive",
                     "-Command", script], timeout=timeout)


def _fmt_bytes(n):
    if not n:
        return "0 B"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_rate(bps):
    if bps is None:
        return "--"
    return _fmt_bytes(bps) + "/s"


def _fmt_uptime(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


# ---------------------------------------------------------------------------
#  Credits / version
# ---------------------------------------------------------------------------

VERSION = "2.0.1"
OWNER = "3lited"
LINKS = (
    ("Discord", "https://discord.com/users/1063483348086964296"),
    ("YouTube", "https://www.youtube.com/@fr3lite"),
    ("Website", "https://guns.lol/jpumpking"),
)


# ---------------------------------------------------------------------------
#  Settings (persisted JSON next to the script)
# ---------------------------------------------------------------------------

THEME_KEYS = (
    "bg", "fg", "muted", "panel", "accent",
    "good", "warn", "bad",
    "graph_bg", "graph_line", "graph_fill",
    "entry_bg", "entry_fg",
)

PRESETS = {
    "Dark": {
        "bg": "#1e1e1e", "fg": "#e6e6e6", "muted": "#9a9a9a",
        "panel": "#252526", "accent": "#4ec9b0",
        "good": "#6ac46a", "warn": "#dcdcaa", "bad": "#f48771",
        "graph_bg": "#181818", "graph_line": "#4ec9b0",
        "graph_fill": "#2d4f47",
        "entry_bg": "#2d2d30", "entry_fg": "#e6e6e6",
    },
    "Light": {
        "bg": "#f5f5f5", "fg": "#1e1e1e", "muted": "#666666",
        "panel": "#e8e8e8", "accent": "#0a7ea4",
        "good": "#1a7f37", "warn": "#9a6700", "bad": "#cf222e",
        "graph_bg": "#ffffff", "graph_line": "#0a7ea4",
        "graph_fill": "#cfe8f3",
        "entry_bg": "#ffffff", "entry_fg": "#1e1e1e",
    },
    "Nord": {
        "bg": "#2e3440", "fg": "#eceff4", "muted": "#a0a8b8",
        "panel": "#3b4252", "accent": "#88c0d0",
        "good": "#a3be8c", "warn": "#ebcb8b", "bad": "#bf616a",
        "graph_bg": "#272c36", "graph_line": "#88c0d0",
        "graph_fill": "#3b5262",
        "entry_bg": "#3b4252", "entry_fg": "#eceff4",
    },
    "Dracula": {
        "bg": "#282a36", "fg": "#f8f8f2", "muted": "#9aa0b5",
        "panel": "#343746", "accent": "#bd93f9",
        "good": "#50fa7b", "warn": "#f1fa8c", "bad": "#ff5555",
        "graph_bg": "#21222c", "graph_line": "#bd93f9",
        "graph_fill": "#443a63",
        "entry_bg": "#343746", "entry_fg": "#f8f8f2",
    },
    "Solarized": {
        "bg": "#002b36", "fg": "#93a1a1", "muted": "#657b83",
        "panel": "#073642", "accent": "#2aa198",
        "good": "#859900", "warn": "#b58900", "bad": "#dc322f",
        "graph_bg": "#00212b", "graph_line": "#2aa198",
        "graph_fill": "#0a4a4a",
        "entry_bg": "#073642", "entry_fg": "#93a1a1",
    },
}

DEFAULTS = {
    "colors": dict(PRESETS["Dark"]),
    "preset": "Dark",
    "ping_host": "8.8.8.8",
    "always_on_top": False,
    "compact_hud": False,
    "hud_alpha": 0.85,
    "csv_logging": False,
    "csv_path": "",
}


def _settings_path():
    here = os.path.dirname(os.path.abspath(__file__))
    for folder in (here, os.path.expanduser("~")):
        try:
            p = os.path.join(folder, "infotab_settings.json")
            with open(p, "a"):
                pass
            return p
        except Exception:
            continue
    return os.path.join(here, "infotab_settings.json")


class Settings:
    def __init__(self):
        self.path = _settings_path()
        self.data = json.loads(json.dumps(DEFAULTS))
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    if k == "colors" and isinstance(v, dict):
                        merged = dict(DEFAULTS["colors"])
                        merged.update({kk: vv for kk, vv in v.items()
                                       if kk in THEME_KEYS and isinstance(vv, str)})
                        self.data["colors"] = merged
                    else:
                        self.data[k] = v
        except Exception:
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2)
        except Exception:
            pass

    @property
    def colors(self):
        return self.data["colors"]


# ---------------------------------------------------------------------------
#  CPU information
# ---------------------------------------------------------------------------

_STATIC = {}


def cpu_name():
    if "cpu_name" in _STATIC:
        return _STATIC["cpu_name"]

    name = None
    try:
        if SYSTEM == "linux":
            with open("/proc/cpuinfo") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        name = line.split(":", 1)[1].strip()
                        break
        elif SYSTEM == "darwin":
            name = _run_out(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        elif SYSTEM == "windows":
            out = _powershell("(Get-CimInstance Win32_Processor).Name")
            lines = [l.strip() for l in out.splitlines() if l.strip()]
            if lines:
                name = lines[0]
    except Exception:
        name = None

    if not name:
        name = platform.processor() or platform.machine() or "Unknown CPU"

    _STATIC["cpu_name"] = name
    return name


def cpu_core_counts():
    if "cores" in _STATIC:
        return _STATIC["cores"]

    logical = os.cpu_count() or 0
    physical = None
    try:
        if psutil is not None:
            physical = psutil.cpu_count(logical=False)
        elif SYSTEM == "windows":
            out = _powershell("(Get-CimInstance Win32_Processor).NumberOfCores")
            nums = [int(x) for x in out.split() if x.strip().isdigit()]
            if nums:
                physical = sum(nums)
        elif SYSTEM == "linux":
            pairs = set()
            phys_id = core_id = None
            with open("/proc/cpuinfo") as fh:
                for line in fh:
                    if not line.strip():
                        if phys_id is not None and core_id is not None:
                            pairs.add((phys_id, core_id))
                        phys_id = core_id = None
                        continue
                    key, _, val = line.partition(":")
                    key = key.strip().lower()
                    if key == "physical id":
                        phys_id = val.strip()
                    elif key == "core id":
                        core_id = val.strip()
            if pairs:
                physical = len(pairs)
        elif SYSTEM == "darwin":
            out = _run_out(["sysctl", "-n", "hw.physicalcpu"]).strip()
            if out.isdigit():
                physical = int(out)
    except Exception:
        physical = None

    _STATIC["cores"] = (physical, logical)
    return _STATIC["cores"]


def _win_cpu_times():
    try:
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD),
                        ("dwHighDateTime", wintypes.DWORD)]

        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None

        def val(ft):
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

        return val(idle), val(kernel) + val(user)
    except Exception:
        return None


def _linux_cpu_times():
    try:
        with open("/proc/stat") as fh:
            parts = fh.readline().split()
        vals = [int(x) for x in parts[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return idle, sum(vals)
    except Exception:
        return None


def _mac_cpu_percent():
    out = _run_out(["top", "-l", "1", "-n", "0"], timeout=15)
    m = re.search(r"CPU usage:\s*([\d.]+)%\s*user,\s*([\d.]+)%\s*sys,\s*([\d.]+)%\s*idle", out)
    if m:
        return 100.0 - float(m.group(3))
    return None


def cpu_freq_mhz():
    try:
        if psutil is not None:
            f = psutil.cpu_freq()
            if f:
                return f.current
    except Exception:
        pass
    return None


def load_average():
    try:
        if psutil is not None and hasattr(psutil, "getloadavg"):
            return psutil.getloadavg()
    except Exception:
        pass
    try:
        return os.getloadavg()
    except Exception:
        return None


class CpuUsageMeter:
    def __init__(self):
        self._lock = threading.Lock()
        self._prev = None
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

    def percent(self):
        if psutil is not None:
            try:
                return psutil.cpu_percent(interval=None)
            except Exception:
                pass

        if SYSTEM == "darwin":
            return _mac_cpu_percent()

        with self._lock:
            if SYSTEM == "windows":
                cur = _win_cpu_times()
            elif SYSTEM == "linux":
                cur = _linux_cpu_times()
            else:
                cur = None

            if cur is None:
                return None
            if self._prev is None:
                self._prev = cur
                return None

            d_idle = cur[0] - self._prev[0]
            d_total = cur[1] - self._prev[1]
            self._prev = cur
            if d_total <= 0:
                return None
            return max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total)))


# ---------------------------------------------------------------------------
#  Memory / disk / net / sensors
# ---------------------------------------------------------------------------

def _win_ram():
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return None
        total = stat.ullTotalPhys
        avail = stat.ullAvailPhys
        return total, total - avail, avail
    except Exception:
        return None


def _linux_ram():
    try:
        info = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                key, _, val = line.partition(":")
                info[key.strip()] = val.strip()

        def kb(key):
            m = re.search(r"(\d+)", info.get(key, ""))
            return int(m.group(1)) * 1024 if m else 0

        total = kb("MemTotal")
        avail = kb("MemAvailable")
        if not avail:
            avail = kb("MemFree") + kb("Buffers") + kb("Cached")
        if not total:
            return None
        return total, total - avail, avail
    except Exception:
        return None


def _mac_ram():
    try:
        total = int((_run_out(["sysctl", "-n", "hw.memsize"]).strip() or "0"))
        if not total:
            return None
        out = _run_out(["vm_stat"], timeout=10)
        page = 4096
        m = re.search(r"page size of (\d+) bytes", out)
        if m:
            page = int(m.group(1))

        vals = {}
        for line in out.splitlines():
            mm = re.match(r'"?([^":]+)"?:\s+(\d+)', line)
            if mm:
                vals[mm.group(1).strip()] = int(mm.group(2))

        free = (vals.get("Pages free", 0)
                + vals.get("Pages inactive", 0)
                + vals.get("Pages speculative", 0)) * page
        free = min(free, total)
        return total, total - free, free
    except Exception:
        return None


def ram_usage():
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            return vm.total, vm.total - vm.available, vm.available
        except Exception:
            pass

    if SYSTEM == "windows":
        return _win_ram()
    if SYSTEM == "linux":
        return _linux_ram()
    if SYSTEM == "darwin":
        return _mac_ram()
    return None


def swap_usage():
    if psutil is None:
        return None
    try:
        sw = psutil.swap_memory()
        return sw.total, sw.used, sw.free
    except Exception:
        return None


def disk_usages():
    """List of (mount, total, used, free) for real filesystems."""
    out = []
    if psutil is not None:
        try:
            for p in psutil.disk_partitions(all=False):
                if SYSTEM == "windows":
                    if "cdrom" in p.opts or not p.fstype:
                        continue
                try:
                    u = shutil.disk_usage(p.mountpoint)
                except Exception:
                    continue
                out.append((p.mountpoint, u.total, u.used, u.free))
        except Exception:
            pass
    if not out:
        try:
            path = (os.environ.get("SystemDrive", "C:") + "\\") if SYSTEM == "windows" else "/"
            u = shutil.disk_usage(path)
            out.append((path, u.total, u.used, u.free))
        except Exception:
            pass
    return out


def uptime_seconds():
    if psutil is not None:
        try:
            return time.time() - psutil.boot_time()
        except Exception:
            pass

    try:
        if SYSTEM == "linux":
            with open("/proc/uptime") as fh:
                return float(fh.read().split()[0])
        if SYSTEM == "darwin":
            out = _run_out(["sysctl", "-n", "kern.boottime"])
            m = re.search(r"sec\s*=\s*(\d+)", out)
            if m:
                return time.time() - int(m.group(1))
        if SYSTEM == "windows":
            import ctypes
            ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
            return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    except Exception:
        pass
    return None


def os_caption():
    try:
        if SYSTEM == "windows":
            out = _powershell(
                "Get-CimInstance Win32_OperatingSystem | "
                "Select-Object Caption,Version,BuildNumber,OSArchitecture | "
                "ConvertTo-Csv -NoTypeInformation")
            rows = list(csv.DictReader(out.splitlines()))
            if rows:
                r = rows[0]
                parts = [r.get("Caption", "").strip(),
                         r.get("Version", "").strip(),
                         f"build {r.get('BuildNumber', '').strip()}"]
                return "  ".join(p for p in parts if p)
        elif SYSTEM == "linux":
            try:
                with open("/etc/os-release") as fh:
                    for line in fh:
                        if line.startswith("PRETTY_NAME="):
                            return line.split("=", 1)[1].strip().strip('"')
            except Exception:
                pass
            return platform.platform()
        elif SYSTEM == "darwin":
            name = _run_out(["sw_vers", "-productName"]).strip()
            ver = _run_out(["sw_vers", "-productVersion"]).strip()
            return f"{name} {ver}".strip()
    except Exception:
        pass
    return platform.platform()


def motherboard_info():
    if SYSTEM != "windows":
        return None
    try:
        out = _powershell(
            "Get-CimInstance Win32_BaseBoard | "
            "Select-Object Manufacturer,Product | ConvertTo-Csv -NoTypeInformation")
        rows = list(csv.DictReader(out.splitlines()))
        if not rows:
            return None
        r = rows[0]
        mfg = (r.get("Manufacturer") or "").strip()
        prod = (r.get("Product") or "").strip()
        return f"{mfg} {prod}".strip() or None
    except Exception:
        return None


def screen_info():
    """(resolution str, refresh Hz) - best effort."""
    try:
        if SYSTEM == "windows":
            out = _powershell(
                "Get-CimInstance Win32_VideoController | "
                "Select-Object CurrentHorizontalResolution,CurrentVerticalResolution,"
                "CurrentRefreshRate | ConvertTo-Csv -NoTypeInformation")
            rows = list(csv.DictReader(out.splitlines()))
            if rows:
                r = rows[0]
                w = r.get("CurrentHorizontalResolution", "").strip()
                h = r.get("CurrentVerticalResolution", "").strip()
                hz = r.get("CurrentRefreshRate", "").strip()
                if w and h:
                    return f"{w}x{h}", (hz or None)
        elif SYSTEM == "linux":
            out = _run_out(["xrandr"], timeout=5)
            m = re.search(r"(\d+x\d+)\s+([\d.]+)\*", out)
            if m:
                return m.group(1), f"{float(m.group(2)):.0f}"
    except Exception:
        pass
    return None, None


def temperatures():
    """List of (label, current_c, high_c) - psutil where available."""
    if psutil is None or not hasattr(psutil, "sensors_temperatures"):
        return []
    try:
        temps = psutil.sensors_temperatures() or {}
    except Exception:
        return []
    out = []
    for chip, entries in temps.items():
        for e in entries:
            label = e.label or chip
            out.append((label, e.current, e.high))
    return out


def fans():
    if psutil is None or not hasattr(psutil, "sensors_fans"):
        return []
    try:
        f = psutil.sensors_fans() or {}
    except Exception:
        return []
    out = []
    for chip, entries in f.items():
        for e in entries:
            out.append((e.label or chip, e.current))
    return out


def battery_info():
    if psutil is None or not hasattr(psutil, "sensors_battery"):
        return None
    try:
        b = psutil.sensors_battery()
        if b is None:
            return None
        return b.percent, b.power_plugged, b.secsleft
    except Exception:
        return None


def local_ip():
    if psutil is None:
        return None
    try:
        addrs = psutil.net_if_addrs()
        for name, infos in addrs.items():
            if name.lower().startswith(("lo", "loopback")):
                continue
            for a in infos:
                if getattr(a, "family", None) is not None and a.family.name == "AF_INET":
                    if not a.address.startswith("127."):
                        return name, a.address
    except Exception:
        pass
    return None


class NetMeter:
    def __init__(self):
        self._prev = None
        self._t = None

    def rate(self):
        if psutil is None:
            return None
        try:
            c = psutil.net_io_counters()
        except Exception:
            return None
        now = time.time()
        if self._prev is None:
            self._prev, self._t = c, now
            return None
        dt = max(now - self._t, 1e-6)
        up = (c.bytes_sent - self._prev.bytes_sent) / dt
        down = (c.bytes_recv - self._prev.bytes_recv) / dt
        self._prev, self._t = c, now
        return up, down


class DiskMeter:
    def __init__(self):
        self._prev = None
        self._t = None

    def rate(self):
        if psutil is None:
            return None
        try:
            c = psutil.disk_io_counters()
        except Exception:
            return None
        if c is None:
            return None
        now = time.time()
        if self._prev is None:
            self._prev, self._t = c, now
            return None
        dt = max(now - self._t, 1e-6)
        read = (c.read_bytes - self._prev.read_bytes) / dt
        write = (c.write_bytes - self._prev.write_bytes) / dt
        self._prev, self._t = c, now
        return read, write


# ---------------------------------------------------------------------------
#  GPU detection + live stats
# ---------------------------------------------------------------------------

def _gpus_windows():
    ps = ("Get-CimInstance Win32_VideoController | "
          "Select-Object Name,AdapterRAM,DriverVersion | "
          "ConvertTo-Csv -NoTypeInformation")
    out = _powershell(ps, timeout=25)
    if not out.strip():
        return []
    gpus = []
    for row in csv.DictReader(out.splitlines()):
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        vram = None
        try:
            vram = int(str(row.get("AdapterRAM", "")).strip())
            if vram < 0:
                vram += 1 << 32
        except (TypeError, ValueError):
            vram = None
        gpus.append({
            "name": name,
            "vram": vram,
            "driver": (row.get("DriverVersion") or "").strip() or None,
        })
    return gpus


def _gpus_linux():
    try:
        res = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    gpus = []
    for line in res.stdout.splitlines():
        if re.search(r"\b(vga|3d|display)\b", line, re.IGNORECASE):
            m = re.search(r":\s*(.+)$", line)
            if m:
                gpus.append({"name": m.group(1).strip(), "vram": None, "driver": None})
    return gpus


def _gpus_macos():
    try:
        res = subprocess.run(["system_profiler", "SPDisplaysDataType"],
                             capture_output=True, text=True, timeout=25)
    except Exception:
        return []
    gpus, current = [], None
    for line in res.stdout.splitlines():
        s = line.strip()
        if s.startswith("Chipset Model:"):
            if current:
                gpus.append(current)
            current = {"name": s.split(":", 1)[1].strip(), "vram": None, "driver": None}
        elif current and s.startswith("VRAM"):
            m = re.search(r"([\d.]+)\s*(MB|GB)", s)
            if m:
                val = float(m.group(1))
                current["vram"] = int(val * (1024 ** 3 if m.group(2) == "GB" else 1024 ** 2))
    if current:
        gpus.append(current)
    return gpus


def detect_gpus():
    try:
        if SYSTEM == "windows":
            return _gpus_windows()
        if SYSTEM == "linux":
            return _gpus_linux()
        if SYSTEM == "darwin":
            return _gpus_macos()
    except Exception:
        pass
    return []


def nvidia_smi_stats():
    """List of dicts with live NVIDIA GPU stats (empty if unavailable)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    fields = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,fan.speed"
    out = _run_out([exe, f"--query-gpu={fields}",
                    "--format=csv,noheader,nounits"], timeout=5)
    stats = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6 or not parts[0]:
            continue

        def num(s):
            try:
                return float(s)
            except Exception:
                return None

        stats.append({
            "name": parts[0],
            "util": num(parts[1]),
            "vram_used_mb": num(parts[2]),
            "vram_total_mb": num(parts[3]),
            "temp": num(parts[4]),
            "fan": num(parts[5]),
        })
    return stats


def linux_amd_intel_gpu_stats():
    """utilization % from /sys/class/drm for amdgpu / i915."""
    out = []
    try:
        base = "/sys/class/drm"
        if not os.path.isdir(base):
            return out
        for name in sorted(os.listdir(base)):
            if not re.match(r"card\d+$", name):
                continue
            dev = os.path.join(base, name, "device")
            util_p = os.path.join(dev, "gpu_busy_percent")
            if not os.path.isfile(util_p):
                continue
            try:
                with open(util_p) as fh:
                    util = float(fh.read().strip())
            except Exception:
                util = None
            out.append({"name": name, "util": util})
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
#  Foreground window -> process name (Windows)
# ---------------------------------------------------------------------------

_win_api = None


def _init_win_api():
    global _win_api
    if _win_api is not None:
        return _win_api
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetForegroundWindow.argtypes = []
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        _win_api = (ctypes, wintypes, user32, kernel32)
    except Exception:
        _win_api = False
    return _win_api


def foreground_process_name():
    if SYSTEM != "windows":
        return None
    api = _init_win_api()
    if not api:
        return None
    ctypes, wintypes, user32, kernel32 = api
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
#  PresentMon
# ---------------------------------------------------------------------------

_LAUNCHER_SUFFIXES = (
    "-win64-shipping.exe", "-win32-shipping.exe",
    "-shipping.exe", "-win64-shipping", "-win32-shipping",
)


def norm_app(name):
    """Normalize a process/exe name so PresentMon rows match the foreground app."""
    if not name:
        return ""
    n = os.path.basename(str(name)).strip().strip('"').lower()
    for suf in _LAUNCHER_SUFFIXES:
        if n.endswith(suf):
            n = n[:-len(suf)]
            break
    if n.endswith(".exe"):
        n = n[:-4]
    return n


def find_presentmon():
    here = os.path.dirname(os.path.abspath(__file__))
    names = ("PresentMon.exe", "PresentMon", "presentmon.exe", "presentmon")
    candidates = []
    for n in names:
        candidates.append(os.path.join(here, n))
        candidates.append(os.path.join(here, "PresentMon", n))
        candidates.append(os.path.join(os.getcwd(), n))
    for n in ("PresentMon", "PresentMon.exe", "presentmon"):
        found = shutil.which(n)
        if found:
            candidates.append(found)
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


class GameFPSMonitor:
    ARG_VARIANTS = (
        ("-output_stdout", "-no_console_stats"),
        ("--output_stdout", "--no_console_stats"),
    )

    MAX_FRAME_MS = 1000.0  # drop hitches above 1 s from stats

    def __init__(self):
        self.path = find_presentmon()
        self.available = False
        self.samples = {}          # norm-app -> deque[(t, ms)]
        self.lock = threading.Lock()
        self.proc = None
        self._stop = threading.Event()
        self._own = norm_app(os.path.basename(sys.executable))

    def start(self):
        if not self.path:
            return
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()
        if self.proc:
            self._kill(self.proc)

    @staticmethod
    def _kill(proc):
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

    def _run(self):
        while not self._stop.is_set():
            started = False
            for args in self.ARG_VARIANTS:
                if self._stop.is_set():
                    return
                if self._try_variant(list(args)):
                    started = True
                    break
            if not started:
                return

            while (not self._stop.is_set()
                   and self.proc is not None
                   and self.proc.poll() is None):
                time.sleep(0.5)

            self.available = False
            if self._stop.is_set():
                return
            time.sleep(2)

    def _try_variant(self, args):
        try:
            proc = subprocess.Popen(
                [self.path] + args,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, **_hidden_kwargs())
        except Exception:
            return False

        ready = threading.Event()
        threading.Thread(target=self._reader, args=(proc, ready), daemon=True).start()

        deadline = time.time() + 4.0
        while time.time() < deadline:
            if ready.is_set():
                self.proc = proc
                self.available = True
                return True
            if proc.poll() is not None:
                break
            time.sleep(0.1)

        self._kill(proc)
        return False

    def _reader(self, proc, ready):
        idx_app, idx_ms = 0, 10
        header_done = False
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                fields = next(csv.reader([line]))

                if not header_done:
                    lowered = [f.strip().strip('"').lower() for f in fields]
                    if "msbetweenpresents" in lowered:
                        for i, f in enumerate(lowered):
                            if f in ("application", "processname", "process_name"):
                                idx_app = i
                            elif f == "msbetweenpresents":
                                idx_ms = i
                        header_done = True
                        ready.set()
                        continue
                    if len(fields) > max(idx_app, idx_ms):
                        header_done = True
                        ready.set()
                    else:
                        continue

                if len(fields) <= max(idx_app, idx_ms):
                    continue
                app = norm_app(fields[idx_app])
                try:
                    ms = float(fields[idx_ms])
                except ValueError:
                    continue
                if not app or ms <= 0 or ms > self.MAX_FRAME_MS:
                    continue

                with self.lock:
                    dq = self.samples.setdefault(app, deque(maxlen=900))
                    dq.append((time.time(), ms))
        except Exception:
            pass
        finally:
            if self.proc is proc:
                self.available = False

    def get_fps_stats(self, window=1.0, min_samples=10):
        """Return (fps, low1, low01, app) for the foreground app, or Nones."""
        if not self.available:
            return None, None, None, None

        app_raw = foreground_process_name()
        if not app_raw:
            return None, None, None, None
        app = norm_app(app_raw)
        if not app or app == self._own:
            return None, None, None, None

        now = time.time()
        with self.lock:
            dq = self.samples.get(app)
            if not dq:
                return None, None, None, None
            recent = [ms for (t, ms) in dq if now - t <= window]

        if len(recent) < min_samples:
            return None, None, None, None

        avg = sum(recent) / len(recent)
        if avg <= 0:
            return None, None, None, None

        slowest = sorted(recent, reverse=True)

        def low(p):
            k = max(1, int(round(len(slowest) * p)))
            k = min(k, len(slowest))
            worst = slowest[:k]
            m = sum(worst) / len(worst)
            return 1000.0 / m if m > 0 else None

        return 1000.0 / avg, low(0.01), low(0.001), app_raw

    def get_fps(self):
        fps, _, _, app = self.get_fps_stats()
        return fps, app


# ---------------------------------------------------------------------------
#  Sparkline / bar graph helper
# ---------------------------------------------------------------------------

def draw_sparkline(canvas, values, colors, lo=None, hi=None,
                   fill=True, hline=None):
    canvas.delete("all")
    w = max(canvas.winfo_width(), 10)
    h = max(canvas.winfo_height(), 10)
    canvas.configure(bg=colors["graph_bg"])

    # frame
    canvas.create_rectangle(0, 0, w - 1, h - 1,
                            outline=colors["muted"], width=1)

    if not values:
        canvas.create_text(w // 2, h // 2, text="no data",
                           fill=colors["muted"], font=("Arial", 8))
        return

    if lo is None:
        lo = min(values)
    if hi is None:
        hi = max(values)
    if hi - lo < 1e-6:
        hi = lo + 1

    pad = 4
    n = len(values)
    step = (w - pad * 2) / max(n - 1, 1)

    def xy(i, v):
        v = max(lo, min(hi, v))
        x = pad + i * step
        y = h - pad - (v - lo) / (hi - lo) * (h - pad * 2)
        return x, y

    pts = [xy(i, v) for i, v in enumerate(values)]

    if fill and len(pts) > 1:
        poly = [pad, h - pad]
        for x, y in pts:
            poly.extend((x, y))
        poly.extend((pts[-1][0], h - pad))
        canvas.create_polygon(poly, fill=colors["graph_fill"], outline="")

    if len(pts) > 1:
        flat = []
        for x, y in pts:
            flat.extend((x, y))
        canvas.create_line(*flat, fill=colors["graph_line"], width=2,
                           smooth=False)

    if hline is not None and lo <= hline <= hi:
        _, y = xy(0, hline)
        canvas.create_line(pad, y, w - pad, y,
                           fill=colors["muted"], dash=(2, 3))


def draw_bar_history(canvas, values, colors, threshold_bad=None, scale_max=None):
    """Bar chart used for ping history (colour-coded by latency)."""
    canvas.delete("all")
    w = max(canvas.winfo_width(), 10)
    h = max(canvas.winfo_height(), 10)
    canvas.configure(bg=colors["graph_bg"])
    canvas.create_rectangle(0, 0, w - 1, h - 1,
                            outline=colors["muted"], width=1)

    if not values:
        canvas.create_text(w // 2, h // 2, text="no data",
                           fill=colors["muted"], font=("Arial", 8))
        return

    top = scale_max or max(values) or 1
    top = max(top, 1)
    n = len(values)
    pad = 2
    slot = (w - pad * 2) / max(n, 1)
    bw = max(1, slot - 1)

    for i, v in enumerate(values):
        if v is None:
            continue
        hh = (min(v, top) / top) * (h - pad * 2)
        x0 = pad + i * slot
        x1 = x0 + bw
        y0 = h - pad - hh
        y1 = h - pad
        if threshold_bad is not None and v >= threshold_bad:
            col = colors["bad"]
        elif v >= 60:
            col = colors["warn"]
        else:
            col = colors["good"]
        canvas.create_rectangle(x0, y0, x1, y1, fill=col, outline="")


# ---------------------------------------------------------------------------
#  Scrollable frame
# ---------------------------------------------------------------------------

class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas, padding=12)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _on_inner(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self.win, width=e.width)

    def _bind_wheel(self, _):
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", self._wheel)
        self.canvas.bind_all("<Button-5>", self._wheel)

    def _unbind_wheel(self, _):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _wheel(self, e):
        if getattr(e, "num", None) == 4:
            delta = -1
        elif getattr(e, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if e.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")


# ---------------------------------------------------------------------------
#  Compact HUD (always-on-top floating window)
# ---------------------------------------------------------------------------

class HudWindow(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", float(app.settings.data.get("hud_alpha", 0.85)))
        except Exception:
            pass

        self.geometry("220x110+40+40")

        self.fps_var = tk.StringVar(value="--")
        self.ping_var = tk.StringVar(value="--")
        self.cpu_var = tk.StringVar(value="CPU --")
        self.ram_var = tk.StringVar(value="RAM --")

        self._drag = (0, 0)
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag_move)
        self.bind("<Double-Button-1>", lambda e: self.destroy())

        self._build()

    def _build(self):
        c = self.app.settings.colors
        self.configure(bg=c["panel"])
        for w in self.winfo_children():
            w.destroy()

        top = tk.Frame(self, bg=c["panel"])
        top.pack(fill="both", expand=True, padx=8, pady=6)

        tk.Label(top, textvariable=self.fps_var, font=("Consolas", 26, "bold"),
                 bg=c["panel"], fg=c["accent"]).grid(row=0, column=0, sticky="w")
        tk.Label(top, text="FPS", font=("Arial", 8),
                 bg=c["panel"], fg=c["muted"]).grid(row=0, column=1, sticky="sw", padx=(4, 0))

        tk.Label(top, textvariable=self.ping_var, font=("Consolas", 12),
                 bg=c["panel"], fg=c["fg"]).grid(row=0, column=2, sticky="e", padx=(12, 0))
        top.columnconfigure(2, weight=1)

        tk.Label(top, textvariable=self.cpu_var, font=("Consolas", 10),
                 bg=c["panel"], fg=c["fg"]).grid(row=1, column=0, columnspan=3,
                                                 sticky="w", pady=(4, 0))
        tk.Label(top, textvariable=self.ram_var, font=("Consolas", 10),
                 bg=c["panel"], fg=c["fg"]).grid(row=2, column=0, columnspan=3,
                                                 sticky="w")

    def _press(self, e):
        self._drag = (e.x, e.y)

    def _drag_move(self, e):
        x = self.winfo_x() + e.x - self._drag[0]
        y = self.winfo_y() + e.y - self._drag[1]
        self.geometry(f"+{x}+{y}")

    def refresh_colors(self):
        try:
            self.attributes("-alpha", float(self.app.settings.data.get("hud_alpha", 0.85)))
        except Exception:
            pass
        self._build()

    def update_values(self, fps, ping, cpu, ram):
        if fps is not None:
            self.fps_var.set(f"{fps:.0f}")
        if ping is not None:
            self.ping_var.set(f"{ping:.0f} ms")
        if cpu is not None:
            self.cpu_var.set(f"CPU {cpu:4.1f}%")
        if ram is not None:
            self.ram_var.set(f"RAM {ram:4.1f}%")


# ---------------------------------------------------------------------------
#  Main application
# ---------------------------------------------------------------------------

class SystemInfoTab:
    def __init__(self, root):
        self.root = root
        self.root.title(f"InfoTab v{VERSION}")
        self.root.geometry("640x820")
        self.root.minsize(560, 620)

        self.settings = Settings()
        self.running = True
        self.ping_host = self.settings.data.get("ping_host", "8.8.8.8")
        self.ui_fps = 0.0
        self.last_ping = None
        self.last_cpu = None
        self.last_ram_pct = None

        # data
        self.ping_samples = deque(maxlen=60)
        self.ping_loss = deque(maxlen=60)      # 1 = timeout, 0 = ok
        self.fps_history = deque(maxlen=180)
        self.fps_low1 = None
        self.fps_low01 = None
        self.fps_app = None

        # meters
        self.cpu_meter = CpuUsageMeter()
        self.net_meter = NetMeter()
        self.disk_meter = DiskMeter()

        # caching / throttling
        self._slow_tick = 0
        self._slow_data = {}

        # csv logging
        self._log_fh = None
        self._log_writer = None

        # HUD
        self.hud = None

        # notebook
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)

        self.info_scroll = ScrollFrame(self.notebook)
        self.notebook.add(self.info_scroll, text="System Info")
        self.info_frame = self.info_scroll.inner

        self.proc_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.proc_tab, text="Processes")

        self.settings_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.settings_tab, text="Settings")

        self.credits_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.credits_tab, text="Credits")

        # canvases registered for redraw on theme change
        self._canvases = []

        # clickable link labels registered for theme updates
        self._link_labels = []

        self.build_info_tab()
        self.build_processes_tab()
        self.build_settings_tab()
        self.build_credits_tab()

        self.apply_theme()

        # start background monitors
        self.fps_monitor = GameFPSMonitor()
        self.fps_monitor.start()

        self.refresh_gpus()
        self.refresh_specs()
        self.refresh_static_extras()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # periodic updates
        self.frame_count = 0
        self.fps_start = time.time()
        self.tick()
        self.update_fps()
        self.start_ping_thread()
        self.start_specs_thread()
        self.start_process_thread()

        # always-on-top & HUD restore
        if self.settings.data.get("always_on_top"):
            try:
                self.root.attributes("-topmost", True)
            except Exception:
                pass
        if self.settings.data.get("compact_hud"):
            self.toggle_hud(True)

    # ------------------------------------------------------------------
    #  System Info tab layout
    # ------------------------------------------------------------------
    def build_info_tab(self):
        f = self.info_frame
        f.columnconfigure(1, weight=1)
        f.columnconfigure(0, weight=0)

        row = 0

        # ---- FPS ----
        ttk.Label(f, text="FPS", style="Header.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.fps_label = ttk.Label(f, text="--", style="Big.TLabel")
        self.fps_label.grid(row=row, column=0, sticky="w")
        self.fps_source_label = ttk.Label(f, text="starting...", style="Muted.TLabel")
        self.fps_source_label.grid(row=row, column=1, sticky="sw", padx=(10, 0))
        row += 1

        self.fps_lows_label = ttk.Label(f, text="1% --    0.1% --",
                                        style="Mono.TLabel")
        self.fps_lows_label.grid(row=row, column=0, columnspan=2,
                                 sticky="w", pady=(2, 0))
        row += 1

        self.fps_canvas = tk.Canvas(f, height=56, highlightthickness=0)
        self.fps_canvas.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._canvases.append(("fps", self.fps_canvas))
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=12)
        row += 1

        # ---- Ping ----
        ttk.Label(f, text="Network", style="Header.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.ping_label = ttk.Label(f, text="--", style="Accent.TLabel")
        self.ping_label.grid(row=row, column=0, sticky="w")
        self.ping_detail_label = ttk.Label(f, text="", style="Muted.TLabel")
        self.ping_detail_label.grid(row=row, column=1, sticky="e")
        row += 1

        self.ping_canvas = tk.Canvas(f, height=44, highlightthickness=0)
        self.ping_canvas.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._canvases.append(("ping", self.ping_canvas))
        row += 1

        hostrow = ttk.Frame(f)
        hostrow.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        hostrow.columnconfigure(1, weight=1)
        ttk.Label(hostrow, text="Host:", style="TLabel").grid(row=0, column=0, sticky="w")
        self.host_var = tk.StringVar(value=self.ping_host)
        self.host_entry = ttk.Entry(hostrow, textvariable=self.host_var)
        self.host_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.host_var.trace_add("write", self._on_host_changed)
        row += 1

        self.net_rate_label = ttk.Label(f, text="↑ --   ↓ --", style="Mono.TLabel")
        self.net_rate_label.grid(row=row, column=0, columnspan=2,
                                 sticky="w", pady=(4, 0))
        row += 1

        self.net_ip_label = ttk.Label(f, text="", style="Muted.TLabel")
        self.net_ip_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=12)
        row += 1

        # ---- CPU ----
        ttk.Label(f, text="CPU", style="Header.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.cpu_name_label = ttk.Label(f, text="Detecting...",
                                        wraplength=520, justify="left")
        self.cpu_name_label.grid(row=row, column=0, columnspan=2,
                                 sticky="w", pady=(2, 0))
        row += 1

        self.cpu_cores_label = ttk.Label(f, text="", style="Muted.TLabel")
        self.cpu_cores_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.cpu_usage_label = ttk.Label(f, text="Usage: --", style="Mono.TLabel")
        self.cpu_usage_label.grid(row=row, column=0, columnspan=2,
                                  sticky="w", pady=(2, 0))
        row += 1

        self.cpu_bar = ttk.Progressbar(f, orient="horizontal", mode="determinate",
                                       maximum=100, length=300)
        self.cpu_bar.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        row += 1

        self.cpu_extra_label = ttk.Label(f, text="", style="Muted.TLabel")
        self.cpu_extra_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=12)
        row += 1

        # ---- Memory ----
        ttk.Label(f, text="Memory", style="Header.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.ram_label = ttk.Label(f, text="Detecting...", style="Mono.TLabel")
        self.ram_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 0))
        row += 1

        self.ram_bar = ttk.Progressbar(f, orient="horizontal", mode="determinate",
                                       maximum=100, length=300)
        self.ram_bar.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        row += 1

        self.swap_label = ttk.Label(f, text="", style="Muted.TLabel")
        self.swap_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=12)
        row += 1

        # ---- Storage ----
        ttk.Label(f, text="Storage", style="Header.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.disk_container = ttk.Frame(f)
        self.disk_container.grid(row=row, column=0, columnspan=2, sticky="ew")
        row += 1

        self.disk_io_label = ttk.Label(f, text="I/O  R --   W --", style="Mono.TLabel")
        self.disk_io_label.grid(row=row, column=0, columnspan=2,
                                sticky="w", pady=(6, 0))
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=12)
        row += 1

        # ---- Sensors ----
        ttk.Label(f, text="Sensors", style="Header.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.temps_label = ttk.Label(f, text="Temperatures: --",
                                     style="Mono.TLabel", justify="left")
        self.temps_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.fans_label = ttk.Label(f, text="Fans: --", style="Mono.TLabel")
        self.fans_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.battery_label = ttk.Label(f, text="Battery: --", style="Mono.TLabel")
        self.battery_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=12)
        row += 1

        # ---- GPU ----
        head = ttk.Frame(f)
        head.grid(row=row, column=0, columnspan=2, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(head, text="Graphics Cards", style="Header.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Button(head, text="Refresh", width=9,
                   command=self.refresh_gpus).grid(row=0, column=1, sticky="e")
        row += 1

        self.gpu_container = ttk.Frame(f)
        self.gpu_container.grid(row=row, column=0, columnspan=2,
                                sticky="ew", pady=(6, 0))
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=12)
        row += 1

        # ---- System ----
        ttk.Label(f, text="System", style="Header.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.os_label = ttk.Label(f, text="", style="Mono.TLabel",
                                  wraplength=520, justify="left")
        self.os_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.board_label = ttk.Label(f, text="", style="Mono.TLabel")
        self.board_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.screen_label = ttk.Label(f, text="", style="Mono.TLabel")
        self.screen_label.grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.uptime_label = ttk.Label(f, text="Uptime: --", style="Mono.TLabel")
        self.uptime_label.grid(row=row, column=0, columnspan=2,
                               sticky="w", pady=(2, 0))
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=12)
        row += 1

        btns = ttk.Frame(f)
        btns.grid(row=row, column=0, columnspan=2, sticky="ew")
        for i in range(3):
            btns.columnconfigure(i, weight=1)
        ttk.Button(btns, text="Copy report",
                   command=self.copy_report).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(btns, text="Save report",
                   command=self.save_report).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(btns, text="Quit",
                   command=self.on_close).grid(row=0, column=2, sticky="ew", padx=(4, 0))
        row += 1

    # ------------------------------------------------------------------
    #  Processes tab
    # ------------------------------------------------------------------
    def build_processes_tab(self):
        f = self.proc_tab
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        head = ttk.Frame(f)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        head.columnconfigure(1, weight=1)

        self.proc_autovar = tk.BooleanVar(value=True)
        ttk.Checkbutton(head, text="Auto refresh", variable=self.proc_autovar).grid(
            row=0, column=0, sticky="w")
        ttk.Button(head, text="Refresh", command=self.refresh_processes).grid(
            row=0, column=2, sticky="e", padx=(6, 0))
        ttk.Button(head, text="Kill", command=self.kill_process).grid(
            row=0, column=3, sticky="e", padx=(6, 0))

        cols = ("pid", "name", "cpu", "mem")
        self.proc_tree = ttk.Treeview(f, columns=cols, show="headings",
                                      selectmode="browse")
        self.proc_tree.heading("pid", text="PID")
        self.proc_tree.heading("name", text="Name")
        self.proc_tree.heading("cpu", text="CPU %")
        self.proc_tree.heading("mem", text="Memory")
        self.proc_tree.column("pid", width=70, anchor="e", stretch=False)
        self.proc_tree.column("name", width=240, anchor="w")
        self.proc_tree.column("cpu", width=80, anchor="e", stretch=False)
        self.proc_tree.column("mem", width=100, anchor="e", stretch=False)
        self.proc_tree.grid(row=1, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(f, orient="vertical", command=self.proc_tree.yview)
        self.proc_tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=1, column=1, sticky="ns")

        self.proc_status = ttk.Label(f, text="", style="Muted.TLabel")
        self.proc_status.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def refresh_processes(self):
        if psutil is None:
            self.proc_status.config(text="psutil not installed")
            return
        rows = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = p.info
                mem = info.get("memory_info")
                mem_b = mem.rss if mem else 0
                cpu = info.get("cpu_percent") or 0.0
                rows.append((info["pid"], info["name"] or "?", cpu, mem_b))
            except Exception:
                continue
        rows.sort(key=lambda r: r[2], reverse=True)
        rows = rows[:40]

        sel = self.proc_tree.selection()
        keep_pid = None
        if sel:
            try:
                keep_pid = int(self.proc_tree.item(sel[0], "values")[0])
            except Exception:
                keep_pid = None

        self.proc_tree.delete(*self.proc_tree.get_children())
        for pid, name, cpu, mem_b in rows:
            iid = self.proc_tree.insert("", "end", values=(
                pid, name, f"{cpu:.1f}", _fmt_bytes(mem_b)))
            if keep_pid is not None and pid == keep_pid:
                self.proc_tree.selection_set(iid)

        self.proc_status.config(
            text=f"{len(rows)} processes (psutil CPU % is per-since-last-call)")

    def kill_process(self):
        sel = self.proc_tree.selection()
        if not sel or psutil is None:
            return
        try:
            pid = int(self.proc_tree.item(sel[0], "values")[0])
            name = self.proc_tree.item(sel[0], "values")[1]
        except Exception:
            return
        if not messagebox.askyesno("Kill process", f"Terminate {name} (PID {pid})?"):
            return
        try:
            psutil.Process(pid).terminate()
            self.proc_status.config(text=f"Sent terminate to {name} ({pid})")
        except Exception as e:
            self.proc_status.config(text=f"Failed: {e}")

    def start_process_thread(self):
        threading.Thread(target=self._proc_loop, daemon=True).start()

    def _proc_loop(self):
        while self.running:
            if self.proc_autovar.get():
                self.root.after(0, self.refresh_processes)
            time.sleep(3.0)

    # ------------------------------------------------------------------
    #  Settings tab
    # ------------------------------------------------------------------
    def build_settings_tab(self):
        f = self.settings_tab
        f.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(f, text="Theme", style="Header.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w")
        row += 1

        preset_row = ttk.Frame(f)
        preset_row.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        ttk.Label(preset_row, text="Preset:").grid(row=0, column=0, sticky="w")
        self.preset_var = tk.StringVar(value=self.settings.data.get("preset", "Dark"))
        cb = ttk.Combobox(preset_row, textvariable=self.preset_var,
                          values=list(PRESETS.keys()), state="readonly", width=14)
        cb.grid(row=0, column=1, sticky="w", padx=(6, 0))
        cb.bind("<<ComboboxSelected>>", self._on_preset)
        ttk.Button(preset_row, text="Reset to defaults",
                   command=self._reset_theme).grid(row=0, column=2, padx=(12, 0))
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        row += 1

        ttk.Label(f, text="Colors", style="Header.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w")
        row += 1

        self._swatch_buttons = {}
        for key in THEME_KEYS:
            ttk.Label(f, text=key.replace("_", " ")).grid(
                row=row, column=0, sticky="w", pady=2)
            btn = tk.Button(f, text=key, width=12, relief="groove",
                            command=lambda k=key: self._pick_color(k))
            btn.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=2)
            self._swatch_buttons[key] = btn
            row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1

        ttk.Label(f, text="Behaviour", style="Header.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w")
        row += 1

        self.topmost_var = tk.BooleanVar(value=bool(self.settings.data.get("always_on_top")))
        ttk.Checkbutton(f, text="Always on top", variable=self.topmost_var,
                        command=self._toggle_topmost).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=2)
        row += 1

        self.hud_var = tk.BooleanVar(value=bool(self.settings.data.get("compact_hud")))
        ttk.Checkbutton(f, text="Compact HUD overlay",
                        variable=self.hud_var,
                        command=lambda: self.toggle_hud(self.hud_var.get())).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=2)
        row += 1

        alpha_row = ttk.Frame(f)
        alpha_row.grid(row=row, column=0, columnspan=3, sticky="ew", pady=2)
        ttk.Label(alpha_row, text="HUD opacity:").grid(row=0, column=0, sticky="w")
        self.alpha_var = tk.DoubleVar(value=float(self.settings.data.get("hud_alpha", 0.85)))
        ttk.Scale(alpha_row, from_=0.3, to=1.0, variable=self.alpha_var,
                  orient="horizontal", length=160,
                  command=self._on_alpha).grid(row=0, column=1, sticky="w", padx=(8, 0))
        row += 1

        self.csv_var = tk.BooleanVar(value=bool(self.settings.data.get("csv_logging")))
        ttk.Checkbutton(f, text="Log CSV (fps/ping/cpu/ram)",
                        variable=self.csv_var,
                        command=self._toggle_csv).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=2)
        row += 1

        self.csv_path_label = ttk.Label(f, text="", style="Muted.TLabel",
                                        wraplength=440, justify="left")
        self.csv_path_label.grid(row=row, column=0, columnspan=3,
                                 sticky="w", pady=(0, 4))
        row += 1

        ttk.Button(f, text="Choose CSV file...",
                   command=self._choose_csv).grid(
            row=row, column=0, sticky="w")
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1

        ttk.Label(f, text=f"Settings file: {self.settings.path}",
                  style="Muted.TLabel", wraplength=520, justify="left").grid(
            row=row, column=0, columnspan=3, sticky="w")
        row += 1

        self._update_csv_label()
        self._refresh_swatches()

    # ------------------------------------------------------------------
    #  Credits tab
    # ------------------------------------------------------------------
    def build_credits_tab(self):
        f = self.credits_tab
        f.columnconfigure(0, weight=1)

        row = 0
        ttk.Label(f, text="Credits", style="Header.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 10))
        row += 1

        ttk.Label(f, text=f"Owner: {OWNER}", style="Accent.TLabel").grid(
            row=row, column=0, sticky="w")
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, sticky="ew", pady=12)
        row += 1

        ttk.Label(f, text="Links", style="Header.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6))
        row += 1

        for label, url in LINKS:
            self._add_link(f, row, label, url)
            row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, sticky="ew", pady=12)
        row += 1

        ttk.Label(f, text="License / Usage", style="Header.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 6))
        row += 1

        notice = (
            f"© {time.strftime('%Y')} {OWNER} — All rights reserved.\n\n"
            "InfoTab is the property of the owner listed above.\n"
            "Nobody is allowed to steal, copy, reupload, resell, or modify\n"
            "this code and claim it as their own.\n\n"
            "You may NOT redistribute this code, or any modified version of\n"
            "it, without explicit written permission from the owner.\n"
            "Do not remove or alter this credits section.\n\n"
            "Want to use or change the code? Ask the owner first."
        )
        ttk.Label(f, text=notice, style="Mono.TLabel",
                  justify="left", wraplength=520).grid(
            row=row, column=0, sticky="w")
        row += 1

        ttk.Separator(f, orient="horizontal").grid(
            row=row, column=0, sticky="ew", pady=12)
        row += 1

        # bottom of the section
        ttk.Label(f, text=f"v{VERSION}", style="Muted.TLabel").grid(
            row=row, column=0, sticky="w")

    def _add_link(self, parent, row, label, url):
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=0, sticky="w", pady=2)
        ttk.Label(holder, text=f"{label}: ", style="TLabel").pack(side="left")
        lbl = tk.Label(holder, text=url, cursor="hand2", bd=0,
                       highlightthickness=0)
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda _e, u=url: self._open_link(u))
        self._link_labels.append(lbl)

    def _open_link(self, url):
        try:
            webbrowser.open(url)
        except Exception:
            messagebox.showerror("InfoTab", f"Could not open:\n{url}")

    def _refresh_swatches(self):
        c = self.settings.colors
        for key, btn in getattr(self, "_swatch_buttons", {}).items():
            try:
                btn.configure(bg=c[key], activebackground=c[key],
                              fg=self._readable_on(c[key]))
            except Exception:
                pass

    @staticmethod
    def _readable_on(hexcolor):
        try:
            h = hexcolor.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            return "#000000" if (r * 0.299 + g * 0.587 + b * 0.114) > 150 else "#ffffff"
        except Exception:
            return "#ffffff"

    def _on_preset(self, _=None):
        name = self.preset_var.get()
        if name in PRESETS:
            self.settings.data["colors"] = dict(PRESETS[name])
            self.settings.data["preset"] = name
            self.settings.save()
            self.apply_theme()
            self._refresh_swatches()

    def _pick_color(self, key):
        cur = self.settings.colors.get(key, "#000000")
        rgb, hexcol = colorchooser.askcolor(color=cur, title=f"Choose {key}")
        if not hexcol:
            return
        self.settings.colors[key] = hexcol
        self.settings.data["preset"] = "Custom"
        self.settings.save()
        self.apply_theme()
        self._refresh_swatches()

    def _reset_theme(self):
        self.settings.data["colors"] = dict(PRESETS["Dark"])
        self.settings.data["preset"] = "Dark"
        self.preset_var.set("Dark")
        self.settings.save()
        self.apply_theme()
        self._refresh_swatches()

    def _toggle_topmost(self):
        v = bool(self.topmost_var.get())
        self.settings.data["always_on_top"] = v
        self.settings.save()
        try:
            self.root.attributes("-topmost", v)
        except Exception:
            pass

    def _on_alpha(self, _=None):
        a = float(self.alpha_var.get())
        self.settings.data["hud_alpha"] = a
        self.settings.save()
        if self.hud is not None:
            try:
                self.hud.attributes("-alpha", a)
            except Exception:
                pass

    def _toggle_csv(self):
        v = bool(self.csv_var.get())
        self.settings.data["csv_logging"] = v
        self.settings.save()
        if v and not self.settings.data.get("csv_path"):
            self._choose_csv()
        self._open_csv()

    def _choose_csv(self):
        path = filedialog.asksaveasfilename(
            title="CSV log file",
            defaultextension=".csv",
            initialfile="infotab_log.csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.settings.data["csv_path"] = path
            self.settings.save()
            self._update_csv_label()
            self._open_csv()

    def _update_csv_label(self):
        p = self.settings.data.get("csv_path") or "(not set)"
        self.csv_path_label.config(text=f"CSV path: {p}")

    def _open_csv(self):
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None
            self._log_writer = None

        if not self.settings.data.get("csv_logging"):
            return
        path = self.settings.data.get("csv_path")
        if not path:
            return
        try:
            new = not os.path.exists(path) or os.path.getsize(path) == 0
            self._log_fh = open(path, "a", newline="", encoding="utf-8")
            self._log_writer = csv.writer(self._log_fh)
            if new:
                self._log_writer.writerow(
                    ["timestamp", "fps", "low1", "low01", "app",
                     "ping_ms", "cpu_pct", "ram_pct"])
        except Exception:
            self._log_fh = None
            self._log_writer = None

    # ------------------------------------------------------------------
    #  Theme application
    # ------------------------------------------------------------------
    def apply_theme(self):
        c = self.settings.colors
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=c["bg"], foreground=c["fg"],
                        fieldbackground=c["entry_bg"], bordercolor=c["muted"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("TButton", background=c["panel"], foreground=c["fg"],
                        bordercolor=c["muted"], focuscolor=c["panel"])
        style.map("TButton",
                  background=[("active", c["accent"])],
                  foreground=[("active", c["bg"])])
        style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"])
        style.map("TCheckbutton",
                  background=[("active", c["bg"])],
                  foreground=[("active", c["accent"])])
        style.configure("TEntry", fieldbackground=c["entry_bg"],
                        foreground=c["entry_fg"], insertcolor=c["fg"],
                        bordercolor=c["muted"])
        style.configure("TCombobox", fieldbackground=c["entry_bg"],
                        background=c["panel"], foreground=c["entry_fg"],
                        arrowcolor=c["fg"])
        style.configure("TNotebook", background=c["bg"], bordercolor=c["bg"],
                        tabmargins=(2, 4, 2, 0))
        style.configure("TNotebook.Tab", background=c["panel"],
                        foreground=c["muted"], padding=(12, 6))
        style.map("TNotebook.Tab",
                  background=[("selected", c["bg"]), ("active", c["panel"])],
                  foreground=[("selected", c["accent"]), ("active", c["fg"])])
        style.configure("TSeparator", background=c["muted"])
        style.configure("Horizontal.TProgressbar",
                        background=c["accent"], troughcolor=c["panel"],
                        bordercolor=c["panel"], lightcolor=c["accent"],
                        darkcolor=c["accent"])
        style.configure("Treeview",
                        background=c["entry_bg"], foreground=c["entry_fg"],
                        fieldbackground=c["entry_bg"], bordercolor=c["muted"])
        style.configure("Treeview.Heading",
                        background=c["panel"], foreground=c["fg"])
        style.map("Treeview",
                  background=[("selected", c["accent"])],
                  foreground=[("selected", c["bg"])])

        # text label styles
        style.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"])
        style.configure("Mono.TLabel", background=c["bg"], foreground=c["fg"],
                        font=("Consolas", 10))
        style.configure("Header.TLabel", background=c["bg"], foreground=c["accent"],
                        font=("Arial", 11, "bold"))
        style.configure("Big.TLabel", background=c["bg"], foreground=c["accent"],
                        font=("Consolas", 26, "bold"))
        style.configure("Accent.TLabel", background=c["bg"], foreground=c["fg"],
                        font=("Consolas", 14, "bold"))

        # tk-level widgets
        try:
            self.root.configure(bg=c["bg"])
        except Exception:
            pass
        self.info_scroll.canvas.configure(bg=c["bg"])

        # canvases
        for name, cv in self._canvases:
            try:
                cv.configure(bg=c["graph_bg"], highlightthickness=0)
            except Exception:
                pass

        # clickable link labels
        for lbl in getattr(self, "_link_labels", []):
            try:
                lbl.configure(bg=c["bg"], fg=c["accent"],
                              activebackground=c["bg"], activeforeground=c["fg"])
            except Exception:
                pass

        if self.hud is not None:
            self.hud.refresh_colors()

        # redraw
        self._redraw_graphs()

    def _redraw_graphs(self):
        c = self.settings.colors
        # FPS
        vals = list(self.fps_history)
        if vals:
            hi = max(max(vals), 60) * 1.1
            draw_sparkline(self.fps_canvas, vals, c, lo=0, hi=hi, hline=60)
        else:
            draw_sparkline(self.fps_canvas, [], c)

        # ping
        pv = [v for v in self.ping_samples if v is not None]
        if pv:
            draw_bar_history(self.ping_canvas, pv, c,
                             scale_max=max(max(pv) * 1.15, 50))
        else:
            draw_bar_history(self.ping_canvas, [], c)

    # ------------------------------------------------------------------
    #  GPU panel
    # ------------------------------------------------------------------
    def refresh_gpus(self):
        for w in self.gpu_container.winfo_children():
            w.destroy()
        ttk.Label(self.gpu_container, text="Detecting...",
                  style="Muted.TLabel").pack(anchor="w")
        threading.Thread(target=self._gpu_worker, daemon=True).start()

    def _gpu_worker(self):
        gpus = detect_gpus()
        self.root.after(0, lambda: self._show_gpus(gpus))

    def _show_gpus(self, gpus):
        if not self.running:
            return
        for w in self.gpu_container.winfo_children():
            w.destroy()

        if not gpus:
            ttk.Label(self.gpu_container, text="No GPU information available.",
                      style="Muted.TLabel").pack(anchor="w")
            return

        for gpu in gpus:
            ttk.Label(self.gpu_container, text=gpu["name"],
                      font=("Arial", 10, "bold")).pack(anchor="w", pady=(4, 0))
            bits = []
            if gpu.get("vram"):
                bits.append(f"VRAM: {_fmt_bytes(gpu['vram'])}")
            if gpu.get("driver"):
                bits.append(f"Driver: {gpu['driver']}")
            if bits:
                ttk.Label(self.gpu_container, text="    ".join(bits),
                          style="Muted.TLabel").pack(anchor="w")

    # ------------------------------------------------------------------
    #  Static specs
    # ------------------------------------------------------------------
    def refresh_specs(self):
        threading.Thread(target=self._specs_worker, daemon=True).start()

    def _specs_worker(self):
        name = cpu_name()
        phys, logical = cpu_core_counts()
        self.root.after(0, lambda: self._show_specs(name, phys, logical))

    def _show_specs(self, name, phys, logical):
        if not self.running:
            return
        self.cpu_name_label.config(text=name or "Unknown CPU")
        if phys:
            cores = f"{phys} cores / {logical} threads"
        elif logical:
            cores = f"{logical} logical processors"
        else:
            cores = ""
        self.cpu_cores_label.config(text=cores)

    def refresh_static_extras(self):
        threading.Thread(target=self._static_extras_worker, daemon=True).start()

    def _static_extras_worker(self):
        os_txt = os_caption()
        board = motherboard_info()
        screen, hz = screen_info()
        self.root.after(0, lambda: self._show_static_extras(os_txt, board, screen, hz))

    def _show_static_extras(self, os_txt, board, screen, hz):
        if not self.running:
            return
        self.os_label.config(text=f"OS: {os_txt}")
        self.board_label.config(text=f"Board: {board}" if board else "Board: --")
        if screen:
            extra = f" @ {hz} Hz" if hz else ""
            self.screen_label.config(text=f"Display: {screen}{extra}")
        else:
            self.screen_label.config(text="Display: --")

    # ------------------------------------------------------------------
    #  Live specs loop
    # ------------------------------------------------------------------
    def start_specs_thread(self):
        threading.Thread(target=self._specs_loop, daemon=True).start()

    def _specs_loop(self):
        while self.running:
            pct = self.cpu_meter.percent()
            ram = ram_usage()
            swap = swap_usage()
            disks = disk_usages()
            up = uptime_seconds()
            net = self.net_meter.rate()
            dio = self.disk_meter.rate()
            freq = cpu_freq_mhz()
            load = load_average()
            ipinfo = local_ip()

            # slower extras every ~5 s
            self._slow_tick += 1
            if self._slow_tick % 5 == 1:
                self._slow_data = {
                    "temps": temperatures(),
                    "fans": fans(),
                    "battery": battery_info(),
                    "nvidia": nvidia_smi_stats(),
                    "linux_gpu": linux_amd_intel_gpu_stats() if SYSTEM == "linux" else [],
                }

            payload = dict(pct=pct, ram=ram, swap=swap, disks=disks, up=up,
                           net=net, dio=dio, freq=freq, load=load, ip=ipinfo,
                           slow=dict(self._slow_data))
            self.root.after(0, lambda p=payload: self._update_specs(p))
            time.sleep(1.0)

    def _update_specs(self, p):
        if not self.running:
            return
        c = self.settings.colors

        # CPU
        pct = p["pct"]
        self.last_cpu = pct
        if pct is None:
            self.cpu_usage_label.config(text="Usage: --")
            self.cpu_bar["value"] = 0
        else:
            self.cpu_usage_label.config(text=f"Usage: {pct:5.1f} %")
            self.cpu_bar["value"] = pct

        bits = []
        if p["freq"]:
            bits.append(f"{p['freq']:.0f} MHz")
        if p["load"]:
            bits.append("load " + " ".join(f"{v:.2f}" for v in p["load"]))
        self.cpu_extra_label.config(text="   ".join(bits))

        # RAM
        ram = p["ram"]
        if ram:
            total, used, avail = ram
            pct_ram = (used / total * 100.0) if total else 0.0
            self.last_ram_pct = pct_ram
            self.ram_label.config(
                text=f"{_fmt_bytes(used)} / {_fmt_bytes(total)}  "
                     f"({pct_ram:.0f}% used, {_fmt_bytes(avail)} free)")
            self.ram_bar["value"] = pct_ram
        else:
            self.last_ram_pct = None
            self.ram_label.config(text="Memory information unavailable")
            self.ram_bar["value"] = 0

        sw = p["swap"]
        if sw and sw[0]:
            self.swap_label.config(
                text=f"Swap: {_fmt_bytes(sw[1])} / {_fmt_bytes(sw[0])}")
        else:
            self.swap_label.config(text="")

        # Disks
        for w in self.disk_container.winfo_children():
            w.destroy()
        if p["disks"]:
            for mount, total, used, free in p["disks"]:
                pct_d = (used / total * 100.0) if total else 0.0
                ttk.Label(
                    self.disk_container,
                    text=f"{mount}   {_fmt_bytes(used)} / {_fmt_bytes(total)}  "
                         f"({pct_d:.0f}% used, {_fmt_bytes(free)} free)",
                    style="Mono.TLabel").pack(anchor="w")
        else:
            ttk.Label(self.disk_container, text="Disk: --",
                      style="Mono.TLabel").pack(anchor="w")

        if p["dio"]:
            r, w = p["dio"]
            self.disk_io_label.config(
                text=f"I/O  R {_fmt_rate(r)}   W {_fmt_rate(w)}")
        else:
            self.disk_io_label.config(text="I/O  R --   W --")

        # Net
        if p["net"]:
            up, down = p["net"]
            self.net_rate_label.config(
                text=f"↑ {_fmt_rate(up)}   ↓ {_fmt_rate(down)}")
        else:
            self.net_rate_label.config(text="↑ --   ↓ --")

        if p["ip"]:
            name, addr = p["ip"]
            self.net_ip_label.config(text=f"{name}: {addr}")
        else:
            self.net_ip_label.config(text="")

        # Uptime
        if p["up"] is not None:
            self.uptime_label.config(text=f"Uptime: {_fmt_uptime(p['up'])}")

        # Slow extras
        slow = p["slow"]
        temps = slow.get("temps") or []
        if temps:
            txt = "  ".join(
                f"{lbl}: {cur:.0f}°C" + (f"/{high:.0f}" if high else "")
                for lbl, cur, high in temps[:6])
            self.temps_label.config(text=f"Temps: {txt}")
        else:
            self.temps_label.config(text="Temperatures: --")

        fans_list = slow.get("fans") or []
        if fans_list:
            txt = "  ".join(f"{lbl}: {rpm} RPM" for lbl, rpm in fans_list[:6])
            self.fans_label.config(text=f"Fans: {txt}")
        else:
            self.fans_label.config(text="Fans: --")

        bat = slow.get("battery")
        if bat:
            pct_b, plugged, secs = bat
            state = "charging" if plugged else "on battery"
            if secs and secs > 0 and not plugged:
                state += f", {_fmt_uptime(secs)} left"
            self.battery_label.config(text=f"Battery: {pct_b:.0f}% ({state})")
        else:
            self.battery_label.config(text="Battery: --")

        # Live GPU stats (optional second line under each GPU)
        self._update_live_gpu(slow.get("nvidia") or slow.get("linux_gpu") or [])

        # HUD
        if self.hud is not None and self.hud.winfo_exists():
            self.hud.update_values(None, self.last_ping, pct, self.last_ram_pct)

        # CSV
        if self._log_writer is not None:
            try:
                self._log_writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    f"{self.ui_fps:.1f}" if self.ui_fps else "",
                    f"{self.fps_low1:.1f}" if self.fps_low1 else "",
                    f"{self.fps_low01:.1f}" if self.fps_low01 else "",
                    self.fps_app or "",
                    f"{self.last_ping:.0f}" if self.last_ping is not None else "",
                    f"{pct:.1f}" if pct is not None else "",
                    f"{self.last_ram_pct:.1f}" if self.last_ram_pct is not None else "",
                ])
                self._log_fh.flush()
            except Exception:
                pass

    def _update_live_gpu(self, stats):
        """Append a small live line to the GPU panel if not already there."""
        if not stats:
            return
        # remove previous dynamic lines
        for w in list(self.gpu_container.winfo_children()):
            if getattr(w, "_dynamic_gpu", False):
                w.destroy()
        for s in stats:
            bits = []
            if s.get("util") is not None:
                bits.append(f"GPU {s['util']:.0f}%")
            if s.get("vram_used_mb") and s.get("vram_total_mb"):
                bits.append(f"VRAM {s['vram_used_mb']:.0f}/{s['vram_total_mb']:.0f} MB")
            if s.get("temp") is not None:
                bits.append(f"{s['temp']:.0f}°C")
            if s.get("fan") is not None:
                bits.append(f"fan {s['fan']:.0f}%")
            if not bits:
                continue
            lbl = ttk.Label(self.gpu_container,
                            text=f"    live: {'   '.join(bits)}",
                            style="Muted.TLabel")
            lbl._dynamic_gpu = True
            lbl.pack(anchor="w")

    # ------------------------------------------------------------------
    #  FPS
    # ------------------------------------------------------------------
    def tick(self):
        if not self.running:
            return
        self.frame_count += 1
        self.root.after(16, self.tick)

    def update_fps(self):
        if not self.running:
            return

        now = time.time()
        elapsed = now - self.fps_start
        if elapsed >= 1.0:
            self.ui_fps = self.frame_count / elapsed
            self.frame_count = 0
            self.fps_start = now

        game_fps, low1, low01, game_name = self.fps_monitor.get_fps_stats()
        self.fps_low1 = low1
        self.fps_low01 = low01
        self.fps_app = game_name

        if game_fps is not None:
            self.fps_label.config(text=f"{game_fps:.0f}")
            src = f"Game: {game_name}"
            self.fps_history.append(game_fps)
        else:
            self.fps_label.config(text=f"{self.ui_fps:.0f}")
            self.fps_history.append(self.ui_fps)
            if not self.fps_monitor.available:
                src = "UI refresh rate (no PresentMon found)"
            else:
                src = "No game detected - UI refresh rate"

        self.fps_source_label.config(text=src)

        if low1 is not None and low01 is not None:
            self.fps_lows_label.config(
                text=f"1% {low1:5.0f}   0.1% {low01:5.0f}")
        else:
            self.fps_lows_label.config(text="1% --    0.1% --")

        self._redraw_graphs()

        if self.hud is not None and self.hud.winfo_exists():
            self.hud.update_values(game_fps if game_fps is not None else self.ui_fps,
                                   self.last_ping, self.last_cpu, self.last_ram_pct)

        self.root.after(500, self.update_fps)

    # ------------------------------------------------------------------
    #  Ping
    # ------------------------------------------------------------------
    def _on_host_changed(self, *_):
        self.ping_host = self.host_var.get().strip() or "8.8.8.8"
        self.settings.data["ping_host"] = self.ping_host
        self.settings.save()

    def start_ping_thread(self):
        threading.Thread(target=self.ping_loop, daemon=True).start()

    def ping_loop(self):
        while self.running:
            host = self.ping_host
            ping_time = self.get_ping(host)
            self.ping_samples.append(ping_time if ping_time is not None else 0.0)
            self.ping_loss.append(1 if ping_time is None else 0)
            self.last_ping = ping_time

            text = f"{ping_time:.0f} ms" if ping_time is not None else "Timeout"
            detail = self._ping_detail()
            self.root.after(0, lambda t=text, d=detail: self._update_ping(t, d))
            time.sleep(2)

    def _ping_detail(self):
        vals = [v for v in self.ping_samples if v]
        if not vals:
            return ""
        avg = sum(vals) / len(vals)
        jitter = 0.0
        if len(vals) > 1:
            jitter = sum(abs(vals[i] - vals[i - 1])
                         for i in range(1, len(vals))) / (len(vals) - 1)
        loss = (sum(self.ping_loss) / max(len(self.ping_loss), 1)) * 100.0
        return (f"avg {avg:.0f}  jit {jitter:.1f}  "
                f"min {min(vals):.0f} / max {max(vals):.0f}  "
                f"loss {loss:.0f}%")

    def _update_ping(self, text, detail):
        if not self.running:
            return
        self.ping_label.config(text=text)
        self.ping_detail_label.config(text=detail)
        self._redraw_graphs()

    def get_ping(self, host):
        try:
            is_win = SYSTEM == "windows"
            param = "-n" if is_win else "-c"
            timeout_param = "-w" if is_win else "-W"
            timeout_val = "2000" if is_win else "2"

            result = subprocess.run(
                ["ping", param, "1", timeout_param, timeout_val, host],
                capture_output=True, text=True, timeout=5, **_hidden_kwargs())

            match = re.search(r"time[=<]\s*([\d.]+)\s*ms",
                              result.stdout, re.IGNORECASE)
            if match:
                return float(match.group(1))
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    #  HUD
    # ------------------------------------------------------------------
    def toggle_hud(self, on):
        self.settings.data["compact_hud"] = bool(on)
        self.settings.save()
        if on:
            if self.hud is None or not self.hud.winfo_exists():
                self.hud = HudWindow(self.root, self)
        else:
            if self.hud is not None and self.hud.winfo_exists():
                self.hud.destroy()
            self.hud = None

    # ------------------------------------------------------------------
    #  Report
    # ------------------------------------------------------------------
    def build_report(self):
        lines = ["=== InfoTab report ===",
                 f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                 f"OS: {self.os_label.cget('text')}",
                 f"Board: {self.board_label.cget('text')}",
                 f"Display: {self.screen_label.cget('text')}",
                 f"CPU: {self.cpu_name_label.cget('text')}",
                 f"Cores: {self.cpu_cores_label.cget('text')}",
                 f"CPU usage: {self.cpu_usage_label.cget('text')}",
                 f"Memory: {self.ram_label.cget('text')}",
                 f"Swap: {self.swap_label.cget('text')}",
                 f"Uptime: {self.uptime_label.cget('text')}",
                 f"Network: {self.net_rate_label.cget('text')}  {self.net_ip_label.cget('text')}",
                 f"Disk I/O: {self.disk_io_label.cget('text')}",
                 f"Temps: {self.temps_label.cget('text')}",
                 f"Fans: {self.fans_label.cget('text')}",
                 f"Battery: {self.battery_label.cget('text')}",
                 "",
                 "Disks:"]
        for w in self.disk_container.winfo_children():
            try:
                lines.append("  " + w.cget("text"))
            except Exception:
                pass
        lines.append("")
        lines.append("GPUs:")
        for w in self.gpu_container.winfo_children():
            try:
                lines.append("  " + w.cget("text"))
            except Exception:
                pass
        lines.append("")
        lines.append(f"InfoTab v{VERSION} - owner: {OWNER}")
        lines.append("Do not steal, copy, or redistribute this code.")
        return "\n".join(lines)

    def copy_report(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.build_report())
            self.root.update()
            messagebox.showinfo("InfoTab", "Report copied to clipboard.")
        except Exception as e:
            messagebox.showerror("InfoTab", f"Copy failed: {e}")

    def save_report(self):
        path = filedialog.asksaveasfilename(
            title="Save report",
            defaultextension=".txt",
            initialfile="infotab_report.txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.build_report())
            messagebox.showinfo("InfoTab", f"Saved to {path}")
        except Exception as e:
            messagebox.showerror("InfoTab", f"Save failed: {e}")

    # ------------------------------------------------------------------
    #  Shutdown
    # ------------------------------------------------------------------
    def on_close(self):
        self.running = False
        try:
            self.fps_monitor.stop()
        except Exception:
            pass
        if self.hud is not None:
            try:
                self.hud.destroy()
            except Exception:
                pass
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except Exception:
                pass
        try:
            self.settings.save()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SystemInfoTab(root)
    root.mainloop()