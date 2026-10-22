// Per-user installer compiled with Windows' .NET Framework compiler; no build-tool installation.
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

class Installer {
    [STAThread]
    static int Main(string[] args) {
        bool silent = Array.IndexOf(args, "/silent") >= 0;
        bool extractOnly = Array.IndexOf(args, "/extract-only") >= 0;
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "FormatWheel");
        foreach (string arg in args) if (arg.StartsWith("/dir=", StringComparison.OrdinalIgnoreCase)) root = Path.GetFullPath(arg.Substring(5));
        if (!silent && MessageBox.Show("Install FormatWheel for your Windows account?\n\n" + root + "\n\nNo administrator access is required.", "FormatWheel Setup", MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK) return 0;
        try {
            Directory.CreateDirectory(root);
            string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            foreach (Process process in Process.GetProcessesByName("FormatWheel")) {
                try { if (process.MainModule.FileName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("Quit FormatWheel from its tray menu before updating."); }
                catch (System.ComponentModel.Win32Exception) { }
            }
            using (Stream data = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
            using (ZipArchive archive = new ZipArchive(data, ZipArchiveMode.Read)) {
                foreach (ZipArchiveEntry entry in archive.Entries) {
                    string target = Path.GetFullPath(Path.Combine(root, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                    if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("Invalid archive path.");
                    if (entry.Name.Length == 0) { Directory.CreateDirectory(target); continue; }
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    using (Stream src = entry.Open()) using (Stream dst = File.Create(target)) src.CopyTo(dst);
                }
            }
            if (extractOnly) return 0; // Packaging smoke test without registry or shortcut changes.
            string menu = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "FormatWheel");
            Directory.CreateDirectory(menu);
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            dynamic shell = Activator.CreateInstance(shellType);
            dynamic shortcut = shell.CreateShortcut(Path.Combine(menu, "FormatWheel.lnk"));
            shortcut.TargetPath = Path.Combine(root, "FormatWheel.exe");
            shortcut.WorkingDirectory = root;
            shortcut.Save();
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\FormatWheel")) {
                key.SetValue("DisplayName", "FormatWheel for Windows");
                key.SetValue("DisplayVersion", "1.0.0.windows.1");
                key.SetValue("Publisher", "FormatWheel contributors");
                key.SetValue("InstallLocation", root);
                key.SetValue("DisplayIcon", Path.Combine(root, "FormatWheel.exe"));
                key.SetValue("UninstallString", "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(root, "uninstall.ps1") + "\"");
                key.SetValue("NoModify", 1);
                key.SetValue("NoRepair", 1);
            }
            if (!silent) MessageBox.Show("Installed. Open FormatWheel from the Start menu.\n\nTo convert: drag a file, tap Shift, flick toward a wheel slot and release.\n\nOptional conversion backends are described in WINDOWS-README.md.", "FormatWheel Setup");
            return 0;
        } catch (Exception error) {
            if (!silent) MessageBox.Show(error.Message, "FormatWheel Setup failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            else Console.Error.WriteLine(error.Message);
            return 1;
        }
    }
}
