"""Small native Windows integration layer, importable on other platforms for tests."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def key_down(key: int) -> bool:
    return IS_WINDOWS and bool(ctypes.windll.user32.GetAsyncKeyState(key) & 0x8000)


def reveal(path: Path):
    path = Path(path).absolute()
    if IS_WINDOWS:
        # Pass arguments separately so file names cannot be interpreted as commands.
        subprocess.Popen(["explorer.exe", "/select,", str(path)], creationflags=NO_WINDOW)
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def startup_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.QueryValueEx(key, "FormatWheel")
        return True
    except OSError:
        return False


def set_startup(enabled: bool):
    if not IS_WINDOWS:
        return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            if getattr(sys, "frozen", False):
                arguments = [sys.executable, "--background"]
            else:
                # pythonw keeps startup from opening an extra console window.
                executable = Path(sys.executable).with_name("pythonw.exe")
                arguments = [str(executable if executable.exists() else sys.executable),
                             str(Path(__file__).resolve().parents[1] / "launcher.py"), "--background"]
            winreg.SetValueEx(key, "FormatWheel", 0, winreg.REG_SZ, subprocess.list2cmdline(arguments))
        else:
            try:
                winreg.DeleteValue(key, "FormatWheel")
            except FileNotFoundError:
                pass


def explorer_selection():
    """Fallback for a shell drag whose source has not delivered an OLE URL yet."""
    if not IS_WINDOWS:
        return []
    try:
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        foreground = ctypes.windll.user32.GetForegroundWindow()
        for window in shell.Windows():
            if int(window.HWND) == foreground:
                return [Path(item.Path) for item in window.Document.SelectedItems() if Path(item.Path).exists()]
    except Exception:
        pass
    return []


def set_app_id():
    if IS_WINDOWS:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FormatWheel.Windows.1")
