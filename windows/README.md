# FormatWheel for Windows

Windows 10/11, 64-bit. This port implements the same **73 action IDs**, wheel pages and conversion/tool choices as the original macOS application. It adds a Windows tray application, a portable build and a per-user installer. The original Swift application remains in `Sources/`.

## Install

Use `FormatWheel-Windows-x64-Setup.exe` from a Windows build of this fork. It installs for the current account in `%LOCALAPPDATA%\Programs\FormatWheel`, adds a Start menu shortcut and registers **FormatWheel for Windows** in Windows **Settings → Apps**. Installing the application itself does not require administrator access.

Open **FormatWheel** from the Start menu. Its tray menu provides file/folder selection, a demo, recent outputs and settings. Quit the tray application before updating or uninstalling it. To uninstall, use Settings → Apps; separately installed conversion backends and user preferences/models remain available.

For a portable installation, extract **all** files from `FormatWheel-Windows-x64.zip` into one folder, then run `FormatWheel.exe`. Keep `_internal`, both executables, notices and the other adjacent files together. Python is included in packaged builds; you do not need to install Python to run them.

## Enable every conversion backend

The main package contains its Python libraries. Some actions also need external tools and a local foreground-removal model. A missing dependency leaves the action visible with an explanation.

From the installed/portable folder, run PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-Dependencies.ps1 -WithCutout
.\FormatWheel-cli.exe --doctor
```

From a source checkout, the setup script is `windows\Install-Dependencies.ps1`. Setup uses `winget` and downloads the language data/model. Third-party installers can request administrator access. Restart FormatWheel after setup so it picks up installed tools.

| Dependency | Enables |
| --- | --- |
| FFmpeg **and ffprobe** | All video/audio conversions and tools, including HEVC, WebM, GIF, extraction, speeds and audio normalization |
| LibreOffice | Rich/legacy document import and export, including DOC, RTF and ODT, and layout-preserving Office-to-PDF conversion |
| Tesseract OCR + `eng`, `chi_sim`, `chi_tra` data | English, Simplified Chinese and Traditional Chinese OCR for images/PDFs |
| Local `u2netp.onnx` model with rembg/ONNX Runtime | Image foreground cutout |

The script places OCR data in `%LOCALAPPDATA%\FormatWheel\tessdata` and the model in `%LOCALAPPDATA%\FormatWheel\models`. Builds also include the verified small cutout model. For model-only setup, use `Install-Dependencies.ps1 -ModelsOnly`. These downloads happen during preparation; conversions process files locally. FormatWheel does not upload source files to a conversion service.

Manual tool installations are supported through `PATH`, common Windows installation folders, or `FORMATWHEEL_FFMPEG`, `FORMATWHEEL_FFPROBE`, `FORMATWHEEL_SOFFICE` and `FORMATWHEEL_TESSERACT` environment variables containing executable paths. `U2NET_HOME` can point to an existing local model directory. Run `--doctor` to inspect readiness; unavailable backends produce a nonzero diagnostic exit status.

## Use the wheel

1. Drag files in Explorer, tap **Shift** while holding the left mouse button, move toward a slot and release.
2. Tap Shift again, or use **Tab / Q / E / scroll**, to switch between conversion and tools.
3. Return to the center before releasing to cancel. **Esc** or right-click also closes the wheel.

The tray menu's **Choose files…** / **Choose folder…** opens the wheel for direct clicking. **Enter / Space** executes the highlighted option. A desktop drop target also accepts files.

Outputs are written beside the source, with unique names to avoid overwriting existing files. An unwritable source folder falls back to Downloads or the temporary folder. Source files remain unchanged. Image-to-PDF and PDF merging keep selection order; generic ZIP/path/name actions use the whole selection. Other mixed-type batches follow the dominant file kind and indicate skipped files. OCR saves UTF-8 text and copies it to the clipboard.

The tray menu includes recent outputs, format/weapon icons, four character colors, three wheel sizes, sound, background blur, completion banners and launch-at-login. Settings are in `%APPDATA%\FormatWheel\settings.json`; the rolling log is `%LOCALAPPDATA%\FormatWheel\FormatWheel.log`.

## Command line

Use `FormatWheel-cli.exe` for visible console output:

```powershell
.\FormatWheel-cli.exe --ids
.\FormatWheel-cli.exe --list "C:\Files\photo.jpg"
.\FormatWheel-cli.exe --run img.to.png "C:\Files\photo.heic"
.\FormatWheel-cli.exe --run pdf.merge "C:\Files\first.pdf" "C:\Files\second.pdf"
.\FormatWheel-cli.exe --scan "C:\Files\photo.jpg"
.\FormatWheel-cli.exe --doctor
.\FormatWheel-cli.exe --snapshot wheel.png --files "C:\Files\photo.jpg" --page 1 --hover 6
.\FormatWheel-cli.exe --weapons weapons.png
.\FormatWheel-cli.exe --glyphs glyphs.png
.\FormatWheel-cli.exe --sounds .\sounds
```

`--crew online|michael|franklin|trevor` and `--size small|medium|large` select appearance. `--preview` opens a demo. To open the wheel for a file directly, pass its path to `FormatWheel.exe`.

## Build and test

Use **Python 3.11 x64**, Git and Windows PowerShell. From the repository root:

```powershell
py -3.11 -m venv windows\.venv
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-Dependencies.ps1 -WithCutout
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\build.ps1
```

`build.ps1` installs the pinned requirements, runs the tests and packages with PyInstaller. Its `-SkipInstall` and `-SkipTests` switches are available for repeat development builds. Packaging uses Windows' .NET Framework C# compiler for the setup executable.

Build outputs are in `dist\windows\`:

| File/folder | Purpose |
| --- | --- |
| `FormatWheel\` | Runnable application with shared libraries and notices |
| `FormatWheel-Windows-x64.zip` | Portable package |
| `FormatWheel-Windows-x64-Setup.exe` | Current-user installer |
| `FormatWheel-Windows-Source.zip` | Matching project sources and build scripts |

Run the source application or tests after dependency installation:

```powershell
.\windows\.venv\Scripts\python.exe .\windows\launcher.py --doctor
.\windows\.venv\Scripts\python.exe .\windows\launcher.py
.\windows\.venv\Scripts\python.exe -m pytest windows\tests -q
```

`windows\tools\sync_catalog.py` refreshes Windows labels and trait tables after an upstream `Sources\Catalog.swift` update. The test suite compares all 73 IDs with that Swift catalog. Generated media fixtures exercise all 27 video/audio operations, including payload-preserving mute/privacy stripping, format codecs, speed, sample-rate and duration limits, compression and immutable inputs. Other tests cover image, PDF, document, privacy and output handling. Tests requiring optional tools may skip when their dependencies are absent.

## Compatibility and verification limits

Action/workflow parity does not mean byte-identical results. Apple Vision OCR/cutout is replaced by Tesseract and U²-Net; fonts, PDF/document rendering, image encoders and hardware media codecs differ between systems. OCR recognition, foreground masks, document layout and encoded size/quality can therefore differ. Mac-specific input types and unusual codecs need representative-file testing. Privacy tools remove the metadata they inspect; visible personal information inside pixels, text or document content remains.

The automated suite verifies conversion behavior with generated fixtures. Real Explorer dragging, shell/OLE integration, multiple displays, DPI settings and install/update/uninstall flows still require interactive Windows testing. Do not treat the action count or successful tests as proof that every macOS file and interaction produces the exact same result.

## Licensing

The upstream Swift project retains its MIT license. The combined Windows package includes PyMuPDF/MuPDF and is distributed under **GNU AGPLv3** terms. It includes the AGPL text, upstream MIT notice, third-party notices and a matching project source archive. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) for component licenses and source links.
