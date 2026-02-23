import datetime as dt
import getpass
import json
import math
import os
import platform
import socket
import sys
import time
from typing import Any, Iterable, List, Sequence

import psutil
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas


def ensure_dirs() -> None:
    os.makedirs("output/pdf", exist_ok=True)
    os.makedirs("tmp/pdfs", exist_ok=True)


def fmt_bytes(n: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    n = float(n)
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return f"{int(n)} {units[i]}"
    return f"{n:.1f} {units[i]}"


def fmt_rate(n: float) -> str:
    return f"{fmt_bytes(n)}/s"


def fmt_percent(v: float) -> str:
    return f"{v:.1f}%"


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts: List[str] = []
    if d:
        parts.append(f"{d}d")
    if h or d:
        parts.append(f"{h}h")
    if m or h or d:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def choose_disk_path() -> str:
    drive, _ = os.path.splitdrive(os.getcwd())
    if drive:
        return drive + "\\"
    return "/"


def safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def sample_processes() -> List[dict[str, Any]]:
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except Exception:
            continue
    time.sleep(0.18)

    rows: List[dict[str, Any]] = []
    for p in procs:
        try:
            info = p.info
            name = info.get("name") or "unknown"
            rss = getattr(info.get("memory_info"), "rss", 0) or 0
            rows.append(
                {
                    "pid": p.pid,
                    "name": name,
                    "cpu": float(p.cpu_percent(None)),
                    "rss": int(rss),
                }
            )
        except Exception:
            continue

    rows.sort(key=lambda r: (r["cpu"], r["rss"]), reverse=True)
    return rows[:8]


def read_temp_sensors() -> list[tuple[str, float]]:
    vals: list[tuple[str, float]] = []
    if not hasattr(psutil, "sensors_temperatures"):
        return vals
    raw = safe_call(lambda: psutil.sensors_temperatures(), {}) or {}
    for name, entries in raw.items():
        for e in entries:
            cur = getattr(e, "current", None)
            label = getattr(e, "label", "") or name
            if cur is None:
                continue
            vals.append((label, float(cur)))
    vals.sort(key=lambda t: t[1], reverse=True)
    return vals[:6]


def collect_monitor_data(sample_seconds: float = 8.0, interval: float = 0.5) -> dict[str, Any]:
    # Prime psutil percentage samplers.
    safe_call(lambda: psutil.cpu_percent(None, percpu=True), [])
    vm0 = safe_call(psutil.virtual_memory)
    swap0 = safe_call(psutil.swap_memory)
    net_prev = safe_call(psutil.net_io_counters)
    disk_prev = safe_call(psutil.disk_io_counters)
    batt_prev = safe_call(psutil.sensors_battery)

    samples: List[dict[str, Any]] = []
    n = max(4, int(sample_seconds / interval))
    start = time.time()

    for i in range(n):
        time.sleep(interval)
        t = time.time() - start
        per_core = safe_call(lambda: psutil.cpu_percent(None, percpu=True), []) or []
        cpu_avg = float(sum(per_core) / len(per_core)) if per_core else float(safe_call(lambda: psutil.cpu_percent(None), 0.0) or 0.0)
        vm = safe_call(psutil.virtual_memory, vm0)
        swap = safe_call(psutil.swap_memory, swap0)

        net_now = safe_call(psutil.net_io_counters, net_prev)
        disk_now = safe_call(psutil.disk_io_counters, disk_prev)
        batt = safe_call(psutil.sensors_battery, batt_prev)

        net_send_rate = 0.0
        net_recv_rate = 0.0
        if net_prev and net_now:
            net_send_rate = max(0.0, (net_now.bytes_sent - net_prev.bytes_sent) / interval)
            net_recv_rate = max(0.0, (net_now.bytes_recv - net_prev.bytes_recv) / interval)
        disk_read_rate = 0.0
        disk_write_rate = 0.0
        if disk_prev and disk_now:
            disk_read_rate = max(0.0, (disk_now.read_bytes - disk_prev.read_bytes) / interval)
            disk_write_rate = max(0.0, (disk_now.write_bytes - disk_prev.write_bytes) / interval)

        net_prev = net_now or net_prev
        disk_prev = disk_now or disk_prev
        batt_prev = batt or batt_prev

        samples.append(
            {
                "t": t,
                "cpu": cpu_avg,
                "per_core": [float(v) for v in per_core[:12]],
                "mem": float(getattr(vm, "percent", 0.0) or 0.0),
                "swap": float(getattr(swap, "percent", 0.0) or 0.0),
                "net_up": net_send_rate,
                "net_down": net_recv_rate,
                "disk_read": disk_read_rate,
                "disk_write": disk_write_rate,
                "battery_pct": None if not batt else float(batt.percent),
                "battery_plugged": None if not batt else bool(batt.power_plugged),
            }
        )

    hostname = socket.gethostname()
    username = safe_call(getpass.getuser, "user")
    uname = platform.uname()
    boot_ts = safe_call(psutil.boot_time)
    now = dt.datetime.now()
    boot_dt = dt.datetime.fromtimestamp(boot_ts) if boot_ts else None
    uptime = (time.time() - boot_ts) if boot_ts else 0.0

    cpu_freq = safe_call(psutil.cpu_freq)
    vm = safe_call(psutil.virtual_memory, vm0)
    swap = safe_call(psutil.swap_memory, swap0)
    disk_path = choose_disk_path()
    disk_usage = safe_call(lambda: psutil.disk_usage(disk_path))
    net_total = safe_call(psutil.net_io_counters)
    disk_total = safe_call(psutil.disk_io_counters)
    battery = safe_call(psutil.sensors_battery)

    temps = read_temp_sensors()
    processes = sample_processes()

    latest = samples[-1] if samples else {}
    cpu_series = [s["cpu"] for s in samples]
    mem_series = [s["mem"] for s in samples]
    down_series = [s["net_down"] for s in samples]
    up_series = [s["net_up"] for s in samples]
    disk_rw_series = [s["disk_read"] + s["disk_write"] for s in samples]

    alerts: list[dict[str, Any]] = []

    def add_alert(level: str, msg: str) -> None:
        alerts.append({"level": level, "msg": msg})

    if latest.get("cpu", 0) >= 85:
        add_alert("warn", f"High CPU load: {latest['cpu']:.1f}%")
    if latest.get("mem", 0) >= 85:
        add_alert("warn", f"High memory use: {latest['mem']:.1f}%")
    if disk_usage and disk_usage.percent >= 90:
        add_alert("warn", f"Low disk space on {disk_path}: {disk_usage.percent:.1f}% used")
    if battery:
        if (not battery.power_plugged) and battery.percent <= 20:
            add_alert("warn", f"Battery low: {battery.percent:.0f}% and unplugged")
        elif battery.power_plugged and battery.percent >= 98:
            add_alert("info", f"Battery near full: {battery.percent:.0f}%")
    if samples and (sum(cpu_series) / len(cpu_series)) >= 70:
        add_alert("info", f"Average CPU over sample window: {sum(cpu_series)/len(cpu_series):.1f}%")
    if not alerts:
        add_alert("ok", "No threshold alerts in this sample window")

    return {
        "generated_at": now,
        "hostname": hostname,
        "username": username,
        "platform": {
            "system": uname.system,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine,
            "processor": uname.processor or platform.processor(),
        },
        "boot_dt": boot_dt,
        "uptime": uptime,
        "python": sys.version.split()[0],
        "cpu": {
            "physical": safe_call(psutil.cpu_count, 0),
            "logical": safe_call(lambda: psutil.cpu_count(logical=True), 0),
            "freq_current": None if not cpu_freq else getattr(cpu_freq, "current", None),
            "freq_max": None if not cpu_freq else getattr(cpu_freq, "max", None),
            "per_core_latest": latest.get("per_core", []),
        },
        "memory": {
            "total": 0 if not vm else int(vm.total),
            "available": 0 if not vm else int(vm.available),
            "used": 0 if not vm else int(vm.used),
            "percent": 0.0 if not vm else float(vm.percent),
        },
        "swap": {
            "total": 0 if not swap else int(getattr(swap, "total", 0)),
            "used": 0 if not swap else int(getattr(swap, "used", 0)),
            "percent": 0.0 if not swap else float(getattr(swap, "percent", 0.0)),
        },
        "disk": {
            "path": disk_path,
            "total": 0 if not disk_usage else int(disk_usage.total),
            "used": 0 if not disk_usage else int(disk_usage.used),
            "free": 0 if not disk_usage else int(disk_usage.free),
            "percent": 0.0 if not disk_usage else float(disk_usage.percent),
            "read_total": 0 if not disk_total else int(getattr(disk_total, "read_bytes", 0)),
            "write_total": 0 if not disk_total else int(getattr(disk_total, "write_bytes", 0)),
        },
        "network": {
            "bytes_sent": 0 if not net_total else int(net_total.bytes_sent),
            "bytes_recv": 0 if not net_total else int(net_total.bytes_recv),
        },
        "battery": None
        if not battery
        else {
            "percent": float(battery.percent),
            "plugged": bool(battery.power_plugged),
            "secsleft": None if battery.secsleft in (None, psutil.POWER_TIME_UNKNOWN) else int(battery.secsleft),
        },
        "temps": temps,
        "samples": samples,
        "series": {
            "cpu": cpu_series,
            "mem": mem_series,
            "net_up": up_series,
            "net_down": down_series,
            "disk_rw": disk_rw_series,
        },
        "alerts": alerts,
        "processes": processes,
        "sample_window": sample_seconds,
        "interval": interval,
    }


def blend(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> colors.Color:
    t = max(0.0, min(1.0, t))
    r = int(c1[0] + (c2[0] - c1[0]) * t)
    g = int(c1[1] + (c2[1] - c1[1]) * t)
    b = int(c1[2] + (c2[2] - c1[2]) * t)
    return colors.Color(r / 255, g / 255, b / 255)


def draw_bg(c: canvas.Canvas, w: float, h: float) -> None:
    top = (8, 20, 42)
    bottom = (2, 6, 14)
    bands = 24
    for i in range(bands):
        y = h * (1 - (i + 1) / bands)
        c.setFillColor(blend(top, bottom, i / max(1, bands - 1)))
        c.rect(0, y, w, h / bands + 1, stroke=0, fill=1)


def card(c: canvas.Canvas, x: float, y: float, w: float, h: float, title: str, subtitle: str | None = None) -> None:
    c.setFillColor(colors.Color(0.02, 0.04, 0.08))
    c.setStrokeColor(colors.Color(0.17, 0.30, 0.47))
    c.roundRect(x, y, w, h, 12, stroke=1, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x + 12, y + h - 20, title)
    if subtitle:
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.Color(0.76, 0.86, 0.95))
        c.drawString(x + 12, y + h - 32, subtitle)


def text_rows(
    c: canvas.Canvas,
    x: float,
    y_top: float,
    rows: Sequence[tuple[str, str]],
    *,
    line_h: float = 14,
    key_w: float = 92,
) -> None:
    for i, (k, v) in enumerate(rows):
        yy = y_top - i * line_h
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(colors.Color(0.84, 0.92, 0.98))
        c.drawString(x, yy, f"{k}:")
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.Color(0.70, 0.84, 0.95))
        c.drawString(x + key_w, yy, v)


def usage_bar(c: canvas.Canvas, x: float, y: float, w: float, label: str, value: float, color_rgb: tuple[int, int, int]) -> None:
    value = max(0.0, min(100.0, value))
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.Color(0.86, 0.93, 0.99))
    c.drawString(x, y + 10, label)
    c.setFont("Helvetica", 8)
    c.drawRightString(x + w, y + 10, fmt_percent(value))

    c.setFillColor(colors.Color(0.04, 0.08, 0.14))
    c.setStrokeColor(colors.Color(0.14, 0.24, 0.37))
    c.roundRect(x, y - 2, w, 8, 4, stroke=1, fill=1)
    fill_w = (w - 2) * value / 100.0
    c.setFillColor(colors.Color(color_rgb[0] / 255, color_rgb[1] / 255, color_rgb[2] / 255))
    c.roundRect(x + 1, y - 1, fill_w, 6, 3, stroke=0, fill=1)


def mini_line_chart(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    series_list: Sequence[Sequence[float]],
    colors_list: Sequence[colors.Color],
    labels: Sequence[str],
    *,
    y_max: float | None = None,
    y_min: float = 0.0,
    percent_scale: bool = False,
) -> None:
    c.setFillColor(colors.Color(0.01, 0.03, 0.07))
    c.setStrokeColor(colors.Color(0.13, 0.24, 0.37))
    c.roundRect(x, y, w, h, 8, stroke=1, fill=1)
    c.setStrokeColor(colors.Color(0.07, 0.21, 0.34))
    c.setLineWidth(0.5)
    for i in range(1, 5):
        gy = y + h * i / 5
        c.line(x + 28, gy, x + w - 8, gy)
    for i in range(1, 7):
        gx = x + 28 + (w - 36) * i / 7
        c.line(gx, y + 10, gx, y + h - 10)
    c.setStrokeColor(colors.Color(0.45, 0.63, 0.82))
    c.line(x + 28, y + 10, x + 28, y + h - 10)
    c.line(x + 28, y + 10, x + w - 8, y + 10)

    all_vals = [float(v) for s in series_list for v in s]
    if y_max is None:
        y_max = max(all_vals) if all_vals else 1.0
        if y_max <= y_min:
            y_max = y_min + 1.0
        if not percent_scale:
            y_max *= 1.15
    if percent_scale:
        y_max = max(100.0, y_max)

    plot_x = x + 28
    plot_y = y + 10
    plot_w = w - 36
    plot_h = h - 20

    def map_pt(i: int, n: int, v: float) -> tuple[float, float]:
        px = plot_x + (0 if n <= 1 else plot_w * i / (n - 1))
        t = (float(v) - y_min) / max(1e-9, (y_max - y_min))
        py = plot_y + plot_h * max(0.0, min(1.0, t))
        return px, py

    for s, col in zip(series_list, colors_list):
        if not s:
            continue
        p = c.beginPath()
        for i, v in enumerate(s):
            px, py = map_pt(i, len(s), float(v))
            if i == 0:
                p.moveTo(px, py)
            else:
                p.lineTo(px, py)
        c.setStrokeColor(col)
        c.setLineWidth(1.6)
        c.drawPath(p, stroke=1, fill=0)

    # legend
    lx = x + 8
    ly = y + h - 12
    for i, (lab, col) in enumerate(zip(labels, colors_list)):
        yy = ly - i * 10
        c.setStrokeColor(col)
        c.setLineWidth(2)
        c.line(lx, yy, lx + 10, yy)
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.Color(0.80, 0.89, 0.96))
        c.drawString(lx + 14, yy - 2, lab)

    c.setFont("Helvetica", 7)
    c.setFillColor(colors.Color(0.76, 0.85, 0.94))
    if percent_scale:
        c.drawRightString(x + w - 10, y + h - 12, "0-100%")
    else:
        c.drawRightString(x + w - 10, y + h - 12, f"max {fmt_rate(y_max)}" if y_max > 0 else "max 0")


def draw_alert_list(c: canvas.Canvas, x: float, y: float, w: float, alerts: Sequence[dict[str, Any]]) -> None:
    palette = {
        "warn": (colors.Color(0.92, 0.36, 0.30), colors.Color(0.30, 0.07, 0.06)),
        "info": (colors.Color(0.20, 0.75, 0.95), colors.Color(0.03, 0.12, 0.19)),
        "ok": (colors.Color(0.24, 0.84, 0.52), colors.Color(0.03, 0.14, 0.09)),
    }
    line_h = 20
    max_rows = 5
    for i, a in enumerate(alerts[:max_rows]):
        yy = y - i * line_h
        lvl = a.get("level", "info")
        fg, bg = palette.get(lvl, palette["info"])
        c.setFillColor(bg)
        c.setStrokeColor(colors.Color(0.15, 0.24, 0.34))
        c.roundRect(x, yy - 13, w, 16, 4, stroke=1, fill=1)
        c.setFillColor(fg)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x + 6, yy - 2, lvl.upper())
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.Color(0.86, 0.93, 0.99))
        c.drawString(x + 34, yy - 2, str(a.get("msg", ""))[:64])


def draw_per_core_bars(c: canvas.Canvas, x: float, y: float, w: float, h: float, per_core: Sequence[float]) -> None:
    if not per_core:
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.Color(0.78, 0.87, 0.95))
        c.drawString(x + 8, y + h - 16, "Per-core data unavailable")
        return
    n = len(per_core)
    cols = 4
    rows = math.ceil(n / cols)
    cell_w = (w - 10) / cols
    cell_h = (h - 12) / rows
    for idx, v in enumerate(per_core):
        col = idx % cols
        row = idx // cols
        cx = x + 5 + col * cell_w
        cy = y + h - (row + 1) * cell_h + 2
        label = f"C{idx}"
        usage_bar(c, cx, cy + 5, cell_w - 10, label, float(v), (64, 210, 255))


def draw_process_table(c: canvas.Canvas, x: float, y: float, w: float, h: float, procs: Sequence[dict[str, Any]]) -> None:
    c.setFillColor(colors.Color(0.01, 0.03, 0.07))
    c.setStrokeColor(colors.Color(0.13, 0.24, 0.37))
    c.roundRect(x, y, w, h, 8, stroke=1, fill=1)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.Color(0.84, 0.92, 0.98))
    c.drawString(x + 8, y + h - 12, "PID")
    c.drawString(x + 48, y + h - 12, "Process")
    c.drawRightString(x + w - 62, y + h - 12, "CPU%")
    c.drawRightString(x + w - 8, y + h - 12, "RSS")

    row_h = 16
    for i, p in enumerate(procs[:8]):
        yy = y + h - 28 - i * row_h
        if yy < y + 6:
            break
        if i % 2 == 0:
            c.setFillColor(colors.Color(0.02, 0.05, 0.09))
            c.rect(x + 4, yy - 10, w - 8, row_h - 1, stroke=0, fill=1)
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.Color(0.75, 0.86, 0.95))
        c.drawString(x + 8, yy, str(p.get("pid", "")))
        name = str(p.get("name", ""))[:18]
        c.drawString(x + 48, yy, name)
        c.drawRightString(x + w - 62, yy, f"{float(p.get('cpu', 0.0)):.1f}")
        c.drawRightString(x + w - 8, yy, fmt_bytes(int(p.get("rss", 0))))


def draw_sensor_rows(c: canvas.Canvas, x: float, y_top: float, data: dict[str, Any]) -> None:
    rows: List[tuple[str, str]] = []
    batt = data.get("battery")
    if batt:
        batt_txt = f"{batt['percent']:.0f}% ({'plugged' if batt['plugged'] else 'battery'})"
        if batt.get("secsleft") is not None:
            batt_txt += f", {fmt_duration(int(batt['secsleft']))} left"
        rows.append(("Battery", batt_txt))
    else:
        rows.append(("Battery", "Not available"))

    temps = data.get("temps", [])
    if temps:
        rows.append(("Temp 1", f"{temps[0][0]}: {temps[0][1]:.1f} C"))
        if len(temps) > 1:
            rows.append(("Temp 2", f"{temps[1][0]}: {temps[1][1]:.1f} C"))
    else:
        rows.append(("Temps", "Not available via psutil on this system"))

    net = data["network"]
    rows.append(("Net Sent", fmt_bytes(net["bytes_sent"])))
    rows.append(("Net Recv", fmt_bytes(net["bytes_recv"])))
    rows.append(("Disk Read", fmt_bytes(data["disk"]["read_total"])))
    rows.append(("Disk Write", fmt_bytes(data["disk"]["write_total"])))
    text_rows(c, x, y_top, rows, line_h=13, key_w=62)


def render_pdf_dashboard(data: dict[str, Any], out_path: str) -> None:
    ensure_dirs()
    width, height = landscape(letter)
    c = canvas.Canvas(out_path, pagesize=(width, height))
    c.setTitle("PC Usage Monitor PDF Dashboard")
    c.setAuthor("Codex")
    c.setSubject("PC usage, sensor snapshot, and Acrobat notification popup")

    draw_bg(c, width, height)

    # Outer shell
    c.setFillColor(colors.Color(0.01, 0.03, 0.06))
    c.setStrokeColor(colors.Color(0.18, 0.32, 0.50))
    c.roundRect(16, 16, width - 32, height - 32, 14, stroke=1, fill=1)

    # Header
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(30, height - 40, "PC Monitor Dashboard PDF (Notifications + Usage + Sensor Snapshot)")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.Color(0.76, 0.86, 0.95))
    gen_local = data["generated_at"].strftime("%Y-%m-%d %H:%M:%S")
    c.drawString(30, height - 54, f"Generated: {gen_local} | Sample window: {data['sample_window']:.1f}s | Interval: {data['interval']:.2f}s")
    c.drawString(30, height - 66, "PDFs cannot stream real-time OS telemetry in normal viewers. This page shows a fresh sampled snapshot. Re-run the generator to refresh.")
    c.drawString(30, height - 78, "Acrobat/Reader may show a popup notification on open (document JavaScript). Other viewers may ignore it.")

    # Layout
    left = 24
    bottom = 24
    gutter = 10
    inner_w = width - 48
    top_y = height - 88

    top_h = 152
    top_y0 = top_y - top_h
    col_w = (inner_w - 2 * gutter) / 3
    x1 = left
    x2 = left + col_w + gutter
    x3 = left + 2 * (col_w + gutter)

    card(c, x1, top_y0, col_w, top_h, "System Info", "Host, OS, uptime, hardware")
    card(c, x2, top_y0, col_w, top_h, "Current Usage", "CPU, memory, swap, disk usage")
    card(c, x3, top_y0, col_w, top_h, "Notifications", "Threshold status and PDF popup support")

    # System info rows
    p = data["platform"]
    cpu = data["cpu"]
    mem = data["memory"]
    disk = data["disk"]
    info_rows = [
        ("Host", data["hostname"]),
        ("User", data["username"]),
        ("OS", f"{p['system']} {p['release']}"),
        ("Machine", p["machine"] or "-"),
        ("Uptime", fmt_duration(data["uptime"])),
        ("CPU", f"{cpu['logical']} logical / {cpu['physical']} physical"),
        ("CPU Freq", "-" if not cpu["freq_current"] else f"{cpu['freq_current']:.0f} MHz"),
        ("Memory", f"{fmt_bytes(mem['used'])} / {fmt_bytes(mem['total'])}"),
        ("Disk", f"{disk['path']} {fmt_bytes(disk['used'])} / {fmt_bytes(disk['total'])}"),
    ]
    text_rows(c, x1 + 12, top_y0 + top_h - 44, info_rows, line_h=12, key_w=72)

    # Usage bars
    latest = data["samples"][-1] if data["samples"] else {"cpu": 0, "mem": 0, "swap": 0}
    usage_bar(c, x2 + 12, top_y0 + top_h - 56, col_w - 24, "CPU", float(latest.get("cpu", 0)), (54, 195, 255))
    usage_bar(c, x2 + 12, top_y0 + top_h - 82, col_w - 24, "Memory", float(latest.get("mem", 0)), (70, 240, 145))
    usage_bar(c, x2 + 12, top_y0 + top_h - 108, col_w - 24, "Swap", float(latest.get("swap", 0)), (255, 170, 70))
    usage_bar(c, x2 + 12, top_y0 + top_h - 134, col_w - 24, "Disk Used", float(data["disk"]["percent"]), (255, 95, 95))

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.Color(0.75, 0.86, 0.95))
    if data.get("battery"):
        batt = data["battery"]
        c.drawString(x2 + 12, top_y0 + 14, f"Battery: {batt['percent']:.0f}% ({'plugged' if batt['plugged'] else 'on battery'})")
    else:
        c.drawString(x2 + 12, top_y0 + 14, "Battery: Not available")

    # Notifications panel
    draw_alert_list(c, x3 + 12, top_y0 + top_h - 48, col_w - 24, data["alerts"])
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.Color(0.82, 0.91, 0.97))
    c.drawString(x3 + 12, top_y0 + 54, "Notification behavior:")
    c.drawString(x3 + 20, top_y0 + 42, "- Acrobat/Reader may show popup on open")
    c.drawString(x3 + 20, top_y0 + 30, "- Most browsers ignore PDF JavaScript")
    c.drawString(x3 + 20, top_y0 + 18, "- For true live monitoring, use a companion app/script")

    # Bottom layout
    bottom_y = bottom
    bottom_h = top_y0 - bottom_y - 10
    left_w = col_w * 2 + gutter
    right_w = col_w
    bx1 = left
    bx2 = left + left_w + gutter

    # Left big trends card
    card(c, bx1, bottom_y, left_w, bottom_h, "Usage Trends", "Recent sampled telemetry over the capture window")
    inner_x = bx1 + 12
    inner_y = bottom_y + 12
    inner_w2 = left_w - 24
    inner_h2 = bottom_h - 40

    chart_h = (inner_h2 - 2 * 8) / 3
    mini_line_chart(
        c,
        inner_x,
        inner_y + 2 * (chart_h + 8),
        inner_w2,
        chart_h,
        [data["series"]["cpu"], data["series"]["mem"]],
        [colors.Color(0.24, 0.86, 1.0), colors.Color(0.22, 0.95, 0.56)],
        ["CPU%", "Mem%"],
        percent_scale=True,
    )
    mini_line_chart(
        c,
        inner_x,
        inner_y + (chart_h + 8),
        inner_w2,
        chart_h,
        [data["series"]["net_down"], data["series"]["net_up"]],
        [colors.Color(0.35, 0.75, 1.0), colors.Color(1.0, 0.68, 0.30)],
        ["Net Down", "Net Up"],
    )
    mini_line_chart(
        c,
        inner_x,
        inner_y,
        inner_w2,
        chart_h,
        [data["series"]["disk_rw"]],
        [colors.Color(0.95, 0.42, 0.40)],
        ["Disk R+W"],
    )

    # Right stacked cards
    right_top_h = bottom_h * 0.48
    right_bottom_h = bottom_h - right_top_h - gutter
    card(c, bx2, bottom_y + bottom_h - right_top_h, right_w, right_top_h, "Sensors / Totals", "Battery, temps, network and disk totals")
    card(c, bx2, bottom_y, right_w, right_bottom_h, "Top Processes", "CPU snapshot + memory RSS")

    # Sensors and per-core split inside top-right card
    rt_x = bx2 + 12
    rt_y = bottom_y + bottom_h - right_top_h + 12
    rt_w = right_w - 24
    rt_h = right_top_h - 40
    upper_h = rt_h * 0.56
    lower_h = rt_h - upper_h - 6

    c.setFillColor(colors.Color(0.01, 0.03, 0.07))
    c.setStrokeColor(colors.Color(0.13, 0.24, 0.37))
    c.roundRect(rt_x, rt_y + rt_h - upper_h, rt_w, upper_h, 8, stroke=1, fill=1)
    draw_sensor_rows(c, rt_x + 8, rt_y + rt_h - 14, data)

    c.setFillColor(colors.Color(0.01, 0.03, 0.07))
    c.setStrokeColor(colors.Color(0.13, 0.24, 0.37))
    c.roundRect(rt_x, rt_y, rt_w, lower_h, 8, stroke=1, fill=1)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.Color(0.84, 0.92, 0.98))
    c.drawString(rt_x + 8, rt_y + lower_h - 12, "Per-Core CPU (latest sample)")
    draw_per_core_bars(c, rt_x + 6, rt_y + 6, rt_w - 12, lower_h - 22, data["cpu"]["per_core_latest"])

    # Process table
    draw_process_table(c, bx2 + 12, bottom_y + 12, right_w - 24, right_bottom_h - 24, data["processes"])

    c.showPage()
    c.save()


def add_open_notification_js(pdf_in: str, pdf_out: str, data: dict[str, Any]) -> None:
    latest = data["samples"][-1] if data["samples"] else {}
    summary_lines = [
        "PC Monitor Snapshot",
        f"Generated: {data['generated_at'].strftime('%Y-%m-%d %H:%M:%S')}",
        f"CPU: {latest.get('cpu', 0):.1f}%",
        f"Memory: {latest.get('mem', 0):.1f}%",
        f"Disk Used: {data['disk']['percent']:.1f}%",
        "Alerts:",
    ]
    for a in data["alerts"][:3]:
        summary_lines.append(f"- {a['level'].upper()}: {a['msg']}")
    if len(summary_lines) == 6:
        summary_lines.append("- OK")

    msg = "\\n".join(summary_lines)
    js = (
        "try {"
        "app.alert({cTitle:'System Monitor PDF', cMsg:"
        + json.dumps(msg)
        + ", nIcon:3});"
        "} catch (e) {}"
    )

    reader = PdfReader(pdf_in)
    writer = PdfWriter()
    writer.append(reader)
    writer.add_js(js)
    # pypdf stores JS in the catalog name tree, but this version does not create
    # a catalog OpenAction. Add one so Acrobat/Reader can run the popup on open.
    js_action = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Action"),
            NameObject("/S"): NameObject("/JavaScript"),
            NameObject("/JS"): TextStringObject(js),
        }
    )
    js_action_ref = writer._add_object(js_action)
    writer._root_object[NameObject("/OpenAction")] = js_action_ref
    with open(pdf_out, "wb") as f:
        writer.write(f)


def main() -> None:
    ensure_dirs()
    data = collect_monitor_data(sample_seconds=8.0, interval=0.5)

    raw_path = os.path.join("output", "pdf", "pc_monitor_dashboard_raw.pdf")
    out_path = os.path.join("output", "pdf", "pc_monitor_dashboard_notifications.pdf")
    render_pdf_dashboard(data, raw_path)
    add_open_notification_js(raw_path, out_path, data)

    print(f"Created raw PDF: {raw_path}")
    print(f"Created notification PDF: {out_path}")


if __name__ == "__main__":
    main()
