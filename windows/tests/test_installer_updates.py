"""Compile tiny real installers; extraction/update tests never register an app."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"


@unittest.skipUnless(sys.platform == "win32" and COMPILER.is_file(), "Windows .NET Framework C# compiler required")
class InstallerUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="FormatWheel isolated installer ")
        self.area = Path(self.temporary.name)
        self.install = self.area / "application"
        self.addCleanup(self.temporary.cleanup)

    def compile_installer(self, files, manifest=None):
        payload = self.area / "payload.zip"
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative, data in files.items():
                archive.writestr(relative, data)
            archive.writestr("installed-files.json", json.dumps(
                list(files) + ["installed-files.json"] if manifest is None else manifest))
        installer = self.area / "isolated-setup.exe"
        compiled = subprocess.run(
            [str(COMPILER), "/nologo", "/target:exe", "/out:" + str(installer),
             "/r:System.Windows.Forms.dll", "/r:System.IO.Compression.dll",
             "/r:System.IO.Compression.FileSystem.dll", "/r:System.Web.Extensions.dll",
             "/r:Microsoft.CSharp.dll", "/resource:" + str(payload) + ",payload.zip",
             str(ROOT / "windows/tools/Installer.cs")],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        return installer

    def extract_only(self, installer):
        # /extract-only returns before all registry, startup and Start menu code.
        return subprocess.run(
            [str(installer), "/silent", "/extract-only", "/dir=" + str(self.install)],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def prepare_previous(self, files, manifest):
        self.install.mkdir()
        for relative, data in files.items():
            target = self.install / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (self.install / "installed-files.json").write_text(json.dumps(manifest), encoding="utf-8")

    def snapshot(self):
        return {str(path.relative_to(self.install)): path.read_bytes()
                for path in self.install.rglob("*") if path.is_file()}

    def test_first_install_extracts_files_and_ownership_manifest(self):
        files = {"FormatWheel.exe": b"new app", "_internal/runtime.dll": b"runtime"}
        installer = self.compile_installer(files)
        result = self.extract_only(installer)
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative, data in files.items():
            self.assertEqual((self.install / relative).read_bytes(), data)
        manifest = json.loads((self.install / "installed-files.json").read_text())
        self.assertEqual(set(manifest), set(files) | {"installed-files.json"})

    def test_legacy_duplicate_manifest_upgrades_and_removes_only_obsolete_owned_files(self):
        previous = {"FormatWheel.exe": b"old app", "_internal/icuuc.dll": b"obsolete DLL",
                    "_internal/retained.dll": b"old retained"}
        self.prepare_previous(previous, list(previous) + ["installed-files.json", "installed-files.json"])
        user_file = self.install / "_internal/user-added.txt"
        user_file.write_bytes(b"keep user file")
        files = {"FormatWheel.exe": b"new app", "_internal/retained.dll": b"new retained",
                 "_internal/new.dll": b"new DLL"}
        result = self.extract_only(self.compile_installer(files))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.install / "_internal/icuuc.dll").exists())
        self.assertEqual(user_file.read_bytes(), b"keep user file")
        for relative, data in files.items():
            self.assertEqual((self.install / relative).read_bytes(), data)
        manifest = json.loads((self.install / "installed-files.json").read_text())
        self.assertEqual(manifest.count("installed-files.json"), 1)

    def test_new_payload_duplicate_manifest_is_rejected_before_any_replacement(self):
        previous = {"FormatWheel.exe": b"old app"}
        self.prepare_previous(previous, list(previous) + ["installed-files.json"])
        before = self.snapshot()
        files = {"FormatWheel.exe": b"must not replace", "new.dll": b"must not create"}
        result = self.extract_only(self.compile_installer(
            files, list(files) + ["installed-files.json", "installed-files.json"]))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.snapshot(), before)

    def test_traversal_is_rejected_in_new_and_legacy_manifests_before_writes(self):
        previous = {"FormatWheel.exe": b"old app"}
        self.prepare_previous(previous, list(previous) + ["installed-files.json"])
        outside = self.area / "outside.txt"
        outside.write_bytes(b"outside preserved")
        before = self.snapshot()
        files = {"FormatWheel.exe": b"must not replace"}
        result = self.extract_only(self.compile_installer(
            files, list(files) + ["installed-files.json", "../outside.txt"]))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.snapshot(), before)
        (self.install / "installed-files.json").write_text(json.dumps(
            ["FormatWheel.exe", "../outside.txt", "installed-files.json", "installed-files.json"]), encoding="utf-8")
        before = self.snapshot()
        result = self.extract_only(self.compile_installer(files))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(outside.read_bytes(), b"outside preserved")


if __name__ == "__main__":
    unittest.main()
