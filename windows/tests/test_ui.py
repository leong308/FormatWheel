"""Direction selection and real Qt file-drop events protect the Explorer workflow."""
from __future__ import annotations

import math
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QMimeData, QObject, QPoint, QPointF, Qt, QThreadPool, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest

from formatwheel import catalog
from formatwheel.drawing import slot_at
from formatwheel.settings import Settings
from formatwheel.sound import Sounds
from formatwheel.ui import DragProbe, DropDock, Overlay, TrayApplication, application


class WheelInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="FormatWheel-UI-")
        self.folder = Path(self.temp.name)
        from PIL import Image
        self.source = self.folder / "中文 source.png"
        Image.new("RGBA", (30, 20), (10, 20, 30, 120)).save(self.source)
        self.original = self.source.read_bytes()
        self.settings = Settings(self.folder / "preferences.json")
        self.settings.values.update(sound=False, blur=False)
        self.overlay = Overlay(self.settings, Sounds(self.settings))
        self.overlay.open_files([self.source], scan=False)
        self.chosen = []
        self.overlay.chosen.connect(lambda option, paths: self.chosen.append((option.id, paths)))

    def tearDown(self):
        self.overlay.close_wheel()
        self.overlay.deleteLater()
        self.app.processEvents()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.temp.cleanup()

    def test_all_eight_directions_continue_beyond_ring(self):
        center = QPointF(500, 500)
        for index in range(8):
            angle = index*math.pi/4
            point = QPointF(center.x()+900*math.sin(angle), center.y()-900*math.cos(angle))
            self.assertEqual(slot_at(point, center, 285), index)

    def test_center_is_safe_cancel_zone(self):
        center = self.overlay.center
        self.assertIsNone(slot_at(center, center, self.overlay.radius))
        self.assertIsNone(slot_at(center+QPointF(5, 8), center, self.overlay.radius))
        self.overlay.hover = None
        self.overlay.execute()
        self.assertEqual(self.chosen, [])
        self.assertFalse(self.overlay.isVisible())

    def test_current_format_cannot_execute(self):
        self.assertEqual(self.overlay.context.pages[0].slots[0].id, "img.to.png")
        self.assertFalse(self.overlay.context.pages[0].slots[0].enabled)
        self.overlay.hover = 0
        self.overlay.execute()
        self.assertEqual(self.chosen, [])
        self.assertTrue(self.overlay.isVisible())

    def test_enabled_action_emits_files_once_and_hides(self):
        self.overlay.hover = 1
        self.overlay.execute()
        self.assertEqual(self.chosen, [("img.to.jpg", [self.source])])
        self.assertFalse(self.overlay.isVisible())

    def test_tab_reaches_tools_and_escape_cancels(self):
        QTest.keyClick(self.overlay, Qt.Key.Key_Tab)
        self.assertEqual(self.overlay.page, 1)
        self.assertEqual(self.overlay.context.pages[1].slots[0].id, "img.compress")
        QTest.keyClick(self.overlay, Qt.Key.Key_Escape)
        self.assertFalse(self.overlay.isVisible())
        self.assertEqual(self.chosen, [])

    def file_mime(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.source))])
        return mime

    def test_center_drop_consumes_copy_without_conversion(self):
        self.overlay.mode = "drag"
        mime = self.file_mime()
        entered = QDragEnterEvent(self.overlay.center.toPoint(), Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                                  mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
        self.overlay.dragEnterEvent(entered)
        self.assertTrue(entered.isAccepted())
        drop = QDropEvent(self.overlay.center, Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                          mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
        self.overlay.dropEvent(drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(drop.dropAction(), Qt.DropAction.CopyAction)
        self.assertEqual(self.chosen, [])

    def test_flick_drop_uses_direction_and_copy_action(self):
        self.overlay.mode = "drag"
        point = self.overlay.center+QPointF(self.overlay.radius*1.5, -self.overlay.radius*1.5)
        mime = self.file_mime()
        drop = QDropEvent(point, Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                          mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
        self.overlay.dropEvent(drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(drop.dropAction(), Qt.DropAction.CopyAction)
        self.assertEqual(self.chosen, [("img.to.jpg", [self.source])])

    def test_move_only_drop_never_executes_or_accepts_even_at_center(self):
        mime = self.file_mime()
        for point in (self.overlay.center, self.overlay.center+QPointF(200, -200)):
            with self.subTest(point=point):
                self.overlay.open_files([self.source], mode="drag", scan=False)
                event = QDropEvent(point, Qt.DropAction.MoveAction, mime,
                                   Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
                self.overlay.dropEvent(event)
                self.assertFalse(event.isAccepted())
                self.assertFalse(self.overlay.isVisible())
                self.assertEqual(self.chosen, [])

    def test_all_drop_targets_reject_move_only_enter_move_and_drop(self):
        owner = SimpleNamespace(settings=self.settings, overlay=self.overlay)
        targets = [self.overlay, DropDock(owner), DragProbe(owner)]
        mime = self.file_mime()
        for target in targets:
            for event_type, handler in ((QDragEnterEvent, "dragEnterEvent"), (QDragMoveEvent, "dragMoveEvent"), (QDropEvent, "dropEvent")):
                with self.subTest(target=type(target).__name__, event=handler):
                    point = QPointF(100, 100) if event_type is QDropEvent else QPoint(100, 100)
                    event = event_type(point, Qt.DropAction.MoveAction, mime,
                                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier)
                    getattr(target, handler)(event)
                    self.assertFalse(event.isAccepted())
                    self.assertEqual(self.chosen, [])
        for target in targets[1:]:
            target.deleteLater()

    def test_worker_completion_is_dispatched_on_gui_thread(self):
        class Harness(QObject):
            submit = TrayApplication.submit
        owner = Harness()
        owner.tasks, owner.pool = set(), QThreadPool.globalInstance()
        gui_thread = threading.get_ident()
        delivered = []
        owner.submit(lambda notify: threading.get_ident(),
                     lambda worker: delivered.append((worker, threading.get_ident())))
        deadline = time.monotonic()+5
        while not delivered and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertEqual(len(delivered), 1)
        self.assertNotEqual(delivered[0][0], gui_thread)
        self.assertEqual(delivered[0][1], gui_thread)


if __name__ == "__main__":
    unittest.main()
