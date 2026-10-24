# FormatWheel for Windows

Windows 10/11, 64-bit. This port implements the same **73 action IDs**, wheel pages and conversion/tool choices as the original macOS application. It adds a Windows tray application, a portable build and a per-user installer. The original Swift application remains in `Sources/`.

## Setup on Windows: follow these five steps

Use this path to run the app. **Python, Git and a source-code build are not required.** You need Windows 10/11 x64 and an Internet connection for the initial downloads and extra conversion tools.

### 1. Get the Windows installer

If you already have `FormatWheel-Windows-x64-Setup.exe`, continue to step 2. Otherwise:

1. Sign in to GitHub and open this fork's [Windows build page](https://github.com/leong308/FormatWheel/actions/workflows/windows.yml).
2. Open the newest completed run with a green check for `codex/windows-support`.
3. Scroll to **Artifacts**, then click **FormatWheel-Windows-x64** to download the build ZIP.
4. In File Explorer, right-click that downloaded ZIP → **Extract All…** → **Extract**.
5. Open the extracted folder and find **FormatWheel-Windows-x64-Setup.exe**.

The build download contains these three files. Choose the installer for the steps below:

| File | What to do with it |
| --- | --- |
| `FormatWheel-Windows-x64-Setup.exe` | Run this to install the application. |
| `FormatWheel-Windows-x64.zip` | Alternative portable app; see the portable instructions below. |
| `FormatWheel-Windows-Source.zip` | Developer source code; it is not the application installer. |

GitHub's **Code → Download ZIP** also downloads source code, not the ready-to-run Windows app. Build artifacts can expire; use a newer successful Windows build if an old download is unavailable.

### 2. Install the app

1. Double-click **FormatWheel-Windows-x64-Setup.exe**.
2. In **FormatWheel Setup**, click **OK** to install for your Windows account.
3. Wait for the **Installed** message, then click **OK**.

The default installation folder is `%LOCALAPPDATA%\Programs\FormatWheel`. The installer adds a Start menu shortcut and an entry in **Settings → Apps**. Installing the app itself does not require administrator access. It does not automatically open the app; complete the extra-tool setup next.

### 3. Install the extra conversion tools

This adds FFmpeg for video/audio, LibreOffice for Office formats, and Tesseract plus English/Chinese OCR data. It also prepares a local background-removal model. Some wheel slots remain unavailable until their tools are installed.

1. If FormatWheel is already running, right-click its tray icon near the clock → **退出格式轮盘 / Quit**. The icon may be under the **^** hidden-icons arrow.
2. Open **Start**, search **Windows PowerShell**, and open it normally.
3. Copy and paste this entire block into PowerShell, then press **Enter**:

```powershell
Set-Location (Join-Path $env:LOCALAPPDATA 'Programs\FormatWheel')
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-Dependencies.ps1 -WithCutout
```

4. Follow any third-party installer prompts. Those installers may request administrator access. Wait until PowerShell prints **Dependencies prepared. Restart FormatWheel; conversions run locally without downloads.** If it reports an error, see troubleshooting below.
5. **Close PowerShell.** Open a new Windows PowerShell window so it can see tool locations added to `PATH`.

These commands assume the default install location. If you used the portable package, change to its extracted application folder instead. Running the dependency script from a source checkout does not install or build the FormatWheel application itself.

### 4. Check that the tools were found

In the **new** PowerShell window, paste:

```powershell
Set-Location (Join-Path $env:LOCALAPPDATA 'Programs\FormatWheel')
.\FormatWheel-cli.exe --doctor
$LASTEXITCODE
```

The diagnostic prints the action IDs and their readiness:

- `"ready": true` means the action's dependency check passed.
- `"ready": false` is followed by a `"note"` explaining what is missing.
- The last line is `0` when all dependency checks pass, or `2` when something is missing.

If an action is unavailable, follow its note, then close and reopen PowerShell before checking again. This diagnostic checks tool availability; it does not certify every input format, OCR language or conversion result.

### 5. Open the app and make one real conversion

1. Open **Start → FormatWheel**. The app lives in the system tray near the clock; a normal application window may not appear. Click **^** if its icon is hidden.
2. If a **Demo** wheel appears, press **Esc** to close it. The demo does not convert a file, even if it displays **MISSION PASSED**.
3. Right-click the tray icon → **选择文件打开轮盘… / Choose files…**.
4. Select an existing **PNG** picture, then click the **JPG** slot on the wheel. Use a copy of a picture for your first test if you prefer.
5. After **MISSION PASSED**, open the source picture's folder. A new JPG should be beside it; the PNG remains unchanged. If the source folder is not writable, use **Recent outputs** in the tray menu to reveal where the result was saved.

After that test, try the shortcut: drag a file in Explorer, keep the left mouse button held, tap **Shift**, move toward a slot and release. The current-format slot is disabled; for example, PNG is disabled when the selected file is already PNG.

## Portable setup instead of installing

1. Extract the downloaded build ZIP first, then right-click its inner **FormatWheel-Windows-x64.zip** → **Extract All…**.
2. Open the resulting application folder. It must contain **FormatWheel.exe**, **FormatWheel-cli.exe**, **Install-Dependencies.ps1** and **_internal**.
3. Keep the entire folder together. Do not run the EXE from inside a ZIP or copy the EXE alone.
4. Open PowerShell in this folder: click File Explorer's address bar, type `powershell`, then press **Enter**. Run the dependency command from step 3 without its `Set-Location` line.
5. Close and reopen PowerShell in that folder, then run `.\FormatWheel-cli.exe --doctor`.
6. Double-click **FormatWheel.exe** and follow the real-conversion test in step 5 above. Portable mode does not create the installer's Start menu shortcut.

## Setup troubleshooting

| What you see | What to do |
| --- | --- |
| `winget` is missing | Install or update Microsoft's **App Installer** in Microsoft Store ([Microsoft's instructions](https://learn.microsoft.com/en-us/windows/package-manager/winget/)). Open a new PowerShell window and rerun step 3. |
| `Set-Location` cannot find the folder | Run the Setup EXE first. For portable mode, use the folder containing `FormatWheel.exe` instead of the default installed-folder command. |
| `Install-Dependencies.ps1` or `FormatWheel-cli.exe` is not found | You are in the wrong folder, or have downloaded source code. Follow step 1 and extract the build; the installed/portable folder contains both files. |
| A slot says **未装备** | Its tool was not found. Run step 4, follow the matching action's note, and restart FormatWheel after installing the tool. |
| Nothing happens when starting the app | Check the **^** tray menu near the clock. Right-click FormatWheel's icon for file selection and settings. |
| Demo says **MISSION PASSED**, but no output appears | The demo does not convert files. Use **Choose files…** with an actual PNG and select JPG. |
| Drag-and-Shift does not open the wheel | Use the tray's **Choose files…** route. Avoid dragging from an application running as administrator into the normal tray app. |

To restart, update or uninstall, use the tray's **Quit** command first. Closing the drop window does not quit the tray application. Uninstall through **Settings → Apps → FormatWheel for Windows**; separately installed tools and user preferences/models remain available.

## Conversion tools and file locations

| Dependency | Enables |
| --- | --- |
| FFmpeg **and ffprobe** | All video/audio conversions and tools, including HEVC, WebM, GIF, extraction, speeds and audio normalization |
| LibreOffice | Rich/legacy document import and export, including DOC, RTF and ODT, and layout-preserving Office-to-PDF conversion |
| Tesseract OCR + `eng`, `chi_sim`, `chi_tra` data | English, Simplified Chinese and Traditional Chinese OCR for images/PDFs |
| Local `u2netp.onnx` model with rembg/ONNX Runtime | Image foreground cutout |

The script places OCR data in `%LOCALAPPDATA%\FormatWheel\tessdata` and the model in `%LOCALAPPDATA%\FormatWheel\models`. Builds also include the verified small cutout model. For model-only setup, use `Install-Dependencies.ps1 -ModelsOnly`. These downloads happen during preparation; conversions process files locally. FormatWheel does not upload source files to a conversion service.

Manual tool installations are supported through `PATH`, common Windows installation folders, or `FORMATWHEEL_FFMPEG`, `FORMATWHEEL_FFPROBE`, `FORMATWHEEL_SOFFICE` and `FORMATWHEEL_TESSERACT` environment variables containing executable paths. `U2NET_HOME` can point to an existing local model directory.

## Use the wheel

1. Drag files in Explorer, tap **Shift** while holding the left mouse button, move toward a slot and release.
2. Tap Shift again, or use **Tab / Q / E / scroll**, to switch between conversion and tools.
3. Return to the center before releasing to cancel. **Esc** or right-click also closes the wheel.

The tray menu's **Choose files…** / **Choose folder…** opens the wheel for direct clicking. **Enter / Space** executes the highlighted option. A desktop drop target also accepts files.

Outputs are written beside the source, with unique names to avoid overwriting existing files. An unwritable source folder falls back to Downloads or the temporary folder. Source files remain unchanged. Image-to-PDF and PDF merging keep selection order; generic ZIP/path/name actions use the whole selection. Other mixed-type batches follow the dominant file kind and indicate skipped files. OCR saves UTF-8 text and copies it to the clipboard.

The tray menu includes recent outputs, format/weapon icons, four character colors, three wheel sizes, sound, background blur, completion banners and launch-at-login. Settings are in `%APPDATA%\FormatWheel\settings.json`; the rolling log is `%LOCALAPPDATA%\FormatWheel\FormatWheel.log`.

## Live ZIP progress

Available in Windows build **1.0.0.windows.2** and newer. Quit the running tray app before installing an update.

Creating a ZIP opens an animated progress panel. It first scans the selection to count files and source bytes, then shows measured progress while each file is compressed, including large single files. The percentage measures **source bytes processed**, rather than the changing size of the compressed ZIP. Hover over the byte counter to see exact byte counts.

- **Pause / Resume** stops and continues the current job at a data-block boundary.
- **Cancel** removes the unfinished archive and keeps the original files. Wait for the canceled message before starting another job.
- **Folder** opens the destination folder while the job runs. When the ZIP is ready, **Show ZIP** reveals the finished archive.
- **Fewer details / More details** toggles file counts, speed, elapsed time, estimated remaining time and archive size.
- The **−** button hides the panel while compression continues. Restore it from the tray menu's **Show ZIP progress** action.

Scanning and finalizing use an activity animation because their duration cannot be measured as an exact percentage. The panel shows 100% only after the ZIP directory has been written and the archive is closed. Remaining time is an estimate based on measured transfer speed; pausing does not reduce the reported transfer speed. Elapsed time includes the whole job, including pauses.

If a selected file changes during compression, the job reports the change and removes the incomplete ZIP. Retry after that file has finished saving.

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
.\FormatWheel-cli.exe --zip-progress-snapshot zip-progress.png
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
