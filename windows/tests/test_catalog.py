"""Check the Windows catalog against the upstream action and selection contract."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formatwheel.catalog import all_ids, canonical_ext, context, file_kind


class CatalogParityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="FormatWheel catalog ")
        self.folder = Path(self.temporary.name)
        self.available = patch("formatwheel.engine.action_availability", return_value=(True, None))
        self.available.start()
        self.addCleanup(self.available.stop)
        self.addCleanup(self.temporary.cleanup)

    def source(self, name):
        path = self.folder / name
        path.touch()
        return path

    def options(self, files):
        return {option.id: option for page in context(files).pages for option in page.slots if option}

    def test_action_ids_exactly_match_the_upstream_catalog(self):
        swift_path = Path(__file__).resolve().parents[2] / "Sources" / "Catalog.swift"
        if not swift_path.exists():
            self.skipTest("The upstream Swift source is not included in this installed distribution")
        swift = swift_path.read_text(encoding="utf-8")
        original = set(re.findall(
            r'\b(?:format|WheelOption|o|strip)\((?:id:\s*)?"((?:img|pdf|vid|aud|doc|gen)\.[^"]+)"',
            swift,
        ))
        self.assertEqual(len(original), 73)
        self.assertEqual(len(all_ids()), 73)
        self.assertEqual(set(all_ids()), original)

    def test_wheel_pages_keep_eight_directional_positions_including_empty_slots(self):
        for name in ("photo.png", "book.pdf", "movie.mp4", "sound.wav", "notes.txt", "archive.7z"):
            with self.subTest(name=name):
                wheel = context([self.source(name)])
                self.assertEqual(len(wheel.pages), 1 if name.endswith(".7z") else 2)
                self.assertTrue(all(len(page.slots) == 8 for page in wheel.pages))
        audio = context([self.source("audio.mp3")]).pages[1].slots
        self.assertEqual([slot.id if slot else None for slot in audio],
                         ["aud.compress", "aud.mono", "aud.loud", "aud.fast", None, None, "gen.zip", "gen.path"])
        documents = context([self.source("document.docx")]).pages[1].slots
        self.assertEqual([slot.id if slot else None for slot in documents],
                         ["doc.count", None, "doc.copy", None, "doc.strip", None, "gen.zip", "gen.path"])

    def test_current_format_aliases_disable_the_existing_format(self):
        for extension, action in (("jpeg", "img.to.jpg"), ("jpe", "img.to.jpg"),
                                  ("tif", "img.to.tiff"), ("heif", "img.to.heic"),
                                  ("markdown", "doc.to.md"), ("htm", "doc.to.html"),
                                  ("aif", "aud.to.aiff"), ("aifc", "aud.to.aiff"),
                                  ("oga", "aud.to.opus"), ("ogg", "aud.to.opus"),
                                  ("m4v", "vid.to.mp4"), ("aac", "aud.to.m4a")):
            with self.subTest(extension=extension):
                option = self.options([self.source("example." + extension)])[action]
                self.assertFalse(option.enabled)
                self.assertEqual(option.ammo, "当前")

    def test_mixed_images_keep_conversion_to_each_format_available(self):
        options = self.options([self.source("a.jpg"), self.source("b.png")])
        self.assertTrue(options["img.to.jpg"].enabled)
        self.assertTrue(options["img.to.png"].enabled)
        self.assertEqual(options["img.to.pdf"].title, "合并成 PDF")
        self.assertIn("2", options["img.to.pdf"].detail)

    def test_majority_kind_and_skipped_count_follow_the_selection(self):
        wheel = context([self.source("note.txt"), self.source("a.jpg"), self.source("b.png")])
        self.assertEqual(wheel.kind, "image")
        self.assertIn("1", wheel.summary)
        self.assertIn("跳过", wheel.summary)
        self.assertEqual(wheel.headline, "3 个文件")

    def test_merge_requires_multiple_pdfs_and_updates_count(self):
        first, second = self.source("a.pdf"), self.source("b.pdf")
        self.assertFalse(self.options([first])["pdf.merge"].enabled)
        merged = self.options([first, second])["pdf.merge"]
        self.assertTrue(merged.enabled)
        self.assertIn("2", merged.detail)
        self.assertNotIn(r"\(", merged.detail)

    def test_docx_privacy_action_requires_a_pure_docx_selection(self):
        word, text = self.source("a.docx"), self.source("b.rtf")
        self.assertTrue(self.options([word])["doc.strip"].enabled)
        self.assertFalse(self.options([word, text])["doc.strip"].enabled)
        self.assertFalse(self.options([text])["doc.strip"].enabled)

    def test_directories_use_generic_actions_and_disable_sha(self):
        directory = self.folder / "folder.pdf"
        directory.mkdir()
        self.assertEqual(file_kind(directory), "other")
        self.assertFalse(self.options([directory])["gen.sha"].enabled)
        self.assertTrue(self.options([directory])["gen.zip"].enabled)
        rich_document = self.folder / "bundle.rtfd"
        rich_document.mkdir()
        self.assertEqual(file_kind(rich_document), "document")

    def test_tool_stats_have_the_same_upstream_deltas(self):
        for name, action, expected in (
            ("a.png", "img.compress", [.9, .7, 1, 1]),
            ("a.png", "img.half", [.7, .65, 1, 1]),
            ("a.jpg", "img.cutout", [.74, .78, 1, 1]),
            ("a.pdf", "pdf.compress", [.92, .15, .9, .95]),
            ("a.mp4", "vid.compress", [.748, 1, 1]),
            ("a.mp4", "vid.720p", [.6, .95, 1]),
            ("a.mp3", "aud.compress", [.56, .95, 1]),
        ):
            with self.subTest(action=action):
                actual = self.options([self.source(name)])[action].stats
                self.assertEqual(len(actual), len(expected))
                for actual_value, expected_value in zip(actual, expected):
                    self.assertAlmostEqual(actual_value, expected_value)

    def test_missing_dependency_disables_slot_with_explanation(self):
        self.available.stop()
        with patch("formatwheel.engine.action_availability", return_value=(False, "Install FFmpeg")):
            option = self.options([self.source("a.mov")])["vid.to.mp4"]
        self.assertFalse(option.enabled)
        self.assertEqual(option.note, "Install FFmpeg")
        self.assertEqual(option.ammo, "未装备")

    def test_canonical_extensions_are_case_insensitive(self):
        self.assertEqual(canonical_ext(".JPEG"), "jpg")
        self.assertEqual(canonical_ext("MARKDOWN"), "md")


if __name__ == "__main__":
    unittest.main()
