"""Build replaceable-library portable apps, a per-user setup EXE and matching source."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/windows"
DIST = ROOT / "dist/windows"
BUILD.mkdir(parents=True, exist_ok=True)
DIST.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--reuse-app", action="store_true", help="Repackage an already compiled app after data-only fixes")
arguments = parser.parse_args()

spec = BUILD / "FormatWheel.spec"
spec.write_text('''from PyInstaller.utils.hooks import collect_all, collect_submodules
datas = [(str(ROOT / 'windows/formatwheel/catalog_data.json'), 'formatwheel')]
binaries, hiddenimports = [], []
for module in ('pillow_heif', 'pymupdf', 'rembg', 'onnxruntime'):
    d, b, h = collect_all(module)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules('win32com')
a = Analysis([str(ROOT / 'windows/launcher.py')], pathex=[str(ROOT / 'windows')],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['tkinter', 'matplotlib', 'IPython', 'pytest', 'torch', 'tensorflow'])
# Qt uses Windows' system ICU API. Third-party ICU DLLs found on a builder's
# PATH can have incompatible suffixed exports and must not shadow Windows ICU.
a.binaries = [entry for entry in a.binaries if __import__('pathlib').Path(entry[0]).name.lower() not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FormatWheel', console=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FormatWheel-cli', console=True)
coll = COLLECT(gui, cli, a.binaries, a.datas, name='FormatWheel')
'''.replace("datas =", f"ROOT = __import__('pathlib').Path({str(ROOT)!r})\ndatas =", 1), encoding="utf-8")
if not arguments.reuse_app:
    build_environment = dict(os.environ)
    build_environment["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), str(Path(sys.base_prefix)), str(Path(os.environ["WINDIR"]) / "System32"), os.environ["WINDIR"]])
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(DIST), "--workpath", str(BUILD), str(spec)], env=build_environment, check=True)
app = DIST / "FormatWheel"
if not (app / "FormatWheel.exe").is_file():
    raise RuntimeError("Build the application before using --reuse-app")
for accidental_system_library in ("icuuc.dll", "icudt78.dll"):
    (app / "_internal" / accidental_system_library).unlink(missing_ok=True)
# pymatting queries its distribution version during import. Its code is detected
# by PyInstaller, but importlib.metadata also requires this separate metadata.
distribution = importlib.metadata.distribution("pymatting")
metadata = next(Path(distribution.locate_file(file)).parent for file in distribution.files
                if file.name == "METADATA" and file.parent.name.endswith(".dist-info"))
shutil.copytree(metadata, app / "_internal" / metadata.name, dirs_exist_ok=True)
for source, target in ((ROOT / "LICENSE", "LICENSE-MIT.txt"), (ROOT / "windows/LICENSE-AGPL-3.0.txt", "LICENSE-AGPL-3.0.txt"),
                       (ROOT / "windows/THIRD-PARTY-NOTICES.md", "THIRD-PARTY-NOTICES.md"), (ROOT / "windows/README.md", "WINDOWS-README.md"),
                       (ROOT / "windows/Install-Dependencies.ps1", "Install-Dependencies.ps1"), (ROOT / "windows/uninstall.ps1", "uninstall.ps1")):
    shutil.copy2(source, app / target)
licenses = app / "licenses"
for distribution in importlib.metadata.distributions():
    name = distribution.metadata.get("Name", "unknown")
    for file in distribution.files or []:
        if any(part.lower().startswith(("license", "copying", "notice")) for part in file.parts):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                target = licenses / name / str(file).replace("/", "_").replace("\\", "_")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
# Bundle an already prepared model, never download during conversion.
model = ROOT / "windows/.tools/models/u2netp.onnx"
if model.exists():
    (app / "models").mkdir(exist_ok=True)
    shutil.copy2(model, app / "models/u2netp.onnx")
manifest = sorted({p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file()} | {"installed-files.json"})
(app / "installed-files.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
portable = DIST / "FormatWheel-Windows-x64.zip"
with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
    for path in app.rglob("*"):
        if path.is_file():
            archive.write(path, path.relative_to(app).as_posix())
compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
setup = DIST / "FormatWheel-Windows-x64-Setup.exe"
subprocess.run([str(compiler), "/nologo", "/target:winexe", "/optimize+", f"/out:{setup}", "/r:System.Windows.Forms.dll", "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll", "/r:System.Web.Extensions.dll", "/r:Microsoft.CSharp.dll", f"/resource:{portable},payload.zip", str(ROOT / "windows/tools/Installer.cs")], check=True)
source_zip = DIST / "FormatWheel-Windows-Source.zip"
tracked = subprocess.check_output(["git", "ls-files", "-z", "--cached"], cwd=ROOT).decode().split("\0")
with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
    for name in tracked:
        path = ROOT / name
        if name and path.is_file() and not name.startswith(("docs/media/", ".git/")):
            archive.write(path, name)
print(f"Created {setup}\nCreated {portable}\nCreated {source_zip}")
