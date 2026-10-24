"""Real streamed compression reaches the interactive panel through Qt's worker queue."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QThreadPool

from formatwheel.engine import Engine, OperationCancelled, OperationControl
from formatwheel.progress_ui import ZipProgressPanel
from formatwheel.ui import TrayApplication, application


class WorkerHarness(QObject):
    submit = TrayApplication.submit

    def __init__(self):
        super().__init__()
        self.tasks = set()
        self.pool = QThreadPool()


class ZipWorkerPanelIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="FormatWheel ZIP UI integration ")
        self.folder = Path(self.temporary.name).resolve()
        self.source = self.folder / "中文 large source.bin"
        block = os.urandom(1 << 20)
        with self.source.open("wb") as stream:
            for _ in range(64):
                stream.write(block)
        self.original = self.digest(self.source)
        self.control = OperationControl()
        self.owner = WorkerHarness()
        self.panel = ZipProgressPanel(open_folder=lambda _path: None, reveal=lambda _path: None)
        self.panel.begin(self.control, show=False)
        self.updates, self.outcomes = [], []
        self.gui_thread = threading.get_ident()

    @staticmethod
    def digest(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").digest()

    def wait_until(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.003)
        self.assertTrue(predicate(), "The expected ZIP/UI state did not arrive")

    def start(self, pause_after_first_chunk=False):
        pause_requested = False

        def update(event):
            nonlocal pause_requested
            self.assertEqual(threading.get_ident(), self.gui_thread)
            self.updates.append(event)
            self.panel.apply_update(event)
            if pause_after_first_chunk and not pause_requested and event.phase == "compressing" and event.processed_bytes:
                pause_requested = True
                self.panel.pause_button.click()

        def complete(result):
            self.panel.finish(result.outputs)
            self.outcomes.append(result)

        def failed(error):
            if isinstance(error, OperationCancelled):
                self.panel.cancelled()
            else:
                self.panel.failed(str(error))
            self.outcomes.append(error)

        self.owner.submit(lambda notify: Engine.run("gen.zip", [self.source], progress=notify, control=self.control),
                          complete, failed, update)

    def tearDown(self):
        self.control.cancel()
        self.owner.pool.waitForDone(15000)
        self.app.processEvents()
        self.panel.timer.stop()
        self.panel.hide()
        self.panel.deleteLater()
        self.app.processEvents()
        self.assertEqual(self.digest(self.source), self.original)
        self.temporary.cleanup()

    def test_live_pause_resume_reaches_valid_completed_archive(self):
        self.start(pause_after_first_chunk=True)
        self.wait_until(lambda: any(event.phase == "paused" for event in self.updates))
        paused_bytes = self.updates[-1].processed_bytes
        self.assertGreater(paused_bytes, 0)
        self.assertLess(paused_bytes, self.source.stat().st_size)
        until = time.monotonic() + .15
        while time.monotonic() < until:
            self.app.processEvents()
            time.sleep(.003)
        self.assertEqual(self.updates[-1].processed_bytes, paused_bytes)
        self.assertTrue(self.control.is_paused)
        self.assertIn("Resume", self.panel.pause_button.text())
        self.panel.pause_button.click()
        self.wait_until(lambda: bool(self.outcomes))
        self.assertNotIsInstance(self.outcomes[0], Exception)
        self.assertTrue(self.panel.terminal)
        self.assertEqual(self.panel.percent_label.text(), "100%")
        self.assertEqual(self.updates[-1].phase, "completed")
        with zipfile.ZipFile(self.outcomes[0].outputs[0]) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.getinfo(self.source.name).file_size, self.source.stat().st_size)

    def test_live_cancel_wakes_paused_worker_and_removes_partial_archive(self):
        self.start(pause_after_first_chunk=True)
        self.wait_until(lambda: any(event.phase == "paused" for event in self.updates))
        self.panel.cancel_button.click()
        self.wait_until(lambda: bool(self.outcomes))
        self.assertIsInstance(self.outcomes[0], OperationCancelled)
        self.assertTrue(self.panel.terminal)
        self.assertIn("Canceled", self.panel.title_label.text())
        self.assertFalse(any(event.phase == "completed" for event in self.updates))
        self.assertEqual(set(self.folder.iterdir()), {self.source})


if __name__ == "__main__":
    unittest.main()
