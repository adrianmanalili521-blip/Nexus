import sys
import re
import csv
import time
import math
import socket
import statistics
import subprocess
import threading
from datetime import datetime
from collections import deque

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QLineEdit,
    QComboBox, QSpinBox, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
    QPlainTextEdit, QFileDialog, QMessageBox, QTabWidget, QProgressBar,
    QGroupBox, QFormLayout
)

APP_NAME = "NEXUS | Game Route Lab"
DEFAULT_HOST = "1.1.1.1"
MAX_HISTORY = 120


def validate_host(host: str) -> str:
    host = host.strip()
    if not host:
        raise ValueError("Enter a hostname or IP address.")
    if len(host) > 253 or any(ch.isspace() for ch in host):
        raise ValueError("The target must be a hostname or IP address without spaces.")
    # Permit ordinary DNS names, IPv4, and IPv6 literals. Actual resolution is tested separately.
    if not re.fullmatch(r"[A-Za-z0-9._:%-]+", host):
        raise ValueError("Use only letters, numbers, dots, hyphens, colons, underscores, or percent signs.")
    return host


def resolve_host(host: str):
    try:
        results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        addresses = []
        for result in results:
            ip = result[4][0]
            if ip not in addresses:
                addresses.append(ip)
        return addresses
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve '{host}'. Check the address and your internet connection.") from exc


class PingWorker(QThread):
    sample = Signal(object)
    note = Signal(str)

    def __init__(self, host: str, interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self.host = host
        self.interval_ms = max(500, interval_ms)
        self._stop_event = threading.Event()
        self._process = None

    def stop(self):
        self._stop_event.set()
        proc = self._process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def run(self):
        self.note.emit(f"Monitoring {self.host}. Stop the test at any time.")
        while not self._stop_event.is_set():
            started = time.perf_counter()
            timestamp = datetime.now().isoformat(timespec="seconds")
            try:
                # Windows ping uses ICMP. A timeout or blocked ICMP can appear as packet loss.
                self._process = subprocess.Popen(
                    ["ping", "-n", "1", "-w", "1200", self.host],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
                output, _ = self._process.communicate(timeout=2.5)
                elapsed_ms = (time.perf_counter() - started) * 1000
                success = self._process.returncode == 0
                latency = None
                if success:
                    # Windows output can be English or localized; parse common time formats.
                    match = re.search(r"(?:time|time<)\s*[=<]\s*(\d+)\s*ms", output, re.IGNORECASE)
                    if not match:
                        match = re.search(r"time\s*=\s*(\d+)\s*ms", output, re.IGNORECASE)
                    if match:
                        latency = float(match.group(1))
                    else:
                        # A successful ping with unrecognized output still counts as a reply.
                        latency = round(elapsed_ms, 1)
                self.sample.emit({
                    "timestamp": timestamp,
                    "host": self.host,
                    "success": success,
                    "latency_ms": latency,
                    "raw": output.strip()
                })
            except subprocess.TimeoutExpired:
                try:
                    self._process.kill()
                except Exception:
                    pass
                self.sample.emit({
                    "timestamp": timestamp, "host": self.host, "success": False,
                    "latency_ms": None, "raw": "Ping process timed out."
                })
            except Exception as exc:
                self.sample.emit({
                    "timestamp": timestamp, "host": self.host, "success": False,
                    "latency_ms": None, "raw": str(exc)
                })
            finally:
                self._process = None
            remaining = self.interval_ms / 1000 - (time.perf_counter() - started)
            if remaining > 0:
                self._stop_event.wait(remaining)
        self.note.emit("Monitoring stopped.")


class TraceWorker(QThread):
    output_ready = Signal(str)
    error = Signal(str)

    def __init__(self, host: str, parent=None):
        super().__init__(parent)
        self.host = host
        self._proc = None

    def run(self):
        try:
            self.output_ready.emit(f"Running: tracert -d -h 20 -w 700 {self.host}\n"
                                   "This may take up to about 20–30 seconds.\n")
            self._proc = subprocess.Popen(
                ["tracert", "-d", "-h", "20", "-w", "700", self.host],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            try:
                output, _ = self._proc.communicate(timeout=30)
                self.output_ready.emit(output or "(No route output was returned.)")
            except subprocess.TimeoutExpired:
                self._proc.kill()
                output, _ = self._proc.communicate()
                self.output_ready.emit((output or "") + "\nTrace timed out after 30 seconds.")
        except FileNotFoundError:
            self.error.emit("Windows 'tracert' was not found. This tool requires Windows.")
        except Exception as exc:
            self.error.emit(f"Trace failed: {exc}")
        finally:
            self._proc = None

    def stop(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass


class RouteCompareWorker(QThread):
    result = Signal(object)
    note = Signal(str)

    def __init__(self, targets, parent=None):
        super().__init__(parent)
        self.targets = targets

    def run(self):
        rows = []
        for label, host in self.targets:
            samples = []
            self.note.emit(f"Testing {label} ({host})…")
            for _ in range(4):
                try:
                    start = time.perf_counter()
                    proc = subprocess.run(
                        ["ping", "-n", "1", "-w", "1400", host],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace", timeout=2.5,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    )
                    out = proc.stdout or ""
                    match = re.search(r"(?:time|time<)\s*[=<]\s*(\d+)\s*ms", out, re.IGNORECASE)
                    if not match:
                        match = re.search(r"time\s*=\s*(\d+)\s*ms", out, re.IGNORECASE)
                    if proc.returncode == 0:
                        samples.append(float(match.group(1)) if match else (time.perf_counter()-start)*1000)
                except Exception:
                    pass
            rows.append({"label": label, "host": host, "sent": 4, "received": len(samples),
                         "loss": (4-len(samples))*25.0,
                         "avg": round(statistics.mean(samples), 1) if samples else None,
                         "jitter": round(statistics.mean(abs(samples[i]-samples[i-1]) for i in range(1,len(samples))),1) if len(samples)>1 else None})
        self.result.emit(rows)


class MetricCard(QFrame):
    def __init__(self, title, value="—", suffix="", parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.suffix_label = QLabel(suffix)
        self.suffix_label.setObjectName("metricSuffix")
        layout.addWidget(self.title_label)
        row = QHBoxLayout()
        row.setSpacing(5)
        row.addWidget(self.value_label)
        row.addWidget(self.suffix_label)
        row.addStretch()
        layout.addLayout(row)

    def set_value(self, value, suffix=None):
        self.value_label.setText(str(value))
        if suffix is not None:
            self.suffix_label.setText(suffix)


class LatencyChart(QWidget):
    """Small custom widget that draws latency history without extra chart dependencies."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = []
        self.setMinimumHeight(180)

    def set_values(self, values):
        self.values = list(values)[-MAX_HISTORY:]
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen, QColor
        from PySide6.QtCore import QRectF, QPointF
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -12)
        painter.fillRect(self.rect(), QColor("#111827"))
        # grid
        grid_pen = QPen(QColor("#263244"), 1)
        painter.setPen(grid_pen)
        for i in range(1, 4):
            y = rect.top() + rect.height() * i / 4
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
        valid = [float(v) for v in self.values if v is not None]
        if len(valid) < 2:
            painter.setPen(QColor("#8794a8"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             "Start a test to build the latency graph")
            painter.end()
            return
        maximum = max(100.0, max(valid) * 1.2)
        points = []
        total = len(self.values)
        for i, value in enumerate(self.values):
            if value is None:
                points.append(None)
                continue
            x = rect.left() + (rect.width() * i / max(1, total - 1))
            y = rect.bottom() - (min(maximum, float(value)) / maximum) * rect.height()
            points.append(QPointF(x, y))
        pen = QPen(QColor("#46e6b0"), 2)
        painter.setPen(pen)
        previous = None
        for point in points:
            if point is None:
                previous = None
                continue
            if previous is not None:
                painter.drawLine(previous, point)
            previous = point
        painter.setPen(QColor("#8794a8"))
        painter.drawText(int(rect.left()), int(rect.top() - 1), f"{int(maximum)} ms")
        painter.drawText(int(rect.left()), int(rect.bottom() + 10), "Older")
        painter.drawText(int(rect.right() - 45), int(rect.bottom() + 10), "Latest")
        painter.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 790)
        self.setMinimumSize(900, 650)

        self.samples = []
        self.latencies = deque(maxlen=MAX_HISTORY)
        self.worker = None
        self.trace_worker = None
        self.monitoring = False

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(22, 18, 22, 18)
        main.setSpacing(14)

        header = QHBoxLayout()
        brand_col = QVBoxLayout()
        brand = QLabel("NEXUS")
        brand.setObjectName("brand")
        subtitle = QLabel("NETWORK DIAGNOSTICS  /  WINDOWS")
        subtitle.setObjectName("subtitle")
        brand_col.addWidget(brand)
        brand_col.addWidget(subtitle)
        header.addLayout(brand_col)
        header.addStretch()
        self.status_badge = QLabel("●  READY")
        self.status_badge.setObjectName("statusBadge")
        header.addWidget(self.status_badge, alignment=Qt.AlignmentFlag.AlignVCenter)
        main.addLayout(header)

        # Target configuration
        target_group = QGroupBox("TEST TARGET")
        target_layout = QGridLayout(target_group)
        target_layout.setContentsMargins(16, 18, 16, 16)
        target_layout.setHorizontalSpacing(10)
        target_layout.setVerticalSpacing(8)

        target_layout.addWidget(QLabel("Game / application"), 0, 0)
        self.game_input = QLineEdit()
        self.game_input.setPlaceholderText("e.g. Your game name")
        self.game_input.setText("Other")
        target_layout.addWidget(self.game_input, 1, 0)

        target_layout.addWidget(QLabel("Server IP or hostname"), 0, 1)
        self.host_input = QLineEdit()
        self.host_input.setText(DEFAULT_HOST)
        self.host_input.setPlaceholderText("Enter a game server IP or hostname")
        target_layout.addWidget(self.host_input, 1, 1)

        target_layout.addWidget(QLabel("Sample interval"), 0, 2)
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["1 second", "2 seconds", "5 seconds"])
        target_layout.addWidget(self.interval_combo, 1, 2)

        self.start_btn = QPushButton("▶  START TEST")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self.start_monitoring)
        target_layout.addWidget(self.start_btn, 1, 3)

        self.stop_btn = QPushButton("■  STOP")
        self.stop_btn.setObjectName("secondaryButton")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_monitoring)
        target_layout.addWidget(self.stop_btn, 1, 4)

        target_layout.setColumnStretch(0, 1)
        target_layout.setColumnStretch(1, 2)
        main.addWidget(target_group)

        # Metrics
        metrics = QGridLayout()
        metrics.setSpacing(12)
        self.current_card = MetricCard("Latest ping", "—", "ms")
        self.average_card = MetricCard("Average ping", "—", "ms")
        self.jitter_card = MetricCard("Jitter estimate", "—", "ms")
        self.loss_card = MetricCard("Packet loss", "—", "%")
        metrics.addWidget(self.current_card, 0, 0)
        metrics.addWidget(self.average_card, 0, 1)
        metrics.addWidget(self.jitter_card, 0, 2)
        metrics.addWidget(self.loss_card, 0, 3)
        main.addLayout(metrics)

        tabs = QTabWidget()
        main.addWidget(tabs, 1)

        monitor_tab = QWidget()
        monitor_layout = QVBoxLayout(monitor_tab)
        monitor_layout.setContentsMargins(12, 12, 12, 12)
        monitor_layout.setSpacing(10)
        chart_title = QLabel("LATENCY HISTORY")
        chart_title.setObjectName("sectionTitle")
        monitor_layout.addWidget(chart_title)
        self.chart = LatencyChart()
        monitor_layout.addWidget(self.chart)
        self.summary_label = QLabel("Run a test to collect measurements.")
        self.summary_label.setObjectName("mutedText")
        monitor_layout.addWidget(self.summary_label)
        tabs.addTab(monitor_tab, "Live monitor")

        route_tab = QWidget()
        route_layout = QVBoxLayout(route_tab)
        route_layout.setContentsMargins(12, 12, 12, 12)
        route_layout.setSpacing(10)
        route_info = QLabel(
            "TRACEROUTE\nShows the hops Windows can discover toward the target. "
            "Routers may hide or rate-limit responses; asterisks do not automatically mean a broken connection."
        )
        route_info.setObjectName("mutedText")
        route_info.setWordWrap(True)
        route_layout.addWidget(route_info)
        route_buttons = QHBoxLayout()
        self.trace_btn = QPushButton("↗  TRACE CURRENT TARGET")
        self.trace_btn.setObjectName("primaryButton")
        self.trace_btn.clicked.connect(self.start_trace)
        self.clear_trace_btn = QPushButton("CLEAR OUTPUT")
        self.clear_trace_btn.setObjectName("secondaryButton")
        self.clear_trace_btn.clicked.connect(lambda: self.trace_output.clear())
        route_buttons.addWidget(self.trace_btn)
        route_buttons.addWidget(self.clear_trace_btn)
        route_buttons.addStretch()
        route_layout.addLayout(route_buttons)
        self.trace_output = QPlainTextEdit()
        self.trace_output.setReadOnly(True)
        self.trace_output.setPlaceholderText("Traceroute output will appear here…")
        route_layout.addWidget(self.trace_output, 1)
        tabs.addTab(route_tab, "Route diagnostics")

        # Route Lab: test direct endpoints and candidate relay endpoints without changing Windows routes.
        lab_tab = QWidget()
        lab_layout = QVBoxLayout(lab_tab)
        lab_layout.setContentsMargins(12, 12, 12, 12)
        lab_layout.setSpacing(10)
        lab_title = QLabel("ROUTE LAB  /  COMPARE CANDIDATES")
        lab_title.setObjectName("sectionTitle")
        lab_layout.addWidget(lab_title)
        lab_explain = QLabel(
            "Enter one target per line as Label,hostname-or-IP. Use a game server for the direct baseline and "
            "real relay-server addresses for relay candidates. This test measures endpoint ping only; it does NOT "
            "route game traffic through a relay or prove that a relay will improve the complete path."
        )
        lab_explain.setObjectName("mutedText")
        lab_explain.setWordWrap(True)
        lab_layout.addWidget(lab_explain)
        self.route_targets = QPlainTextEdit()
        self.route_targets.setPlaceholderText("Direct game server,203.0.113.10\nRelay candidate A,198.51.100.20")
        self.route_targets.setPlainText("Cloudflare baseline,1.1.1.1\nGoogle baseline,8.8.8.8")
        self.route_targets.setMinimumHeight(105)
        lab_layout.addWidget(self.route_targets)
        lab_actions = QHBoxLayout()
        self.compare_btn = QPushButton("⇄  COMPARE ROUTES")
        self.compare_btn.setObjectName("primaryButton")
        self.compare_btn.clicked.connect(self.start_route_compare)
        self.simulate_btn = QPushButton("▶  RUN OFFLINE SELF-TEST")
        self.simulate_btn.setObjectName("secondaryButton")
        self.simulate_btn.clicked.connect(self.run_self_test)
        lab_actions.addWidget(self.compare_btn)
        lab_actions.addWidget(self.simulate_btn)
        lab_actions.addStretch()
        lab_layout.addLayout(lab_actions)
        self.route_results = QPlainTextEdit()
        self.route_results.setReadOnly(True)
        self.route_results.setPlaceholderText("Comparison results will appear here…")
        lab_layout.addWidget(self.route_results, 1)
        tabs.addTab(lab_tab, "Route Lab")

        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        history_layout.setContentsMargins(12, 12, 12, 12)
        history_layout.setSpacing(10)
        history_heading = QLabel("TEST LOG")
        history_heading.setObjectName("sectionTitle")
        history_layout.addWidget(history_heading)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Test samples and diagnostic notes appear here…")
        history_layout.addWidget(self.log_output, 1)
        history_buttons = QHBoxLayout()
        self.export_btn = QPushButton("↓  EXPORT CSV")
        self.export_btn.setObjectName("primaryButton")
        self.export_btn.clicked.connect(self.export_csv)
        self.clear_btn = QPushButton("CLEAR LOG")
        self.clear_btn.setObjectName("secondaryButton")
        self.clear_btn.clicked.connect(self.clear_log)
        history_buttons.addWidget(self.export_btn)
        history_buttons.addWidget(self.clear_btn)
        history_buttons.addStretch()
        history_layout.addLayout(history_buttons)
        tabs.addTab(history_tab, "Log & export")

        footer = QLabel(
            "ROUTE LAB PREVIEW  •  ICMP may differ from in-game latency  •  No network settings are changed"
        )
        footer.setObjectName("footer")
        main.addWidget(footer)

        self.apply_styles()

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #0b1018; color: #e7edf6; font-family: "Segoe UI"; font-size: 10pt; }
            QLabel { color: #e7edf6; }
            QLabel#brand { font-size: 27pt; font-weight: 800; letter-spacing: 2px; color: #f4f8ff; }
            QLabel#subtitle { font-size: 8pt; font-weight: 600; letter-spacing: 2px; color: #75869d; }
            QLabel#statusBadge { color: #46e6b0; background: #102a28; border: 1px solid #1c5449; border-radius: 10px; padding: 8px 12px; font-weight: 700; }
            QGroupBox { border: 1px solid #263244; border-radius: 12px; margin-top: 10px; padding-top: 10px; font-weight: 700; color: #92a2b8; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; }
            QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background: #111827; border: 1px solid #29364a; border-radius: 7px; padding: 9px; color: #e7edf6; selection-background-color: #245d59; }
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #46e6b0; }
            QComboBox QAbstractItemView { background: #111827; color: #e7edf6; selection-background-color: #245d59; }
            QPushButton { border-radius: 8px; padding: 10px 14px; font-weight: 700; }
            QPushButton#primaryButton { background: #46e6b0; color: #071410; border: none; }
            QPushButton#primaryButton:hover { background: #6cf0c3; }
            QPushButton#secondaryButton { background: #182233; color: #d5deeb; border: 1px solid #304057; }
            QPushButton#secondaryButton:hover { background: #233249; }
            QPushButton:disabled { background: #202a38; color: #65748a; border: 1px solid #29364a; }
            QFrame#metricCard { background: #111827; border: 1px solid #263244; border-radius: 12px; }
            QLabel#metricTitle { color: #8292a9; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
            QLabel#metricValue { color: #f4f8ff; font-size: 24pt; font-weight: 800; }
            QLabel#metricSuffix { color: #7f90a8; font-size: 9pt; padding-bottom: 4px; }
            QTabWidget::pane { border: 1px solid #263244; border-radius: 10px; background: #0e1520; }
            QTabBar::tab { background: #111827; color: #7f90a8; padding: 10px 18px; border: 1px solid #263244; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 4px; }
            QTabBar::tab:selected { background: #172235; color: #46e6b0; }
            QLabel#sectionTitle { color: #e7edf6; font-size: 12pt; font-weight: 800; letter-spacing: 1px; }
            QLabel#mutedText { color: #8999af; }
            QLabel#footer { color: #586980; font-size: 8pt; }
            QScrollBar:vertical { background: #0b1018; width: 10px; }
            QScrollBar::handle:vertical { background: #304057; border-radius: 4px; min-height: 20px; }
        """)

    def set_status(self, text, active=False):
        self.status_badge.setText(f"●  {text}")
        self.status_badge.setStyleSheet(
            "color: #46e6b0; background: #102a28; border: 1px solid #1c5449; border-radius: 10px; padding: 8px 12px; font-weight: 700;"
            if active else
            "color: #a8b6c9; background: #172235; border: 1px solid #304057; border-radius: 10px; padding: 8px 12px; font-weight: 700;"
        )

    def selected_interval(self):
        return {"1 second": 1000, "2 seconds": 2000, "5 seconds": 5000}.get(self.interval_combo.currentText(), 1000)

    def start_monitoring(self):
        if self.monitoring:
            return
        try:
            host = validate_host(self.host_input.text())
            resolve_host(host)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid target", str(exc))
            return

        game = self.game_input.text().strip() or "Unspecified"
        self.host_input.setText(host)
        self.samples = []
        self.latencies.clear()
        self.chart.set_values([])
        self.current_card.set_value("—")
        self.average_card.set_value("—")
        self.jitter_card.set_value("—")
        self.loss_card.set_value("—")
        self.log_output.appendPlainText(
            f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] START | Game/app: {game} | Target: {host} | Wi-Fi/current connection"
        )
        self.summary_label.setText(f"Testing {host}. This is an ICMP diagnostic, not a guarantee of in-game ping.")
        self.worker = PingWorker(host, self.selected_interval())
        self.worker.sample.connect(self.on_sample)
        self.worker.note.connect(self.on_note)
        self.worker.finished.connect(self.on_worker_finished)
        self.monitoring = True
        self.worker.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.set_status("TEST RUNNING", True)

    def stop_monitoring(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        self.monitoring = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.set_status("READY", False)

    def on_worker_finished(self):
        self.monitoring = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.set_status("READY", False)

    def on_note(self, note):
        self.log_output.appendPlainText(f"[{datetime.now():%H:%M:%S}] {note}")

    def on_sample(self, item):
        self.samples.append(item)
        self.latencies.append(item["latency_ms"] if item["success"] else None)
        self.chart.set_values(self.latencies)
        count = len(self.samples)
        successes = [x["latency_ms"] for x in self.samples if x["success"] and x["latency_ms"] is not None]
        loss = (count - len(successes)) / count * 100 if count else 0

        if item["success"] and item["latency_ms"] is not None:
            self.current_card.set_value(f'{item["latency_ms"]:.0f}')
            self.log_output.appendPlainText(
                f'[{item["timestamp"]}] OK | {item["host"]} | {item["latency_ms"]:.1f} ms'
            )
        else:
            self.current_card.set_value("TIMEOUT", "")
            self.log_output.appendPlainText(f'[{item["timestamp"]}] TIMEOUT | {item["host"]}')

        if successes:
            avg = statistics.mean(successes)
            self.average_card.set_value(f"{avg:.1f}")
            self.average_card.set_value(f"{avg:.1f}")
            if len(successes) > 1:
                jitter = statistics.mean(abs(successes[i] - successes[i - 1]) for i in range(1, len(successes)))
            else:
                jitter = 0.0
            self.jitter_card.set_value(f"{jitter:.1f}")
        self.loss_card.set_value(f"{loss:.1f}")
        latest_avg = f'{statistics.mean(successes):.1f} ms' if successes else "no successful replies"
        self.summary_label.setText(
            f"Samples: {count}  •  Replies: {len(successes)}  •  Average: {latest_avg}  •  Packet loss: {loss:.1f}%"
        )

    def start_trace(self):
        if self.trace_worker and self.trace_worker.isRunning():
            QMessageBox.information(self, "Trace running", "A route trace is already running.")
            return
        try:
            host = validate_host(self.host_input.text())
            resolve_host(host)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid target", str(exc))
            return
        self.trace_output.setPlainText(f"Preparing route trace to {host}...\n")
        self.trace_btn.setEnabled(False)
        self.trace_worker = TraceWorker(host)
        self.trace_worker.output_ready.connect(self.trace_output.setPlainText)
        self.trace_worker.error.connect(self.on_trace_error)
        self.trace_worker.finished.connect(lambda: self.trace_btn.setEnabled(True))
        self.trace_worker.start()

    def on_trace_error(self, message):
        self.trace_output.setPlainText(message)
        QMessageBox.warning(self, "Route trace", message)

    def start_route_compare(self):
        if hasattr(self, "route_worker") and self.route_worker and self.route_worker.isRunning():
            return
        targets = []
        for line_no, line in enumerate(self.route_targets.toPlainText().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "," not in line:
                QMessageBox.warning(self, "Invalid target list", f"Line {line_no}: use Label,hostname-or-IP")
                return
            label, host = [part.strip() for part in line.split(",", 1)]
            try:
                host = validate_host(host)
                resolve_host(host)
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid target", f"Line {line_no}: {exc}")
                return
            targets.append((label or host, host))
        if not targets:
            QMessageBox.warning(self, "No targets", "Add at least one target first.")
            return
        if len(targets) > 12:
            QMessageBox.warning(self, "Too many targets", "Compare up to 12 targets at a time.")
            return
        self.compare_btn.setEnabled(False)
        self.route_results.setPlainText("Comparing each endpoint with four ping samples…\n")
        self.route_worker = RouteCompareWorker(targets)
        self.route_worker.note.connect(lambda msg: self.route_results.appendPlainText(msg))
        self.route_worker.result.connect(self.show_route_results)
        self.route_worker.finished.connect(lambda: self.compare_btn.setEnabled(True))
        self.route_worker.start()

    def show_route_results(self, rows):
        lines = ["ENDPOINT PING COMPARISON", "=" * 72,
                 "Note: lowest endpoint ping is not necessarily the best game route.", ""]
        usable = [r for r in rows if r["avg"] is not None]
        ranked = sorted(usable, key=lambda r: (r["avg"], r["loss"]))
        for r in rows:
            avg = f"{r['avg']:.1f} ms" if r["avg"] is not None else "No replies"
            jitter = f"{r['jitter']:.1f} ms" if r["jitter"] is not None else "—"
            lines.append(f"{r['label']} | {r['host']} | avg {avg} | jitter {jitter} | loss {r['loss']:.0f}%")
        if ranked:
            lines.extend(["", f"Lowest measured endpoint ping: {ranked[0]['label']} ({ranked[0]['avg']:.1f} ms).",
                          "This is a diagnostic result only; no route or network settings were changed."])
        else:
            lines.extend(["", "No endpoints replied to ICMP. Some servers block ping; this alone does not prove they are offline."])
        self.route_results.setPlainText("\n".join(lines))

    def run_self_test(self):
        checks = []
        checks.append(("Hostname validation accepts a normal host", validate_host("example.com") == "example.com"))
        try:
            validate_host("")
            checks.append(("Empty hostname is rejected", False))
        except ValueError:
            checks.append(("Empty hostname is rejected", True))
        try:
            validate_host("invalid host with spaces")
            checks.append(("Host containing spaces is rejected", False))
        except ValueError:
            checks.append(("Host containing spaces is rejected", True))
        # Test the ranking decision on synthetic measurements without pretending these are real routes.
        simulated = [{"label": "Route A", "avg": 85.0, "loss": 0.0},
                     {"label": "Route B", "avg": 42.0, "loss": 0.0},
                     {"label": "Route C", "avg": None, "loss": 100.0}]
        winner = min((x for x in simulated if x["avg"] is not None), key=lambda x: (x["avg"], x["loss"]))
        checks.append(("Synthetic route ranking selects the lowest responding latency", winner["label"] == "Route B"))
        checks.append(("Synthetic 100% loss route is excluded from winner selection", all(x["label"] != "Route C" for x in [winner])))
        lines = ["NEXUS OFFLINE SELF-TEST", "=" * 40]
        for name, passed in checks:
            lines.append(f"{'PASS' if passed else 'FAIL'}  {name}")
        lines.append("")
        lines.append(f"Result: {sum(1 for _, ok in checks if ok)}/{len(checks)} checks passed.")
        lines.append("These are software logic checks, not a test of real game traffic or relay infrastructure.")
        self.route_results.setPlainText("\n".join(lines))

    def export_csv(self):
        if not self.samples:
            QMessageBox.information(self, "Nothing to export", "Run a ping test first so there are samples to export.")
            return
        suggested = f"NEXUS_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export test results", suggested, "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "game_app", "host", "success", "latency_ms", "raw"])
                writer.writeheader()
                game = self.game_input.text().strip() or "Unspecified"
                for sample in self.samples:
                    row = dict(sample)
                    row["game_app"] = game
                    writer.writerow(row)
            QMessageBox.information(self, "Export complete", f"Saved {len(self.samples)} samples to:\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def clear_log(self):
        self.log_output.clear()
        self.samples = []
        self.latencies.clear()
        self.chart.set_values([])
        self.current_card.set_value("—")
        self.average_card.set_value("—")
        self.jitter_card.set_value("—")
        self.loss_card.set_value("—")
        self.summary_label.setText("Log cleared. Start a new test to collect measurements.")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2500)
        if self.trace_worker and self.trace_worker.isRunning():
            self.trace_worker.stop()
            self.trace_worker.wait(1500)
        event.accept()


def main():
    if sys.platform != "win32":
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "Windows required", "This version uses Windows ping and tracert commands.")
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
