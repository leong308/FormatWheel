"""Interactive ZIP progress backed by actual source bytes and worker checkpoints."""
from __future__ import annotations

import math
from pathlib import Path
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QLinearGradient, QPainter, QPainterPath, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLayout, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import win32


def byte_text(value):
    value = max(0, int(value or 0))
    if value < 1024:
        return f"{value:,} B"
    amount = float(value)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        amount /= 1024
        if amount < 1024 or unit == "TiB":
            return f"{amount:,.1f} {unit}"


def duration_text(seconds):
    seconds = max(0, round(seconds or 0))
    hours, minutes = seconds//3600, seconds%3600//60
    return f"{hours}:{minutes:02}:{seconds%60:02}" if hours else f"{minutes}:{seconds%60:02}"


class ArchiveMeter(QProgressBar):
    """Animated activity is decorative; its fill always uses the reported fraction."""
    def __init__(self, accent, parent=None):
        super().__init__(parent)
        self.accent = QColor(accent)
        self.fraction = None
        self.paused = False
        self.phase = 0.
        self.setFixedHeight(12)
        self.setTextVisible(False)
        self.setAccessibleName("ZIP source bytes processed")
        self.setRange(0, 0)

    def set_progress(self, fraction, paused=False):
        self.fraction, self.paused = fraction, paused
        if fraction is None:
            self.setRange(0, 0)
        else:
            self.setRange(0, 1000)
            self.setValue(int(max(0., min(1., fraction))*1000))
        self.update()

    def animate(self, phase):
        self.phase = phase
        if not self.paused:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QPainterPath()
        track.addRoundedRect(QRectF(self.rect()), 6, 6)
        p.fillPath(track, QColor("#303641"))
        p.setClipPath(track)
        accent = QColor("#a6afbd") if self.paused else self.accent
        width = self.width()
        if self.fraction is None:
            segment = max(45, width*.23)
            x = ((self.phase*.45) % 1)*(width+segment)-segment
            fill = QRectF(x, 0, segment, self.height())
        else:
            fill = QRectF(0, 0, width*max(0., min(1., self.fraction)), self.height())
        p.fillRect(fill, accent)
        if not self.paused and self.fraction is not None and fill.width()>0:
            p.setClipRect(fill, Qt.ClipOperation.IntersectClip)
            x = ((self.phase*.38) % 1)*(width+140)-140
            shine = QLinearGradient(x, 0, x+140, 0)
            shine.setColorAt(0, QColor(255, 255, 255, 0))
            shine.setColorAt(.5, QColor(255, 255, 255, 100))
            shine.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(x, 0, 140, self.height()), shine)
        p.end()


class ZipProgressPanel(QWidget):
    """One ZIP job, expandable details, cooperative controls and a hideable window."""
    visibility_changed = Signal(bool)

    def __init__(self, accent="#3380e6", reveal=None, open_folder=None):
        super().__init__()
        self.accent = accent
        self.reveal = reveal or win32.reveal
        self.open_folder = open_folder or (lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("ZIP progress · FormatWheel")
        self.setAccessibleName("ZIP archive progress")
        self.control = None
        self.latest = None
        self.output_path = None
        self.active = False
        self.terminal = False
        self.started = 0.
        self.elapsed_at_update = 0.
        self.received_at = 0.
        self.pause_requested = False
        self.cancel_requested = False
        self.finished_elapsed = None
        self._drag_offset = None
        self._expanded = True
        self.setStyleSheet(f"""
            QWidget {{ color: #f2f4f8; font-family: 'Segoe UI'; font-size: 13px; }}
            QFrame#card {{ background: #191e28; border: 1px solid #394454; border-radius: 14px; }}
            QLabel {{ background: transparent; border: none; }}
            QLabel#eyebrow {{ color: {accent}; font-size: 11px; font-weight: 700; letter-spacing: 2px; }}
            QLabel#title {{ font-size: 23px; font-weight: 650; }}
            QLabel#percent {{ font-size: 24px; font-weight: 650; }}
            QLabel#muted {{ color: #a6b0bf; font-size: 12px; }}
            QLabel#value {{ font-size: 13px; font-weight: 600; }}
            QPushButton {{ border: 1px solid #4b5668; background: #252d3b; border-radius: 7px; padding: 8px 12px; }}
            QPushButton:hover {{ background: #354257; border-color: #8296b4; }}
            QPushButton:focus {{ border: 2px solid {accent}; padding: 7px 11px; }}
            QPushButton:disabled {{ color: #687586; border-color: #343e4c; background: #202631; }}
            QPushButton#primary {{ color: #ffffff; background: {accent}; border-color: {accent}; font-weight: 600; }}
            QPushButton#secondary {{ border: none; color: #aab7ca; background: transparent; padding: 4px 0px; text-align: left; }}
            QPushButton#hide {{ border: none; background: transparent; color: #aab7ca; font-size: 19px; padding: 0px; }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
        """)
        outer = QVBoxLayout(self)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame()
        self.card.setObjectName("card")
        outer.addWidget(self.card)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(24, 21, 24, 19)
        layout.setSpacing(13)
        header = QHBoxLayout()
        self.eyebrow = self.label("FORMATWHEEL  /  ZIP", "eyebrow")
        header.addWidget(self.eyebrow)
        header.addStretch()
        self.hide_button = QPushButton("−")
        self.hide_button.setObjectName("hide")
        self.hide_button.setFixedSize(25, 24)
        self.hide_button.setAccessibleName("Hide progress; ZIP keeps running")
        self.hide_button.setToolTip("隐藏进度，ZIP 继续运行。系统托盘菜单可重新打开。\nHide progress; ZIP keeps running. Restore from the tray menu.")
        self.hide_button.clicked.connect(self.hide)
        header.addWidget(self.hide_button)
        layout.addLayout(header)
        title_row = QHBoxLayout()
        self.title_label = self.label("创建 ZIP / Creating ZIP", "title")
        self.title_label.setWordWrap(True)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_row.addWidget(self.title_label, 1)
        self.percent_label = self.label("", "percent")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(self.percent_label)
        layout.addLayout(title_row)
        self.status_label = self.label("正在扫描文件 / Scanning files…", "muted")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.meter = ArchiveMeter(accent)
        layout.addWidget(self.meter)
        self.bytes_label = self.label("正在统计大小 / Counting source bytes…", "value")
        self.bytes_label.setWordWrap(True)
        self.bytes_label.setMinimumWidth(0)
        self.bytes_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.bytes_label)
        self.current_label = self.label("", "muted")
        self.current_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.current_label.setMinimumWidth(0)
        self.current_label.setAccessibleName("Current file")
        layout.addWidget(self.current_label)
        self.details_button = QPushButton("▾  收起详情 / Fewer details")
        self.details_button.setObjectName("secondary")
        self.details_button.setCheckable(True)
        self.details_button.setChecked(True)
        self.details_button.setAccessibleName("Toggle ZIP progress details")
        self.details_button.setToolTip("Alt+D：展开或收起详情 / Expand or collapse details")
        self.details_button.toggled.connect(self.set_expanded)
        layout.addWidget(self.details_button)
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details_scroll.setMaximumHeight(188)
        self.details = QWidget()
        grid = QGridLayout(self.details)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(6)
        self.files_value = self.detail_cell(grid, 0, 0, "文件 / Files", "—")
        self.speed_value = self.detail_cell(grid, 0, 1, "速度 / Speed", "—")
        self.elapsed_value = self.detail_cell(grid, 2, 0, "已用时间 / Elapsed", "0:00")
        self.eta_value = self.detail_cell(grid, 2, 1, "预计剩余 / Estimated remaining", "Calculating…")
        self.archive_value = self.detail_cell(grid, 4, 0, "ZIP 当前大小 / Archive size", "0 B")
        self.destination_label = self.label("", "muted")
        self.destination_label.setWordWrap(True)
        self.destination_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.destination_label.setMinimumWidth(0)
        grid.addWidget(self.destination_label, 6, 0, 1, 2)
        self.details_scroll.setWidget(self.details)
        layout.addWidget(self.details_scroll)
        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        self.destination_button = QPushButton("打开位置 / &Folder")
        self.destination_button.setAccessibleName("Open destination folder")
        self.destination_button.setToolTip("打开目标文件夹；正在创建的 ZIP 不会被打开。\nOpen the destination folder, not the unfinished archive.")
        self.destination_button.clicked.connect(self.open_destination)
        self.pause_button = QPushButton("暂停 / &Pause")
        self.pause_button.setObjectName("primary")
        self.pause_button.setAccessibleName("Pause ZIP creation")
        self.pause_button.setToolTip("暂停读取与压缩，稍后可以继续。Alt+P 暂停，Alt+R 继续。\nPause reading and compression. Alt+P pauses; Alt+R resumes.")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.cancel_button = QPushButton("取消 / &Cancel")
        self.cancel_button.setAccessibleName("Cancel ZIP creation")
        self.cancel_button.setToolTip("取消后删除未完成的 ZIP，保留原文件。\nCancel and remove the partial ZIP. Originals are preserved.")
        self.cancel_button.clicked.connect(self.request_cancel)
        for button in (self.destination_button, self.pause_button, self.cancel_button):
            button.setMinimumHeight(36)
        buttons.addWidget(self.destination_button)
        buttons.addStretch(1)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.footer = self.label("文件在本机处理，原文件保留 / Local processing · Originals kept", "muted")
        self.footer.setWordWrap(True)
        layout.addWidget(self.footer)
        # Keep native action controls reachable even on a short logical display.
        # Only the measurements scroll; Pause/Cancel and the footer remain fixed.
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_scroll.setMinimumSize(0, 0)
        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        for _ in range(8):
            item = layout.takeAt(0)
            if item.widget():
                body_layout.addWidget(item.widget())
            elif item.layout():
                child_layout = item.layout()
                child_layout.setParent(None)
                body_layout.addLayout(child_layout)
        body_layout.addStretch(1)
        self.body_scroll.setWidget(self.body)
        layout.insertWidget(0, self.body_scroll, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.animate)
        self._shortcuts = []
        for sequence, callback in (("Alt+D", lambda: self.details_button.toggle()), ("Escape", self.request_cancel)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    @staticmethod
    def label(value, style=None):
        result = QLabel(value)
        result.setTextFormat(Qt.TextFormat.PlainText)
        if style:
            result.setObjectName(style)
        return result

    def detail_cell(self, grid, row, col, name, initial):
        caption = self.label(name, "muted")
        caption.setWordWrap(True)
        caption.setMinimumWidth(0)
        grid.addWidget(caption, row, col)
        value = self.label(initial, "value")
        value.setAccessibleName(name)
        grid.addWidget(value, row+1, col)
        return value

    def begin(self, control, show=True):
        self.control, self.latest, self.output_path = control, None, None
        self.active, self.terminal = True, False
        self.pause_requested = self.cancel_requested = False
        self.finished_elapsed = None
        self.started = self.received_at = time.monotonic()
        self.elapsed_at_update = 0.
        self.title_label.setText("创建 ZIP / Creating ZIP")
        self.percent_label.setText("")
        self.status_label.setText("正在扫描文件 / Scanning files…")
        self.bytes_label.setText("正在统计大小 / Counting source bytes…")
        self.current_label.setText("")
        self.destination_label.setText("")
        self.destination_button.setText("打开位置 / &Folder")
        self.destination_button.setAccessibleName("Open destination folder")
        self.destination_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.pause_button.setVisible(True)
        self.pause_button.setText("暂停 / &Pause")
        self.pause_button.setAccessibleName("Pause ZIP creation")
        self.cancel_button.setText("取消 / &Cancel")
        self.cancel_button.setAccessibleName("Cancel ZIP creation")
        self.cancel_button.setEnabled(True)
        self.files_value.setText("—")
        self.speed_value.setText("—")
        self.elapsed_value.setText("0:00")
        self.eta_value.setText("统计中 / Calculating…")
        self.archive_value.setText("0 B")
        self.footer.setText("文件在本机处理，原文件保留 / Local processing · Originals kept")
        self.meter.set_progress(None)
        self.fit_to_screen(auto_collapse=True)
        self.timer.start()
        if show:
            self.restore()

    def apply_update(self, update):
        if self.terminal:
            return
        self.latest = update
        self.received_at = time.monotonic()
        self.elapsed_at_update = max(0., float(update.elapsed or 0))
        phase = update.phase
        paused = phase == "paused"
        # The worker acknowledgement can arrive after a quick Pause→Resume click.
        self.pause_requested = bool(self.control and self.control.is_paused)
        fraction = update.fraction
        complete = phase == "completed"
        if fraction is not None:
            fraction = max(0., min(1. if complete else .9999, float(fraction)))
        self.output_path = Path(update.output_path) if update.output_path else self.output_path
        self.destination_button.setEnabled(bool(self.output_path))
        self.destination_label.setText(f"保存到 / Destination\n{self.output_path or '扫描后确定 / Available after scanning'}")
        self.destination_label.setToolTip(str(self.output_path or ""))
        self.percent_label.setText("" if fraction is None or phase in {"scanning", "finalizing"} else f"{math.floor(fraction*1000)/10:.1f}%" if fraction < 1 else "100%")
        if phase == "scanning":
            status = "正在扫描文件，计算总大小 / Scanning files and counting source bytes…"
        elif phase == "paused":
            status = ("已暂停 · 原文件和进度保留 / Paused · Ready to resume" if self.pause_requested
                      else "正在继续 / Resuming…")
        elif phase == "finalizing":
            status = "正在写入 ZIP 目录，完成前请稍候 / Finalizing the archive…"
        elif phase == "completed":
            status = "ZIP 已完成，可以安全打开 / Archive ready"
        else:
            status = "正在压缩文件 / Compressing files…"
        if self.cancel_requested:
            status = "正在取消并清理未完成的 ZIP… / Canceling and removing the partial archive…"
        elif self.pause_requested and not paused:
            status = "即将在当前数据块完成后暂停… / Pausing after the current block…"
        self.status_label.setText(status)
        self.meter.set_progress(None if phase in {"scanning", "finalizing"} else fraction, paused or self.pause_requested or self.cancel_requested)
        if phase == "scanning":
            self.bytes_label.setText(f"已找到 / Found {byte_text(update.total_bytes)} · 总大小仍在统计 / Counting…")
            self.files_value.setText(f"{update.files_total:,} 已找到 / found")
        else:
            self.bytes_label.setText(f"{byte_text(update.processed_bytes)} / {byte_text(update.total_bytes)}  源文件已读取 / source bytes read")
            self.files_value.setText(f"{update.files_completed:,} / {update.files_total:,}")
        self.current_label.setToolTip(str(update.current_file or ""))
        self.current_label.setAccessibleDescription(str(update.current_file or ""))
        self.refresh_current_file()
        self.archive_value.setText(byte_text(update.archive_bytes))
        self.archive_value.setToolTip(f"{int(update.archive_bytes):,} bytes currently written to the ZIP")
        self.bytes_label.setToolTip(f"{int(update.processed_bytes):,} / {int(update.total_bytes):,} source bytes processed" + (" (total still being counted)" if phase == "scanning" else ""))
        self.speed_value.setText("已暂停 / Paused" if paused else f"{byte_text(update.speed_bps)}/s" if update.speed_bps is not None else "—")
        self.speed_value.setToolTip(f"{update.speed_bps:,.0f} source bytes per second; excludes paused time" if update.speed_bps is not None else "")
        self.eta_value.setText("已暂停 / Paused" if paused else f"约 / About {duration_text(update.eta_seconds)}" if update.eta_seconds is not None else "统计中 / Calculating…" if phase == "scanning" else "—")
        self.pause_button.setEnabled(not self.cancel_requested and phase not in {"finalizing", "completed"})
        self.pause_button.setText("继续 / &Resume" if self.pause_requested else "暂停 / &Pause")
        self.pause_button.setAccessibleName("Resume ZIP creation" if self.pause_requested else "Pause ZIP creation")
        self.refresh_buttons()
        self.animate()

    def refresh_current_file(self):
        full = self.current_label.toolTip()
        prefix = "当前文件 / Current: " if full else ""
        width = max(80, self.current_label.width())
        self.current_label.setText(self.current_label.fontMetrics().elidedText(prefix+full, Qt.TextElideMode.ElideMiddle, width))

    def animate(self):
        now = time.monotonic()
        self.meter.animate(now-self.started)
        if self.finished_elapsed is not None:
            elapsed = self.finished_elapsed
        else:
            elapsed = self.elapsed_at_update+max(0., now-self.received_at)
        self.elapsed_value.setText(duration_text(elapsed))

    def toggle_pause(self):
        if not self.active or self.cancel_requested or not self.pause_button.isEnabled():
            return
        if self.pause_requested:
            self.control.resume()
            self.pause_requested = False
            self.pause_button.setText("暂停 / &Pause")
            self.pause_button.setAccessibleName("Pause ZIP creation")
            self.status_label.setText("正在继续 / Resuming…")
        else:
            self.control.pause()
            self.pause_requested = True
            self.pause_button.setText("继续 / &Resume")
            self.pause_button.setAccessibleName("Resume ZIP creation")
            self.status_label.setText("即将在当前数据块完成后暂停… / Pausing after the current block…")
            self.speed_value.setText("—")
            self.eta_value.setText("—")
            self.meter.paused = True
            self.meter.update()
        self.refresh_buttons()

    def request_cancel(self):
        if self.terminal:
            self.hide()
            return
        if not self.active or self.cancel_requested:
            return
        self.cancel_requested = True
        self.control.cancel()
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("取消中… / Canceling…")
        self.status_label.setText("正在取消并清理未完成的 ZIP… / Canceling and removing the partial archive…")
        self.speed_value.setText("—")
        self.eta_value.setText("—")
        self.meter.paused = True
        self.meter.update()
        self.refresh_buttons()

    def finish(self, outputs):
        self._finish_state()
        self.cancel_requested = False
        self.output_path = Path(outputs[0]) if outputs else self.output_path
        self.title_label.setText("ZIP 已完成 / Archive ready")
        self.percent_label.setText("100%")
        self.status_label.setText("所有文件已写入，ZIP 目录已完成 / All files and the ZIP directory are complete")
        self.meter.set_progress(1.)
        self.destination_button.setEnabled(bool(self.output_path))
        self.destination_button.setText("显示 ZIP / &Show ZIP")
        self.destination_button.setAccessibleName("Show completed ZIP in Explorer")
        if self.output_path:
            self.destination_label.setText(f"保存到 / Destination\n{self.output_path}")
            try:
                self.archive_value.setText(byte_text(self.output_path.stat().st_size))
            except OSError:
                pass
        self.footer.setText("完成 · 原文件保留 / Completed · Originals kept")
        self.refresh_buttons()

    def cancelled(self):
        self._finish_state()
        self.title_label.setText("已取消 / Canceled")
        self.percent_label.setText("")
        self.status_label.setText("未完成的 ZIP 已删除，原文件保留 / Partial archive removed. Originals are preserved.")
        self.destination_button.setEnabled(bool(self.output_path))
        self.meter.set_progress(self.meter.fraction, True)
        self.archive_value.setText("已清理 / Removed")
        self.footer.setText("可以从轮盘重新开始 / Start another ZIP from the wheel whenever you're ready")
        self.refresh_buttons()

    def failed(self, message):
        self._finish_state()
        self.title_label.setText("ZIP 未完成 / Archive failed")
        self.status_label.setText(str(message))
        self.meter.set_progress(self.meter.fraction, True)
        self.footer.setText("原文件保留 / Originals are preserved")
        self.refresh_buttons()

    def _finish_state(self):
        self.finished_elapsed = self.elapsed_at_update+max(0., time.monotonic()-self.received_at)
        self.active, self.terminal = False, True
        self.timer.stop()
        self.pause_button.setVisible(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("关闭 / &Close")
        self.cancel_button.setAccessibleName("Close ZIP progress")
        self.speed_value.setText("—")
        self.eta_value.setText("—")
        self.animate()

    def open_destination(self):
        if not self.output_path:
            return
        if self.terminal and not self.cancel_requested and self.meter.fraction == 1 and self.output_path.exists():
            self.reveal(self.output_path)
        else:
            self.open_folder(self.output_path.parent)

    def set_expanded(self, expanded):
        self._expanded = bool(expanded)
        self.details_scroll.setVisible(expanded)
        self.details_button.setText("▾  收起详情 / Fewer details" if expanded else "▸  展开详情 / More details")
        self.fit_to_screen()

    def fit_to_screen(self, auto_collapse=False):
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            self.resize(570, 516 if self._expanded else 328)
            return
        frame = screen.availableGeometry()
        if auto_collapse and frame.height()<560 and self._expanded:
            self._expanded = False
            self.details_button.blockSignals(True)
            self.details_button.setChecked(False)
            self.details_button.blockSignals(False)
            self.details_scroll.hide()
            self.details_button.setText("▸  展开详情 / More details")
        width = min(590, max(320, frame.width()-32))
        height = min(542 if self._expanded else 345, max(260, frame.height()-32))
        self.resize(width, height)
        self.move(frame.right()-width-18, frame.bottom()-height-18)
        self.refresh_current_file()
        self.refresh_buttons()

    def refresh_buttons(self):
        if not hasattr(self, "cancel_button"):
            return
        compact = self.width()<440
        completed = self.terminal and self.meter.fraction == 1 and not self.cancel_requested
        self.destination_button.setText(("&Show ZIP" if completed else "&Folder") if compact else ("显示 ZIP / &Show ZIP" if completed else "打开位置 / &Folder"))
        self.pause_button.setText(("&Resume" if self.pause_requested else "&Pause") if compact else ("继续 / &Resume" if self.pause_requested else "暂停 / &Pause"))
        self.cancel_button.setText(("&Close" if self.terminal else "Canceling…" if self.cancel_requested else "&Cancel") if compact else
                                   ("关闭 / &Close" if self.terminal else "取消中… / Canceling…" if self.cancel_requested else "取消 / &Cancel"))

    def restore(self):
        self.fit_to_screen()
        self.show()
        self.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_current_file()
        self.refresh_buttons()

    def showEvent(self, event):
        self.visibility_changed.emit(True)
        super().showEvent(event)

    def hideEvent(self, event):
        self.visibility_changed.emit(False)
        super().hideEvent(event)

    def closeEvent(self, event):
        self.hide()  # Closing progress never cancels a running archive.
        event.ignore()


def progress_snapshot(path, phase="compressing", expanded=True):
    """Render only this panel, using sample data and no screen capture or file operation."""
    from types import SimpleNamespace
    app = QApplication.instance() or QApplication([])
    panel = ZipProgressPanel()
    control = SimpleNamespace(pause=lambda: None, resume=lambda: None, cancel=lambda: None, is_paused=phase == "paused")
    panel.begin(control, show=False)
    panel.set_expanded(expanded)
    sample = SimpleNamespace(fraction=None if phase == "scanning" else .426, phase=phase,
                             processed_bytes=436_207_616, total_bytes=1_024_000_000, files_completed=124,
                             files_total=287, current_file="Holiday photos/2026/sunset beach.png",
                             output_path=Path("C:/Users/You/Downloads/Holiday photos.zip"), archive_bytes=309_329_920,
                             elapsed=28.4, speed_bps=15_360_000 if phase == "compressing" else None,
                             eta_seconds=38.3 if phase == "compressing" else None)
    panel.apply_update(sample)
    panel.ensurePolished()
    panel.layout().activate()
    app.processEvents()
    panel.meter.animate(.8)
    target = Path(path).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not panel.grab().save(str(target)):
        raise OSError(f"Could not save ZIP progress snapshot: {target}")
    panel.timer.stop()
    panel.deleteLater()
    return target
