"""Streamed ZIP progress and controls operate on source bytes and preserve inputs."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formatwheel.engine import Engine, FormatWheelError, OperationCancelled, OperationControl, ProgressUpdate


class ZipProgressTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="FormatWheel ZIP progress ")
        self.folder = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def source(self, name="large source.bin", size=8 << 20):
        path = self.folder / name
        with path.open("wb") as output:
            block = b"FormatWheel local conversion fixture\n" * 32768
            remaining = size
            while remaining:
                piece = block[:min(len(block), remaining)]
                output.write(piece)
                remaining -= len(piece)
        return path

    def rich(self, updates):
        return [item for item in updates if isinstance(item, ProgressUpdate)]

    def test_source_byte_totals_percent_and_completed_archive_are_consistent(self):
        source = self.source(size=64 << 20)
        original = hashlib.sha256(source.read_bytes()).hexdigest()
        updates, closed_archive = [], []

        def progress(update):
            updates.append(update)
            if isinstance(update, ProgressUpdate) and update.phase == "completed":
                with zipfile.ZipFile(update.output_path) as archive:
                    closed_archive.append(archive.testzip())

        result = Engine.run("gen.zip", [source], progress=progress)
        events = self.rich(updates)
        self.assertTrue(events)
        self.assertTrue(any(event.phase == "scanning" and event.fraction is None for event in events))
        active = [event for event in events if event.phase == "compressing"]
        self.assertTrue(any(0 < event.processed_bytes < event.total_bytes for event in active))
        for event in active:
            self.assertEqual(event.total_bytes, source.stat().st_size)
            self.assertEqual(event.files_total, 1)
            self.assertLessEqual(event.processed_bytes, event.total_bytes)
            self.assertGreaterEqual(event.fraction, 0)
            self.assertLess(event.fraction, 1)
            if event.total_bytes:
                self.assertAlmostEqual(event.fraction, event.processed_bytes / event.total_bytes, delta=.001)
            if event.speed_bps is not None:
                self.assertGreaterEqual(event.speed_bps, 0)
            if event.eta_seconds is not None:
                self.assertGreaterEqual(event.eta_seconds, 0)
        known = [event.fraction for event in events if event.fraction is not None]
        self.assertEqual(known, sorted(known))
        self.assertEqual(events[-1].phase, "completed")
        self.assertEqual(events[-1].fraction, 1)
        self.assertEqual(events[-1].processed_bytes, source.stat().st_size)
        self.assertEqual(events[-1].files_completed, 1)
        self.assertEqual(closed_archive, [None])
        self.assertLess(result.outputs[0].stat().st_size, source.stat().st_size // 10)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)

    def test_empty_folders_and_zero_byte_files_finish_without_division_by_zero(self):
        selected = self.folder / "empty tree"
        (selected / "empty child").mkdir(parents=True)
        (selected / "zero.txt").touch()
        updates = []
        result = Engine.run("gen.zip", [selected], progress=updates.append)
        events = self.rich(updates)
        self.assertEqual(events[-1].total_bytes, 0)
        self.assertEqual(events[-1].processed_bytes, 0)
        self.assertEqual(events[-1].files_total, 1)
        self.assertEqual(events[-1].files_completed, 1)
        self.assertEqual(events[-1].fraction, 1)
        self.assertTrue(all(event.fraction in (None, 0, 1) for event in events))
        with zipfile.ZipFile(result.outputs[0]) as archive:
            self.assertTrue(any(name.endswith("empty child/") for name in archive.namelist()))
            self.assertTrue(any(name.endswith("zero.txt") for name in archive.namelist()))

    def test_cancellation_during_streaming_removes_only_partial_output(self):
        source = self.source()
        original = source.read_bytes()
        control, updates = OperationControl(), []

        def progress(event):
            updates.append(event)
            if isinstance(event, ProgressUpdate) and event.phase == "compressing" and event.processed_bytes:
                control.cancel()

        with self.assertRaises(OperationCancelled):
            Engine.run("gen.zip", [source], progress=progress, control=control)
        self.assertEqual(set(self.folder.iterdir()), {source})
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(any(event.fraction == 1 for event in self.rich(updates)))

    def test_cancel_at_finalizing_does_not_publish_success_or_leave_archive(self):
        source = self.source(size=8192)
        control, updates = OperationControl(), []

        def progress(event):
            updates.append(event)
            if isinstance(event, ProgressUpdate) and event.phase == "finalizing":
                control.cancel()

        with self.assertRaises(OperationCancelled):
            Engine.run("gen.zip", [source], progress=progress, control=control)
        self.assertEqual(set(self.folder.iterdir()), {source})
        self.assertFalse(any(event.phase == "completed" for event in self.rich(updates)))

    def test_pause_freezes_progress_and_cancel_wakes_paused_worker(self):
        source = self.source()
        control, paused, updates, failures = OperationControl(), threading.Event(), [], []
        requested = False

        def progress(event):
            nonlocal requested
            updates.append(event)
            if isinstance(event, ProgressUpdate):
                if event.phase == "compressing" and event.processed_bytes and not requested:
                    requested = True
                    control.pause()
                elif event.phase == "paused":
                    paused.set()

        def work():
            try:
                Engine.run("gen.zip", [source], progress=progress, control=control)
            except Exception as error:
                failures.append(error)

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        try:
            self.assertTrue(paused.wait(5), "The engine never acknowledged pause")
            self.assertTrue(control.is_paused)
            before = self.rich(updates)[-1].processed_bytes
            time.sleep(.12)
            self.assertEqual(self.rich(updates)[-1].processed_bytes, before)
            self.assertTrue(worker.is_alive())
            control.cancel()
            worker.join(5)
            self.assertFalse(worker.is_alive(), "Cancel did not wake the paused worker")
            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], OperationCancelled)
            self.assertEqual(set(self.folder.iterdir()), {source})
        finally:
            control.cancel()
            worker.join(5)

    def test_wall_elapsed_includes_pause_but_transfer_speed_and_eta_exclude_it(self):
        source = self.source(size=64 << 20)
        control, paused, finished = OperationControl(), threading.Event(), threading.Event()
        updates, failures, results, paused_at_update = [], [], [], []
        requested = False

        def progress(event):
            nonlocal requested
            updates.append(event)
            if isinstance(event, ProgressUpdate):
                paused_at_update.append((event, control.paused_seconds))
                if event.phase == "compressing" and event.processed_bytes and not requested:
                    requested = True
                    control.pause()
                elif event.phase == "paused":
                    paused.set()

        def work():
            try:
                results.append(Engine.run("gen.zip", [source], progress=progress, control=control))
            except Exception as error:
                failures.append(error)
            finally:
                finished.set()

        start = time.monotonic()
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        try:
            self.assertTrue(paused.wait(5))
            time.sleep(.25)
            control.resume()
            self.assertTrue(finished.wait(5), "Resuming did not finish the archive")
            worker.join(5)
            self.assertEqual(failures, [])
            final = self.rich(updates)[-1]
            self.assertEqual(final.phase, "completed")
            self.assertGreaterEqual(control.paused_seconds, .20)
            self.assertAlmostEqual(final.elapsed, time.monotonic() - start, delta=.15)
            self.assertGreaterEqual(final.elapsed, control.paused_seconds)
            compression_start = next(event.elapsed for event in self.rich(updates) if event.phase == "compressing")
            measured = [(event, pause) for event, pause in paused_at_update
                        if event.phase == "compressing" and event.speed_bps is not None and pause >= .20]
            self.assertTrue(measured, "No resumed transfer speed was reported")
            for event, pause in measured:
                active = event.elapsed - compression_start - pause
                self.assertGreater(active, 0)
                self.assertAlmostEqual(event.speed_bps, event.processed_bytes / active,
                                       delta=event.speed_bps * .02)
                if event.eta_seconds is not None:
                    self.assertAlmostEqual(event.eta_seconds,
                                           (event.total_bytes - event.processed_bytes) / event.speed_bps,
                                           delta=.02)
            with zipfile.ZipFile(results[0].outputs[0]) as archive:
                self.assertIsNone(archive.testzip())
        finally:
            control.cancel()
            worker.join(5)

    def test_file_growth_during_archive_is_reported_and_partial_output_removed(self):
        source = self.source()
        changed = False

        def progress(event):
            nonlocal changed
            if isinstance(event, ProgressUpdate) and event.phase == "compressing" and event.processed_bytes and not changed:
                changed = True
                with source.open("ab") as output:
                    output.write(b"a new tail")

        with self.assertRaisesRegex(FormatWheelError, "(?i)changed"):
            Engine.run("gen.zip", [source], progress=progress)
        self.assertTrue(changed)
        self.assertEqual(set(self.folder.iterdir()), {source})

    def test_source_shrink_and_same_size_edits_are_not_silently_archived(self):
        for kind in ("shrink", "same size edit"):
            with self.subTest(kind=kind):
                source = self.source(kind + ".bin")
                changed = False

                def progress(event):
                    nonlocal changed
                    if isinstance(event, ProgressUpdate) and event.phase == "compressing" and event.processed_bytes and not changed:
                        changed = True
                        previous = source.stat()
                        with source.open("r+b") as output:
                            if kind == "shrink":
                                output.truncate(1024)
                            else:
                                output.write(b"edited bytes")
                        os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns + 10_000_000))

                before = set(self.folder.iterdir())
                with self.assertRaisesRegex(FormatWheelError, "(?i)changed"):
                    Engine.run("gen.zip", [source], progress=progress)
                self.assertTrue(changed)
                self.assertEqual(set(self.folder.iterdir()), before)

    def test_zip64_file_headers_support_large_files_without_gigabyte_fixture(self):
        source = self.source(size=8192)
        with patch("zipfile.ZIP64_LIMIT", 1024):
            result = Engine.run("gen.zip", [source])
        with zipfile.ZipFile(result.outputs[0]) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read(source.name), source.read_bytes())
            self.assertEqual(archive.getinfo(source.name).file_size, 8192)

    def test_cancellation_during_scan_does_not_create_an_output(self):
        source = self.source(size=8192)
        control, updates = OperationControl(), []

        def progress(event):
            updates.append(event)
            if isinstance(event, ProgressUpdate) and event.phase == "scanning":
                control.cancel()

        with self.assertRaises(OperationCancelled):
            Engine.run("gen.zip", [source], progress=progress, control=control)
        self.assertEqual(set(self.folder.iterdir()), {source})
        self.assertTrue(all(event.phase != "completed" for event in self.rich(updates)))

    def test_archive_inside_another_selected_folder_cannot_include_itself(self):
        selected = self.folder / "parent"
        selected.mkdir()
        source = selected / "child.txt"
        source.write_text("kept", encoding="utf-8")
        updates = []
        result = Engine.run("gen.zip", [source, selected], progress=updates.append)
        output = result.outputs[0]
        with zipfile.ZipFile(output) as archive:
            self.assertTrue(all(Path(name).name != output.name for name in archive.namelist()))
            self.assertEqual(sum(info.file_size for info in archive.infolist()), 8)
        self.assertEqual(self.rich(updates)[-1].total_bytes, 8)
        self.assertEqual(source.read_text(encoding="utf-8"), "kept")

    def test_nested_directory_links_are_not_followed(self):
        external = self.folder / "outside selection"
        external.mkdir()
        (external / "private.txt").write_text("not selected", encoding="utf-8")
        selected = self.folder / "selected"
        selected.mkdir()
        (selected / "ordinary.txt").write_text("selected", encoding="utf-8")
        try:
            os.symlink(external, selected / "external link", target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Windows symlink creation is unavailable: {error}")
        result = Engine.run("gen.zip", [selected])
        with zipfile.ZipFile(result.outputs[0]) as archive:
            self.assertFalse(any("private.txt" in name or "external link" in name for name in archive.namelist()))


if __name__ == "__main__":
    unittest.main()
