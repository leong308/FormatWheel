"""ZIP controls and displayed measurements must reflect worker state, never animation."""
from __future__ import annotations

from dataclasses import replace
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from formatwheel.engine import OperationControl, ProgressUpdate
from formatwheel.progress_ui import ZipProgressPanel, byte_text
from formatwheel.ui import ProgressMailbox, application


class ZipProgressPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = application()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="FormatWheel-ZIP-UI-")
        self.folder = Path(self.temporary.name)
        self.output = self.folder / "中文 archive.zip"
        self.revealed, self.opened = [], []
        self.panel = ZipProgressPanel(reveal=self.revealed.append, open_folder=self.opened.append)
        self.control = OperationControl()
        self.panel.begin(self.control, show=False)
        self.update = ProgressUpdate(fraction=.25, phase="compressing", processed_bytes=1024, total_bytes=4096,
                                     files_completed=1, files_total=4, current_file="资料/照片.png",
                                     output_path=self.output, archive_bytes=618, elapsed=28.4, speed_bps=512,
                                     eta_seconds=6)

    def tearDown(self):
        self.panel.timer.stop()
        self.panel.hide()
        self.panel.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def test_scanning_has_indeterminate_activity_and_no_invented_percent(self):
        update = replace(self.update, phase="scanning", fraction=None, speed_bps=None, eta_seconds=None)
        self.panel.apply_update(update)
        self.assertEqual(self.panel.percent_label.text(), "")
        self.assertEqual((self.panel.meter.minimum(), self.panel.meter.maximum()), (0, 0))
        for phase in (.1, .5, 1.5):
            self.panel.meter.animate(phase)
        self.assertIsNone(self.panel.meter.fraction)
        self.assertIn("Scanning", self.panel.status_label.text())
        self.assertIn("0:28", self.panel.elapsed_value.text())

    def test_nearly_complete_bytes_do_not_round_to_100_before_footer_closed(self):
        self.panel.apply_update(replace(self.update, fraction=math.nextafter(1., 0), processed_bytes=4096))
        self.assertEqual(self.panel.percent_label.text(), "99.9%")
        self.assertLess(self.panel.meter.value(), self.panel.meter.maximum())
        self.panel.apply_update(replace(self.update, phase="finalizing", fraction=math.nextafter(1., 0)))
        self.assertEqual(self.panel.percent_label.text(), "")
        self.assertEqual(self.panel.meter.maximum(), 0)
        self.output.write_bytes(b"a finished test archive")
        self.panel.finish([self.output])
        self.assertEqual(self.panel.percent_label.text(), "100%")
        self.assertEqual(self.panel.meter.value(), 1000)
        self.assertEqual(self.panel.archive_value.text(), byte_text(self.output.stat().st_size))

    def test_pause_resume_and_late_pause_ack_cannot_leave_pausing_state(self):
        self.panel.apply_update(self.update)
        self.panel.pause_button.click()
        self.assertTrue(self.control.is_paused)
        self.panel.apply_update(replace(self.update, phase="paused", speed_bps=None, eta_seconds=None))
        self.assertIn("Resume", self.panel.pause_button.text())
        self.assertIn("Paused", self.panel.speed_value.text())
        self.panel.pause_button.click()
        self.assertFalse(self.control.is_paused)
        # A queued pause acknowledgement can arrive after the user resumed.
        self.panel.apply_update(replace(self.update, phase="paused", speed_bps=None, eta_seconds=None))
        self.assertFalse(self.panel.pause_requested)
        self.assertIn("Pause", self.panel.pause_button.text())
        self.panel.apply_update(replace(self.update, fraction=.4))
        self.assertFalse(self.panel.pause_requested)
        self.assertNotIn("Pausing", self.panel.status_label.text())
        self.assertIn("Compressing", self.panel.status_label.text())

    def test_elapsed_advances_while_paused_without_changing_bytes_or_percent(self):
        self.control.pause()
        self.panel.apply_update(replace(self.update, phase="paused", speed_bps=None, eta_seconds=None))
        self.panel.received_at = 100.
        with patch("formatwheel.progress_ui.time.monotonic", return_value=112.):
            self.panel.animate()
        self.assertEqual(self.panel.elapsed_value.text(), "0:40")
        self.assertEqual(self.panel.meter.fraction, .25)
        self.assertEqual(self.panel.percent_label.text(), "25.0%")
        self.assertIn("Paused", self.panel.eta_value.text())

    def test_cancel_waits_for_worker_ack_and_disables_controls(self):
        self.panel.apply_update(self.update)
        self.panel.cancel_button.click()
        self.assertTrue(self.control.is_cancelled)
        self.assertTrue(self.panel.active)
        self.assertFalse(self.panel.pause_button.isEnabled())
        self.assertFalse(self.panel.cancel_button.isEnabled())
        self.assertIn("Canceling", self.panel.status_label.text())
        self.panel.cancelled()
        self.assertFalse(self.panel.active)
        self.assertTrue(self.panel.cancel_button.isEnabled())
        self.assertIn("Canceled", self.panel.title_label.text())
        self.assertNotIn("100", self.panel.percent_label.text())

    def test_space_activates_focused_native_pause_resume_and_cancel_buttons(self):
        self.panel.apply_update(self.update)
        self.panel.show()
        self.panel.pause_button.setFocus()
        QTest.keyClick(self.panel.pause_button, Qt.Key.Key_Space)
        self.assertTrue(self.control.is_paused)
        QTest.keyClick(self.panel.pause_button, Qt.Key.Key_Space)
        self.assertFalse(self.control.is_paused)
        self.panel.cancel_button.setFocus()
        QTest.keyClick(self.panel.cancel_button, Qt.Key.Key_Space)
        self.assertTrue(self.control.is_cancelled)
        self.assertFalse(self.control.is_paused)

    def test_compact_panel_keeps_controls_within_340_pixel_width(self):
        self.panel.apply_update(self.update)
        self.panel.set_expanded(False)
        self.panel.resize(340, 390)
        self.panel.ensurePolished()
        self.panel.layout().activate()
        self.app.processEvents()
        self.panel.grab()  # Forces the same layout pass used to paint the window.
        self.assertEqual(self.panel.width(), 340)
        for button in (self.panel.destination_button, self.panel.pause_button, self.panel.cancel_button):
            position = button.mapTo(self.panel, button.rect().bottomRight())
            self.assertLess(position.x(), self.panel.width())
            self.assertLess(position.y(), self.panel.height())

    def test_short_high_dpi_panel_scrolls_measurements_but_keeps_native_controls(self):
        self.panel.apply_update(self.update)
        self.panel.resize(320, 260)
        self.panel.ensurePolished()
        self.panel.layout().activate()
        self.app.processEvents()
        self.panel.grab()
        for button in (self.panel.destination_button, self.panel.pause_button, self.panel.cancel_button):
            position = button.mapTo(self.panel, button.rect().bottomRight())
            self.assertGreaterEqual(button.height(), 36)
            self.assertLess(position.x(), self.panel.width())
            self.assertLess(position.y(), self.panel.height())
        self.assertGreater(self.panel.body_scroll.verticalScrollBar().maximum(), 0)

    def test_hide_and_close_leave_job_running_and_can_restore(self):
        self.panel.show()
        self.panel.hide_button.click()
        self.assertFalse(self.panel.isVisible())
        self.assertTrue(self.panel.active)
        self.assertFalse(self.control.is_cancelled)
        self.panel.restore()
        self.panel.close()
        self.assertFalse(self.panel.isVisible())
        self.assertTrue(self.panel.active)
        self.assertFalse(self.control.is_cancelled)

    def test_destination_only_opens_folder_until_completed(self):
        self.output.write_bytes(b"partial")
        self.panel.apply_update(self.update)
        self.panel.destination_button.click()
        self.assertEqual(self.opened, [self.folder])
        self.assertEqual(self.revealed, [])
        self.panel.finish([self.output])
        self.panel.destination_button.click()
        self.assertEqual(self.revealed, [self.output])

    def test_long_filename_remains_accessible_and_measurements_have_exact_tooltips(self):
        filename = "<资料> & " + "a"*400 + ".png"
        self.panel.apply_update(replace(self.update, current_file=filename))
        self.panel.resize(340, 440)
        self.app.processEvents()
        self.assertEqual(self.panel.current_label.toolTip(), filename)
        self.assertEqual(self.panel.current_label.accessibleDescription(), filename)
        self.assertIn("1,024 / 4,096", self.panel.bytes_label.toolTip())
        self.assertIn("618 bytes", self.panel.archive_value.toolTip())
        self.assertIn("512", self.panel.speed_value.toolTip())
        self.assertLessEqual(self.panel.current_label.fontMetrics().horizontalAdvance(self.panel.current_label.text()), self.panel.current_label.width()+1)

    def test_expand_collapse_keeps_controls_and_measurements(self):
        self.panel.apply_update(self.update)
        self.panel.details_button.click()
        self.assertFalse(self.panel._expanded)
        self.assertTrue(self.panel.details_scroll.isHidden())
        self.assertEqual(self.panel.meter.fraction, .25)
        self.panel.details_button.click()
        self.assertTrue(self.panel._expanded)
        self.assertFalse(self.panel.details_scroll.isHidden())

    def test_worker_burst_coalesces_to_latest_update_on_gui_thread(self):
        delivered = []
        main = threading.get_ident()
        mailbox = ProgressMailbox(lambda value: delivered.append((value, threading.get_ident())))
        thread = threading.Thread(target=lambda: [mailbox.push(index) for index in range(10000)])
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(delivered, [])
        self.app.processEvents()
        self.assertEqual(delivered, [(9999, main)])


if __name__ == "__main__":
    unittest.main()
