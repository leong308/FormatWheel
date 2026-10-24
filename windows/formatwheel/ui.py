"""Native Windows tray application with an OLE file-drop weapon wheel."""
from __future__ import annotations

import logging
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QRunnable, Qt, QThreadPool, QTimer, Signal, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QDesktopServices, QImage, QPainter, QPixmap, QRadialGradient
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QFileDialog, QGraphicsBlurEffect, QGraphicsPixmapItem,
                               QGraphicsScene, QMenu, QMessageBox, QSystemTrayIcon, QWidget)

from . import catalog, win32
from .drawing import (GOLD, LOSS, WHITE, font, glyph, paint_stats, paint_wanted, paint_wheel,
                      panel, slot_at, text, tray_icon, weapon, weapon_name)
from .engine import Engine, OperationCancelled, OperationControl, find_tool, scan_privacy
from .progress_ui import ZipProgressPanel
from .settings import CREWS, SIZES, Settings
from .sound import Sounds

log = logging.getLogger(__name__)
OVERLAY_FLAGS = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool


def supports_copy(event):
    """Qt keeps MoveAction when CopyAction is absent, so never accept such a drag."""
    return bool(event.possibleActions() & Qt.DropAction.CopyAction)


class TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(object)


class Task(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = TaskSignals()

    def run(self):
        try:
            self.signals.done.emit(self.function(self.signals.progress.emit))
        except Exception as error:
            if not isinstance(error, OperationCancelled):
                log.exception("Background operation failed")
            self.signals.failed.emit(error)


class ProgressMailbox(QObject):
    """Coalesce worker updates before Qt queues them, retaining the latest real value."""
    ready = Signal()

    def __init__(self, deliver):
        super().__init__()
        self.deliver = deliver
        self.lock = threading.Lock()
        self.latest = None
        self.pending = False
        self.ready.connect(self.flush, Qt.ConnectionType.QueuedConnection)

    def push(self, value):
        with self.lock:
            self.latest = value
            notify = not self.pending
            self.pending = True
        if notify:
            self.ready.emit()

    def flush(self):
        with self.lock:
            value, self.latest = self.latest, None
            self.pending = False
        if value is not None:
            self.deliver(value)


def screen_for(point=None):
    return QApplication.screenAt(point or QCursor.pos()) or QApplication.primaryScreen()


def demo_files():
    path = Path(tempfile.gettempdir()) / "FormatWheel-demo.png"
    if not path.exists():
        image = QImage(1200, 800, QImage.Format.Format_RGB32)
        image.fill(QColor("#7da3b3"))
        p = QPainter(image)
        p.fillRect(0, 490, 1200, 310, QColor("#314c43"))
        p.setBrush(QColor("#edbe6d"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(810, 110, 150, 150)
        p.end()
        image.save(str(path))
    return [path]


def blurred_screen(screen):
    original = screen.grabWindow(0)
    if original.isNull():
        return None
    # Work in physical pixels, preserving the display's DPI on the final pixmap.
    ratio = original.devicePixelRatio()
    image = original.toImage().scaled(max(1, original.width()//3), max(1, original.height()//3), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(image))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(7)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    result = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    scene.render(painter, QRectF(result.rect()), QRectF(image.rect()))
    painter.end()
    pixmap = QPixmap.fromImage(result)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


class Overlay(QWidget):
    chosen = Signal(object, object)
    closed = Signal()

    def __init__(self, settings, sounds, owner=None):
        super().__init__()
        self.settings, self.sounds, self.owner = settings, sounds, owner
        self.setWindowFlags(OVERLAY_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)  # Register with OLE before any Explorer drag begins.
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.context = None
        self.page = 0
        self.hover = None
        self.center = QPointF()
        self.open_point = QPointF()
        self.armed = True
        self.radius = settings.radius
        self.mode = "click"
        self.backdrop = None
        self.glow = [0.] * 8
        self.shown_stats = []
        self.started = time.monotonic()
        self.wanted_level, self.wanted_reasons = 0, []
        self.drag_seen, self.dropped = False, False
        self.scan_generation = 0
        self.last_shift = win32.key_down(0x10)
        self.last_keys = {}
        self.last_scroll = 0.
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        # Construct the native handle while hidden, making the drop target ready.
        self.winId()

    @property
    def selected(self):
        if not self.context or self.hover is None:
            return None
        slots = self.context.pages[self.page].slots
        return slots[self.hover] if self.hover < len(slots) else None

    def open_files(self, files, mode="click", at=None, scan=True):
        self.hide()
        point = at or screen_for().availableGeometry().center()
        screen = screen_for(point)
        frame = screen.geometry()
        self.setGeometry(frame)
        self.radius = min(self.settings.radius, (frame.height()-82)/2, (frame.width()-80)/2)
        margin = self.radius+30
        local = QPointF(point-frame.topLeft())
        self.center = QPointF(min(max(local.x(), margin), frame.width()-margin), min(max(local.y(), margin), frame.height()-margin))
        self.open_point = local
        self.armed = math.hypot(local.x()-self.center.x(), local.y()-self.center.y()) < 4
        self.context = catalog.context(files)
        self.mode, self.page, self.hover = mode, 0, None
        self.drag_seen, self.dropped = False, False
        self.wanted_level, self.wanted_reasons = 0, []
        self.glow, self.shown_stats = [0.]*8, list(self.context.base)
        self.started = time.monotonic()
        self.last_shift = win32.key_down(0x10)
        self.last_keys = {key: win32.key_down(key) for key in (0x1B, 0x09, 0x51, 0x45, 0x0D, 0x20)}
        self.scan_generation += 1
        self.backdrop = blurred_screen(screen) if self.settings.get("blur") else None
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, mode == "drag")
        self.show()
        self.raise_()
        if mode != "drag":
            self.activateWindow()
            self.setFocus()
        self.timer.start()
        self.sounds.play("open")
        if mode == "demo":
            self.wanted_level, self.wanted_reasons = 3, ["GPS 定位", "iPhone 15 Pro", "拍摄时间"]
        elif files and scan:
            self.scan()

    def scan(self):
        if not self.owner:
            return
        token = self.scan_generation
        files = list(self.context.files)
        def operation(_):
            found = [scan_privacy(path) for path in files[:24]]
            worst = max(found, key=lambda result: result.level, default=None)
            return worst
        def complete(found):
            if not found or not self.isVisible() or token != self.scan_generation:
                return
            self.wanted_level, self.wanted_reasons = found.level, found.reasons
            if found.level:
                self.sounds.play("wanted")
            self.update()
        self.owner.submit(operation, complete, lambda error: log.warning("Privacy scan: %s", error))

    def close_wheel(self):
        if not self.isVisible():
            return
        self.timer.stop()
        self.scan_generation += 1
        self.hide()
        self.backdrop = None
        self.closed.emit()

    def update_hover(self, point):
        if not self.armed:
            if math.hypot(point.x()-self.open_point.x(), point.y()-self.open_point.y()) <= 12:
                return
            self.armed = True
        new = slot_at(point, self.center, self.radius, self.hover)
        if new != self.hover:
            self.hover = new
            if self.selected:
                self.sounds.play("tick")
            self.update()

    def flip_page(self):
        if self.context and len(self.context.pages)>1:
            self.page = (self.page+1) % len(self.context.pages)
            self.sounds.play("page")
            self.update()

    def execute(self):
        option = self.selected
        if option is None:
            self.close_wheel()
            return
        if not option.enabled:
            self.sounds.play("denied")
            return
        files = list(self.context.files)
        mode = self.mode
        self.close_wheel()
        if mode == "demo":
            if self.owner:
                self.owner.demo_result(option)
        else:
            self.chosen.emit(option, files)

    def tick(self):
        point = QPointF(self.mapFromGlobal(QCursor.pos()))
        self.update_hover(point)
        shift = win32.key_down(0x10)
        if shift and not self.last_shift:
            self.flip_page()
        self.last_shift = shift
        if self.mode == "drag":
            # OLE owns keyboard dispatch during a drag; poll these keys as well.
            for key in (0x1B, 0x09, 0x51, 0x45):
                down = win32.key_down(key)
                if down and not self.last_keys.get(key):
                    if key == 0x1B:
                        self.close_wheel()
                    else:
                        self.flip_page()
                self.last_keys[key] = down
        for index in range(8):
            self.glow[index] += ((1 if index==self.hover else 0)-self.glow[index])*.25
        selected = self.selected
        target = (selected.stats if selected and selected.enabled else None) or self.context.base
        if len(self.shown_stats) != len(target):
            self.shown_stats = list(target)
        else:
            self.shown_stats = [a+(b-a)*.2 for a, b in zip(self.shown_stats, target)]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.backdrop:
            p.drawPixmap(self.rect(), self.backdrop)
        p.fillRect(self.rect(), QColor(0, 0, 0, 85 if self.backdrop else 95))
        vignette = QRadialGradient(self.center, math.hypot(self.width(), self.height())*.7)
        vignette.setColorAt(.15, QColor(0, 0, 0, 0))
        vignette.setColorAt(1, QColor(0, 0, 0, 150))
        p.fillRect(self.rect(), vignette)
        if not self.context:
            return
        accent = QColor(self.settings.accent)
        pop = min(1., (time.monotonic()-self.started)/.15)
        paint_wheel(p, self.context, self.page, self.hover, self.center, self.radius, self.settings, self.glow, pop)
        ring = QRectF(self.center.x()-self.radius, self.center.y()-self.radius, self.radius*2, self.radius*2)
        help_rect = QRectF(28, 28, 316, 115)
        if ring.intersects(help_rect):
            help_rect.moveBottom(self.height()-28)
        panel(p, help_rect, accent)
        lines = (["Shift / Tab / Q / E  切换 转换 / 工具", "朝格子方向拖，松开鼠标执行", "移回中心松开 = 取消 · Esc 关闭"] if self.mode == "drag" else
                 ["Shift / Tab / 滚轮  切换 转换 / 工具", "点击格子执行 · 中心 / Esc 取消", "演示模式 / Demo" if self.mode == "demo" else "文件保留，结果保存到原文件旁"])
        for i, line in enumerate(lines):
            text(p, line, QRectF(help_rect.x()+14, help_rect.y()+12+i*30, help_rect.width()-28, 26), 14,
                 align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        stats_height = 84+len(self.context.stat_labels)*27
        stats_rect = QRectF(self.width()-344, 28, 316, stats_height)
        wanted_rect = QRectF(self.width()-408, stats_rect.bottom()+8, 380, 70)
        if ring.intersects(stats_rect) or ring.intersects(wanted_rect):
            wanted_rect.moveBottom(self.height()-28)
            stats_rect.moveBottom(wanted_rect.top()-8)
        paint_stats(p, self.context, self.selected, stats_rect, accent, self.shown_stats)
        evading = bool(self.selected and self.selected.enabled and self.selected.id.endswith(".strip"))
        paint_wanted(p, wanted_rect, self.wanted_level, self.wanted_reasons, time.monotonic()-self.started, evading)
        if self.mode == "drag" and not self.context.files:
            text(p, "把文件拖到轮盘上 / Drag your files onto the wheel", QRectF(0, self.height()-78, self.width(), 36), 20)
        p.end()

    def mouseMoveEvent(self, event):
        self.update_hover(event.position())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.close_wheel()
        elif self.mode != "drag":
            self.update_hover(event.position())
            self.execute()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_wheel()
        elif event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Q, Qt.Key.Key_E):
            self.flip_page()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.execute()
        else:
            super().keyPressEvent(event)

    def event(self, event):
        # QWidget normally consumes Tab for focus traversal before keyPressEvent.
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Tab:
            self.flip_page()
            return True
        return super().event(event)

    def wheelEvent(self, event):
        if time.monotonic()-self.last_scroll>.18 and abs(event.angleDelta().y())>20:
            self.last_scroll = time.monotonic()
            self.flip_page()
        event.accept()

    @staticmethod
    def paths(mime):
        return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile() and Path(url.toLocalFile()).exists()]

    def dragEnterEvent(self, event):
        if not supports_copy(event):
            event.ignore()
            return
        files = self.paths(event.mimeData())
        if not files:
            event.ignore()
            return
        self.drag_seen = True
        if self.mode != "demo" and list(self.context.files) != files:
            self.context = catalog.context(files)
            self.shown_stats = list(self.context.base)
            self.page = min(self.page, len(self.context.pages)-1)
            self.scan()
        self.update_hover(event.position())
        # Always accept the drag; center/disabled slots are consumed safely on drop.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragMoveEvent(self, event):
        if not supports_copy(event):
            event.ignore()
            return
        self.update_hover(event.position())
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dropEvent(self, event):
        if not supports_copy(event):
            event.ignore()
            self.close_wheel()
            return
        files = self.paths(event.mimeData())
        self.update_hover(event.position())
        self.dropped = True
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if files:
            self.context.files = files
        if self.selected is None or not self.selected.enabled:
            if self.selected:
                self.sounds.play("denied")
            self.close_wheel()
        else:
            self.execute()

    def dragLeaveEvent(self, event):
        if self.mode == "drag":
            # Fullscreen target normally cannot be left except across displays.
            self.close_wheel()

    def closeEvent(self, event):
        self.close_wheel()
        event.ignore()


class Banner(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(OVERLAY_FLAGS | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.passed, self.title, self.detail = True, "", ""
        self.started = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.animate)

    def display(self, passed, title, detail):
        self.passed, self.title, self.detail = passed, title, detail
        self.setGeometry(screen_for().geometry())
        self.started = time.monotonic()
        self.show()
        self.raise_()
        self.timer.start()

    def animate(self):
        if time.monotonic()-self.started > (2.6 if self.passed else 4):
            self.hide()
            self.timer.stop()
        else:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        elapsed = time.monotonic()-self.started
        p.setOpacity(min(1., elapsed/.2))
        if not self.passed:
            p.fillRect(self.rect(), QColor(0, 0, 0, 155))
        band = QRectF(0, self.height()/2-120, self.width(), 210)
        shade = QRadialGradient(band.center(), self.width()/2)
        shade.setColorAt(0, QColor(0, 0, 0, 215))
        shade.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(band, shade)
        text(p, "MISSION PASSED" if self.passed else "WASTED", QRectF(0, band.y()+15, self.width(), 93), 72 if self.passed else 84, GOLD if self.passed else LOSS, True)
        text(p, self.title, QRectF(self.width()*.1, band.y()+115, self.width()*.8, 30), 22)
        text(p, self.detail, QRectF(self.width()*.12, band.y()+150, self.width()*.76, 46), 16, QColor("#ccccd0"), wrap=True)
        p.end()


class Busy(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(OVERLAY_FLAGS | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.label = ""
        self.started = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(32)
        self.timer.timeout.connect(self.update)

    def display(self, label):
        self.label = label
        frame = screen_for().availableGeometry()
        self.setGeometry(frame.right()-420, frame.bottom()-90, 400, 60)
        self.started = time.monotonic()
        self.show()
        self.timer.start()

    def dismiss(self):
        self.hide()
        self.timer.stop()

    def paintEvent(self, event):
        from PySide6.QtGui import QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 195))
        text(p, self.label, QRectF(14, 8, 330, 44), 16)
        p.setPen(QPen(WHITE, 3))
        p.drawArc(QRectF(357, 20, 20, 20), int(-(time.monotonic()-self.started)*220*16), 230*16)
        p.end()


class WantedHUD(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(OVERLAY_FLAGS | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.started, self.level = 0., 0
        self.timer = QTimer(self)
        self.timer.setInterval(32)
        self.timer.timeout.connect(self.animate)

    def evade(self, level):
        frame = screen_for().availableGeometry()
        self.setGeometry(frame.right()-408, frame.top()+240, 380, 90)
        self.started, self.level = time.monotonic(), level
        self.show()
        self.raise_()
        self.timer.start()

    def animate(self):
        if time.monotonic()-self.started>2.4:
            self.hide()
            self.timer.stop()
        else:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        elapsed = time.monotonic()-self.started
        p.setOpacity(max(0., min(1., (2.4-elapsed)/.45)))
        paint_wanted(p, QRectF(0, 0, 380, 70), self.level, [], elapsed, True, "已甩掉警察 / WANTED LEVEL CLEARED")
        p.end()


class DropDock(QWidget):
    """A discoverable direct drop target, also useful when the notification tray is hidden."""
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setWindowTitle("FormatWheel · 格式轮盘")
        self.setWindowIcon(tray_icon(owner.settings.accent))
        self.setAcceptDrops(True)
        self.setMinimumSize(540, 300)
        self.resize(600, 330)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#191b22"))
        text(p, "FORMATWHEEL", QRectF(25, 22, self.width()-50, 48), 34, bold=True)
        text(p, "拖着文件按 Shift，呼出格式轮盘", QRectF(25, 83, self.width()-50, 36), 24)
        text(p, "Drag files in Explorer, then press Shift", QRectF(25, 122, self.width()-50, 30), 18, QColor("#bbc5d5"))
        text(p, "也可以把文件拖到这里，或点击选择文件", QRectF(25, 187, self.width()-50, 35), 20, QColor(self.owner.settings.accent))
        text(p, "Drop files here or click to choose · Right-click for menu", QRectF(25, 228, self.width()-50, 28), 15, QColor("#a1a6b2"))
        text(p, "转换在本机完成 · 原文件保留 / Local processing · Originals kept", QRectF(25, self.height()-40, self.width()-50, 28), 13, QColor("#9398a4"))
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.owner.menu.exec(event.globalPosition().toPoint())
        else:
            self.owner.choose_files()

    def dragEnterEvent(self, event):
        if supports_copy(event) and Overlay.paths(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if supports_copy(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not supports_copy(event):
            event.ignore()
            return
        files = Overlay.paths(event.mimeData())
        if files:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.hide()
            QTimer.singleShot(0, lambda: self.owner.overlay.open_files(files))

    def closeEvent(self, event):
        self.hide()
        event.ignore()


class DragProbe(QWidget):
    """An almost transparent OLE target distinguishes a file drag from mouse selection."""
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setWindowFlags(OVERLAY_FLAGS | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.winId()

    def begin(self, point):
        self.setGeometry(screen_for(point).geometry())
        self.show()
        self.raise_()

    def paintEvent(self, event):
        # Alpha zero layered pixels are excluded from Windows hit testing.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        painter.end()

    def dragEnterEvent(self, event):
        if not supports_copy(event):
            event.ignore()
            return
        files = Overlay.paths(event.mimeData())
        if not files:
            event.ignore()
            self.hide()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        point = QCursor.pos()
        # Finish this native OLE callback before replacing its destination window.
        def activate():
            self.hide()
            if win32.key_down(1):
                self.owner.overlay.open_files(files, mode="drag", at=point)
        QTimer.singleShot(0, activate)

    def dragMoveEvent(self, event):
        if not supports_copy(event):
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dropEvent(self, event):
        if not supports_copy(event):
            event.ignore()
            self.hide()
            return
        # A release before the full wheel has appeared is a center cancellation.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.hide()


class DragWatcher(QObject):
    """Observe native key/button state without installing input hooks or requesting elevation."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.probe = DragProbe(owner)
        self.left, self.shift, self.start = False, False, QPoint()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def poll(self):
        left, shift = win32.key_down(1), win32.key_down(0x10)
        point = QCursor.pos()
        overlay = self.owner.overlay
        if left and not self.left:
            self.start = point
        moved = (point-self.start).manhattanLength() >= QApplication.startDragDistance()
        if left and moved and shift and not self.shift and not overlay.isVisible() and not self.owner.running:
            self.probe.begin(point)
        if not left and self.left:
            self.probe.hide()
        if not left and self.left and overlay.isVisible() and overlay.mode == "drag":
            # Qt's OLE Drop callback must win over polling. A canceled drag does nothing.
            QTimer.singleShot(180, lambda: overlay.close_wheel() if overlay.isVisible() and overlay.mode == "drag" else None)
        self.left, self.shift = left, shift


class TrayApplication(QObject):
    def __init__(self, files=None, preview=False, background=False):
        super().__init__()
        self.settings = Settings()
        self.sounds = Sounds(self.settings)
        self.pool = QThreadPool.globalInstance()
        self.tasks = set()
        self.running = False
        self.last_error = ""
        self.ipc_sockets = set()
        self.overlay = Overlay(self.settings, self.sounds, self)
        self.overlay.chosen.connect(self.run_action)
        self.banner, self.busy = Banner(), Busy()
        self.zip_progress = ZipProgressPanel(self.settings.accent)
        self.zip_control = None
        self.wanted_hud = WantedHUD()
        self.dock = DropDock(self)
        self.tray = QSystemTrayIcon(tray_icon(self.settings.accent), self)
        self.tray.setToolTip("格式轮盘 / FormatWheel · 拖着文件按 Shift")
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self.build_menu)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_clicked)
        self.tray.messageClicked.connect(self.message_clicked)
        self.build_menu()
        self.tray.show()
        self.watcher = DragWatcher(self)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        if files:
            QTimer.singleShot(100, lambda: self.overlay.open_files([Path(p) for p in files]))
        elif preview:
            QTimer.singleShot(100, self.show_demo)
        elif not background and not self.settings.get("welcomed"):
            self.settings.set("welcomed", True)
            QTimer.singleShot(300, self.show_dock)
            self.tray.showMessage("FormatWheel 已启动", "拖着文件按 Shift 呼出轮盘。右键系统托盘图标可选择文件、设置和退出。")

    def submit(self, function, complete, failed=None, progress=None):
        task = Task(function)
        self.tasks.add(task)
        mailbox = ProgressMailbox(progress) if progress else None
        task.progress_mailbox = mailbox
        def done(result):
            if mailbox:
                mailbox.flush()
            self.tasks.discard(task)
            complete(result)
        def error(message):
            if mailbox:
                mailbox.flush()
            self.tasks.discard(task)
            if failed:
                failed(message)
        task.signals.done.connect(done, Qt.ConnectionType.QueuedConnection)
        task.signals.failed.connect(error, Qt.ConnectionType.QueuedConnection)
        if progress:
            task.signals.progress.connect(mailbox.push, Qt.ConnectionType.DirectConnection)
        self.pool.start(task)

    def shutdown(self):
        self.watcher.timer.stop()
        self.tray.hide()
        if self.zip_control and self.zip_progress.active:
            # Session shutdown must also release a worker waiting in Pause.
            self.zip_control.cancel()
        # Qt waits for conversions to finish rather than destroying an active worker.
        self.pool.waitForDone()

    def accept_ipc(self):
        while self.ipc_server.hasPendingConnections():
            socket = self.ipc_server.nextPendingConnection()
            self.ipc_sockets.add(socket)
            data = bytearray()
            def received(sock=socket, buffer=data):
                buffer.extend(bytes(sock.readAll()))
                if b"\n" not in buffer:
                    return
                try:
                    message = json.loads(bytes(buffer).split(b"\n", 1)[0].decode("utf-8"))
                    files = [Path(p) for p in message.get("files", []) if Path(p).exists()]
                    if files and not self.running:
                        self.dock.hide()
                        self.overlay.open_files(files)
                    elif message.get("preview"):
                        self.show_demo()
                    elif not message.get("background"):
                        self.show_dock()
                except (ValueError, TypeError, OSError):
                    log.warning("Ignoring malformed local launch message")
                sock.disconnectFromServer()
            def disconnected(sock=socket):
                self.ipc_sockets.discard(sock)
                sock.deleteLater()
            socket.readyRead.connect(received)
            socket.disconnected.connect(disconnected)
            received()

    def show_dock(self):
        self.dock.show()
        self.dock.raise_()
        self.dock.activateWindow()

    def tray_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.zip_progress.active:
                self.zip_progress.restore()
            else:
                self.show_dock()

    def message_clicked(self):
        if self.last_error:
            QMessageBox.warning(self.dock, "FormatWheel", self.last_error)
        elif self.settings.get("recents"):
            win32.reveal(Path(self.settings.get("recents")[0]))

    def choose_files(self):
        self.overlay.close_wheel()
        files, _ = QFileDialog.getOpenFileNames(self.dock, "选择文件打开轮盘 / Choose files", "", "所有文件 / All files (*)")
        if files:
            self.dock.hide()
            self.overlay.open_files([Path(p) for p in files])

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self.dock, "选择文件夹 / Choose folder")
        if folder:
            self.dock.hide()
            self.overlay.open_files([Path(folder)])

    def show_demo(self):
        self.dock.hide()
        self.overlay.open_files(demo_files(), mode="demo")

    def preference(self, key, value, preview=False):
        self.settings.set(key, value)
        self.tray.setIcon(tray_icon(self.settings.accent))
        if preview:
            self.show_demo()

    def build_menu(self):
        self.menu.clear()
        self.menu.addAction("格式轮盘 / FormatWheel").setEnabled(False)
        self.menu.addAction("拖着文件按 Shift / Drag files + Shift").setEnabled(False)
        self.menu.addSeparator()
        self.menu.addAction("看看效果 / Demo", self.show_demo)
        self.menu.addAction("选择文件打开轮盘… / Choose files…", self.choose_files)
        self.menu.addAction("选择文件夹… / Choose folder…", self.choose_folder)
        self.menu.addAction("打开拖放窗口 / Open drop window", self.show_dock)
        if self.zip_progress.control is not None:
            self.menu.addAction("显示 ZIP 进度 / Show ZIP progress", self.zip_progress.restore)
        recent = self.menu.addMenu("最近转换 · 在资源管理器显示 / Recent outputs")
        for name in self.settings.get("recents"):
            path = Path(name)
            action = recent.addAction(f"{path.name}  —  {path.parent.name}", lambda checked=False, p=path: win32.reveal(p))
            action.setEnabled(path.exists())
        if not self.settings.get("recents"):
            recent.addAction("还没有转换过文件 / No outputs yet").setEnabled(False)
        self.menu.addSeparator()
        for title, key, values in (("角色配色 / Crew color", "crew", {name: spec[0] for name, spec in CREWS.items()}),
                                   ("格子图标 / Slot icons", "icons", {"formats": "格式图标 / Formats", "weapons": "GTA 武器 / Weapons"}),
                                   ("轮盘大小 / Wheel size", "size", {name: spec[0] for name, spec in SIZES.items()})):
            submenu = self.menu.addMenu(title)
            group = QActionGroup(submenu)
            group.setExclusive(True)
            for value, label in values.items():
                action = submenu.addAction(label)
                action.setCheckable(True)
                action.setChecked(self.settings.get(key)==value)
                group.addAction(action)
                action.triggered.connect(lambda checked=False, k=key, v=value: self.preference(k, v, True))
        for key, title in (("sound", "音效 / Sound effects"), ("blur", "背景虚化 / Background blur"), ("banner", "完成横幅 / MISSION PASSED banner")):
            action = self.menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(bool(self.settings.get(key)))
            action.triggered.connect(lambda checked, k=key: self.preference(k, checked))
        startup = self.menu.addAction("登录时自动启动 / Start with Windows")
        startup.setCheckable(True)
        startup.setChecked(win32.startup_enabled())
        startup.triggered.connect(self.toggle_startup)
        self.menu.addSeparator()
        missing = [name for name in ("ffmpeg", "soffice", "tesseract", "pandoc") if not find_tool(name)]
        self.menu.addAction("工具就绪 / Tools ready" if not missing else "未装备 / Optional tools: " + ", ".join(missing)).setEnabled(False)
        self.menu.addAction("退出格式轮盘 / Quit", self.quit)

    def toggle_startup(self, enabled):
        try:
            win32.set_startup(enabled)
        except OSError as error:
            QMessageBox.warning(self.dock, "无法设置自动启动 / Startup setting failed", str(error))

    def quit(self):
        if self.running:
            self.tray.showMessage("FormatWheel", "正在转换，完成后再退出。 / A conversion is still running.")
            return
        QApplication.instance().quit()

    def demo_result(self, option):
        self.sounds.play("passed")
        self.banner.display(True, option.title, "演示完成 · 没有修改文件 / Demo complete")

    def run_action(self, option, files):
        if self.running:
            self.tray.showMessage("FormatWheel", "请等待当前转换完成 / Please wait for the current operation")
            return
        self.running = True
        self.last_error = ""
        wanted_level = self.overlay.wanted_level
        is_zip = option.id == "gen.zip"
        if is_zip:
            self.zip_control = OperationControl()
            self.zip_progress.begin(self.zip_control)
        else:
            self.zip_progress.hide()
            self.busy.display(f"{option.title}…")
        def progress(value):
            if is_zip and hasattr(value, "phase"):
                self.zip_progress.apply_update(value)
                return
            try:
                percent = int(float(value)*100)
                self.busy.label = f"{option.title}… {max(0, min(100, percent))}%"
            except (ValueError, TypeError):
                self.busy.label = str(value)
        def complete(result):
            self.running = False
            self.busy.dismiss()
            if is_zip:
                self.zip_progress.finish(result.outputs)
            if result.clip is not None:
                QApplication.clipboard().setText(result.clip)
            if result.outputs:
                self.settings.add_recent(result.outputs)
            cue = {"pistol": "rackPistol", "silencedPistol": "rackPistol", "microSMG": "rackPistol", "smg": "rackPistol",
                   "rifle": "rackRifle", "sniper": "rackBolt", "shotgun": "rackPump", "rpg": "rackHeavy", "minigun": "rackHeavy",
                   "jerryCan": "rackHeavy", "grenade": "pinPull", "stickyBomb": "pinPull", "molotov": "pinPull", "knife": "bladeDraw"}.get(weapon_name(option.id), "meleeSwing")
            self.sounds.play(cue)
            evaded = option.id.endswith(".strip") and wanted_level>0
            QTimer.singleShot(300, lambda: self.sounds.play("evaded" if evaded else "passed"))
            detail = result.note or (f"{len(result.outputs)} 个文件 / files" if result.outputs else "已完成 / Done")
            if evaded:
                self.wanted_hud.evade(wanted_level)
                detail = "通缉 " + "★"*wanted_level + " 已解除 / Privacy traces removed"
            if result.outputs:
                detail += f" · 保存到 / Saved to: {Path(result.outputs[0]).parent}"
            if self.settings.get("banner"):
                self.banner.display(True, option.title, detail)
            self.tray.showMessage(f"MISSION PASSED · {option.title}", detail, QSystemTrayIcon.MessageIcon.Information, 5000)
        def failed(error):
            self.running = False
            self.busy.dismiss()
            if isinstance(error, OperationCancelled):
                if is_zip:
                    self.zip_progress.cancelled()
                self.last_error = ""
                self.tray.showMessage("ZIP 已取消 / ZIP canceled", "未完成的 ZIP 已清理，原文件保留。 / Partial archive removed. Originals kept.", QSystemTrayIcon.MessageIcon.Information, 5000)
                return
            message = str(error)
            if is_zip:
                self.zip_progress.failed(message)
            self.last_error = message
            self.sounds.play("wasted")
            self.banner.display(False, option.title, message)
            self.tray.showMessage(f"WASTED · {option.title}", message, QSystemTrayIcon.MessageIcon.Warning, 10000)
        control = self.zip_control if is_zip else None
        self.submit(lambda notify: Engine.run(option.id, files, progress=notify, control=control), complete, failed, progress)


def application():
    win32.set_app_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("FormatWheel")
    app.setOrganizationName("FormatWheel")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(tray_icon())
    return app


def _forward_launch(server_name, files, preview, background):
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(250):
        return False
    message = {"files": [str(Path(p).absolute()) for p in files or []], "preview": preview, "background": background}
    socket.write(json.dumps(message).encode("utf-8")+b"\n")
    socket.flush()
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return True


def run_gui(files=None, preview=False, background=False):
    app = application()
    identity = os.environ.get("USERNAME", "user")+os.environ.get("APPDATA", "")
    server_name = "FormatWheel-"+hashlib.sha256(identity.encode()).hexdigest()[:16]
    if _forward_launch(server_name, files, preview, background):
        return 0
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(server_name)
    if not server.listen(server_name):
        # Two simultaneous launches can both finish their initial connection check.
        if _forward_launch(server_name, files, preview, background):
            return 0
        raise RuntimeError("Unable to start FormatWheel local instance: "+server.errorString())
    owner = TrayApplication(files, preview, background)
    owner.ipc_server = server
    server.setParent(owner)
    server.newConnection.connect(owner.accept_ipc)
    app._formatwheel = owner
    return app.exec()


def snapshot(path, files=None, page=0, hover=None, background=False):
    app = application()
    settings = Settings()
    sounds = Sounds(settings)
    previous = settings.values["sound"]
    settings.values["sound"] = False
    settings.values["blur"] = bool(background)
    overlay = Overlay(settings, sounds)
    overlay.open_files([Path(p) for p in files] if files else demo_files(), "demo", scan=False)
    if not background:
        overlay.backdrop = QPixmap(overlay.size())
        overlay.backdrop.fill(QColor("#242a35"))
    overlay.page = max(0, min(page, len(overlay.context.pages)-1))
    overlay.hover = hover if hover is not None and 0 <= hover < 8 else None
    overlay.glow = [float(index==overlay.hover) for index in range(8)]
    overlay.started = time.monotonic()-1
    app.processEvents()
    target = Path(path).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not overlay.grab().save(str(target)):
        raise OSError(f"Could not save snapshot: {target}")
    overlay.close_wheel()
    settings.values["sound"] = previous
    return target


def export_contact_sheet(path, weapons=False):
    app = application()
    ids = catalog.all_ids()
    width, cell = 1200, 150
    image = QImage(width, math.ceil(len(ids)/8)*135, QImage.Format.Format_RGB32)
    image.fill(QColor("#292c34"))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for index, action in enumerate(ids):
        x, y = (index%8)*cell, (index//8)*135
        if weapons:
            weapon(p, action, QRectF(x+14, y+15, 122, 64))
        else:
            glyph(p, action, QRectF(x+43, y+12, 64, 64), "#3380e6")
        text(p, action, QRectF(x+4, y+86, 142, 34), 12, wrap=True)
    p.end()
    path = Path(path).absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path)):
        raise OSError(f"Could not save contact sheet: {path}")
    return path
