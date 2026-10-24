"""Real codec integration checks, using generated fixtures and no downloaded media."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formatwheel.engine import Engine


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def run_tool(*args: str) -> str:
    completed = subprocess.run(
        args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace", timeout=120,
    )
    return completed.stdout.strip()


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and ffprobe are required for codec integration tests")
class MediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="FormatWheel media 文字 ")
        cls.folder = Path(cls.temporary.name)
        cls.video = cls.folder / "video with spaces 影片.mp4"
        cls.audio = cls.folder / "stereo sound 声音.wav"
        cls.ringtone = cls.folder / "long ringtone.m4a"
        cls.long_video = cls.folder / "long animation.mp4"
        cls.silent_video = cls.folder / "silent video.mp4"
        run_tool(
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=160x96:rate=12:duration=2.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2.5",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ac", "2", "-shortest",
            "-metadata", "location=+03.1390+101.6869/",
            "-metadata", "com.apple.quicktime.model=Test Camera",
            "-metadata", "com.apple.quicktime.creationdate=2024-01-02T03:04:05Z",
            "-movflags", "+use_metadata_tags", str(cls.video),
        )
        run_tool(
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2.5",
            "-ac", "2", "-c:a", "pcm_s16le", str(cls.audio),
        )
        run_tool(
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=16000:duration=43",
            "-c:a", "aac", "-b:a", "32k", str(cls.ringtone),
        )
        run_tool(
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=64x32:rate=2:duration=31",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(cls.long_video),
        )
        run_tool(
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(cls.video),
            "-map", "0:v:0", "-c", "copy", "-an", str(cls.silent_video),
        )
        cls.hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in
                      (cls.video, cls.audio, cls.ringtone, cls.long_video, cls.silent_video)}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.engine = Engine()

    def tearDown(self):
        for source, original_hash in self.hashes.items():
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash,
                             f"Source file changed: {source.name}")

    def probe(self, path):
        return json.loads(run_tool(
            FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
        ))

    def stream(self, path, kind):
        return next(item for item in self.probe(path)["streams"] if item["codec_type"] == kind)

    def duration(self, path):
        return float(self.probe(path)["format"]["duration"])

    def output(self, action, source):
        result = self.engine.run(action, [source])
        self.assertEqual(len(result.outputs), 1)
        path = Path(result.outputs[0])
        self.assertTrue(path.is_file(), f"No output for {action}")
        self.assertEqual(path.parent.resolve(), source.parent.resolve())
        self.assertNotEqual(path, source)
        return path

    def video_packets_hash(self, path):
        return run_tool(
            FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-map", "0:v:0", "-c", "copy", "-f", "hash", "-hash", "sha256", "-",
        )

    def test_mute_preserves_compressed_video_packets_and_removes_audio(self):
        output = self.output("vid.mute", self.video)
        self.assertEqual(self.video_packets_hash(output), self.video_packets_hash(self.video))
        self.assertFalse(any(item["codec_type"] == "audio" for item in self.probe(output)["streams"]))

    def test_strip_removes_capture_metadata_without_reencoding_video(self):
        original_tags = json.dumps(self.probe(self.video)).lower()
        self.assertIn("test camera", original_tags)
        output = self.output("vid.strip", self.video)
        self.assertEqual(self.video_packets_hash(output), self.video_packets_hash(self.video))
        tags = json.dumps(self.probe(output)).lower()
        self.assertNotIn("test camera", tags)
        self.assertNotIn("+03.1390+101.6869", tags)
        self.assertNotIn("2024-01-02", tags)
        self.assertTrue(any(item["codec_type"] == "audio" for item in self.probe(output)["streams"]))

    def test_cover_is_full_size_jpeg(self):
        output = self.output("vid.cover", self.video)
        stream = self.stream(output, "video")
        self.assertEqual(stream["codec_name"], "mjpeg")
        self.assertEqual((stream["width"], stream["height"]), (160, 96))

    def test_video_speed_changes_duration_and_keeps_audio(self):
        for action, factor in (("vid.fast", 0.5), ("vid.slow", 2.0)):
            with self.subTest(action=action):
                output = self.output(action, self.video)
                self.assertAlmostEqual(self.duration(output), self.duration(self.video) * factor, delta=0.3)
                self.assertEqual(self.stream(output, "audio")["codec_type"], "audio")

    def test_speed_also_accepts_video_without_an_audio_track(self):
        output = self.output("vid.fast", self.silent_video)
        self.assertAlmostEqual(self.duration(output), self.duration(self.silent_video) / 2, delta=0.3)
        self.assertFalse(any(item["codec_type"] == "audio" for item in self.probe(output)["streams"]))

    def test_gif_is_animated_and_capped_at_thirty_seconds(self):
        output = self.output("vid.to.gif", self.long_video)
        self.assertEqual(self.stream(output, "video")["codec_name"], "gif")
        self.assertAlmostEqual(self.duration(output), 30.0, delta=0.2)
        self.assertGreater(int(self.stream(output, "video").get("nb_frames", "2")), 1)

    def test_iphone_ringtone_is_aac_and_capped_at_forty_seconds(self):
        output = self.output("aud.to.m4r", self.ringtone)
        self.assertEqual(output.suffix, ".m4r")
        self.assertEqual(self.stream(output, "audio")["codec_name"], "aac")
        self.assertAlmostEqual(self.duration(output), 40.0, delta=0.2)

    def test_mono_preserves_wav_codec_and_sample_rate(self):
        output = self.output("aud.mono", self.audio)
        stream = self.stream(output, "audio")
        self.assertEqual(output.suffix, ".wav")
        self.assertEqual(stream["codec_name"], "pcm_s16le")
        self.assertEqual(stream["channels"], 1)
        self.assertEqual(int(stream["sample_rate"]), 48000)

    def test_loudness_does_not_leave_audio_upsampled(self):
        output = self.output("aud.loud", self.audio)
        stream = self.stream(output, "audio")
        self.assertEqual(stream["codec_name"], "pcm_s16le")
        self.assertEqual(int(stream["sample_rate"]), 48000)
        self.assertAlmostEqual(self.duration(output), self.duration(self.audio), delta=0.05)

    def test_audio_speed_is_one_and_a_half(self):
        output = self.output("aud.fast", self.audio)
        self.assertAlmostEqual(self.duration(output), self.duration(self.audio) / 1.5, delta=0.15)

    def test_apple_lossless_uses_alac_in_m4a(self):
        output = self.output("aud.to.alac", self.audio)
        self.assertEqual(output.suffix, ".m4a")
        self.assertEqual(self.stream(output, "audio")["codec_name"], "alac")

    def test_video_conversion_formats_have_the_requested_codec_and_audio(self):
        for action, extension, codec in (
            ("vid.to.mp4", ".mp4", "h264"),
            ("vid.to.mov", ".mov", "h264"),
            ("vid.to.hevc", ".mp4", "hevc"),
            ("vid.to.webm", ".webm", "vp9"),
        ):
            with self.subTest(action=action):
                output = self.output(action, self.video)
                self.assertEqual(output.suffix, extension)
                self.assertEqual(self.stream(output, "video")["codec_name"], codec)
                self.assertEqual(self.stream(output, "audio")["codec_type"], "audio")
                self.assertAlmostEqual(self.duration(output), self.duration(self.video), delta=0.25)

    def test_extracted_audio_has_no_video_track(self):
        for target, codec in (("mp3", "mp3"), ("m4a", "aac"), ("wav", "pcm_s16le")):
            with self.subTest(target=target):
                output = self.output("vid.to." + target, self.video)
                self.assertEqual(self.stream(output, "audio")["codec_name"], codec)
                self.assertFalse(any(item["codec_type"] == "video" for item in self.probe(output)["streams"]))

    def test_audio_conversion_formats_have_the_requested_codec(self):
        for target, codec in (("mp3", "mp3"), ("m4a", "aac"), ("wav", "pcm_s16le"),
                              ("flac", "flac"), ("aiff", "pcm_s16be"), ("opus", "opus")):
            with self.subTest(target=target):
                output = self.output("aud.to." + target, self.audio)
                self.assertEqual(output.suffix, "." + target)
                self.assertEqual(self.stream(output, "audio")["codec_name"], codec)
                self.assertAlmostEqual(self.duration(output), self.duration(self.audio), delta=0.15)

    def test_media_compression_produces_smaller_playable_outputs(self):
        for action, source in (("vid.compress", self.video), ("aud.compress", self.audio)):
            with self.subTest(action=action):
                output = self.output(action, source)
                self.assertLess(output.stat().st_size, source.stat().st_size)
                self.assertAlmostEqual(self.duration(output), self.duration(source), delta=0.2)

    def test_720p_does_not_upscale_a_smaller_video(self):
        output = self.output("vid.720p", self.video)
        video = self.stream(output, "video")
        self.assertEqual((video["width"], video["height"]), (160, 96))

    def test_repeated_action_does_not_overwrite_previous_output(self):
        first = self.output("vid.cover", self.video)
        first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
        second = self.output("vid.cover", self.video)
        self.assertNotEqual(first, second)
        self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(), first_hash)


if __name__ == "__main__":
    unittest.main()
