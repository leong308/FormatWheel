// Per-user installer compiled with Windows' .NET Framework compiler; no build-tool installation.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using Microsoft.Win32;

class Installer {
    static string OwnedPath(string root, string relative) {
        if (String.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.IndexOf(':') >= 0)
            throw new IOException("Invalid installation manifest or archive path.");
        string normalized = relative.Replace('/', Path.DirectorySeparatorChar);
        foreach (string part in normalized.Split(Path.DirectorySeparatorChar)) {
            if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" ") || part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                throw new IOException("Invalid installation manifest or archive path.");
        }
        string target = Path.GetFullPath(Path.Combine(root, normalized));
        string prefix = root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new IOException("Installation path escapes the application folder.");
        // A junction/symlink could otherwise redirect a valid-looking relative path outside root.
        string current = root;
        CheckOrdinaryPath(current);
        foreach (string part in normalized.Split(Path.DirectorySeparatorChar)) {
            current = Path.Combine(current, part);
            CheckOrdinaryPath(current);
        }
        return target;
    }

    static void CheckOrdinaryPath(string path) {
        try {
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Installation paths must not contain symbolic links or junctions: " + path);
        } catch (FileNotFoundException) { }
        catch (DirectoryNotFoundException) { }
    }

    static HashSet<string> ManifestPaths(string root, string json) {
        object[] entries = new JavaScriptSerializer().DeserializeObject(json) as object[];
        if (entries == null) throw new IOException("The installation manifest must be an array of file paths.");
        HashSet<string> paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (object entry in entries) {
            string relative = entry as string;
            string target = OwnedPath(root, relative);
            if (!paths.Add(target)) throw new IOException("Duplicate installation manifest path.");
        }
        return paths;
    }

    static void ExtractAndUpdate(string root, ZipArchive archive) {
        string manifestPath = OwnedPath(root, "installed-files.json");
        HashSet<string> previous = File.Exists(manifestPath)
            ? ManifestPaths(root, File.ReadAllText(manifestPath))
            : new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        Dictionary<string, ZipArchiveEntry> files = new Dictionary<string, ZipArchiveEntry>(StringComparer.OrdinalIgnoreCase);
        List<string> directories = new List<string>();
        HashSet<string> entries = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        // Validate the entire payload and old ownership list before creating or replacing files.
        foreach (ZipArchiveEntry entry in archive.Entries) {
            bool directory = entry.FullName.EndsWith("/") || entry.FullName.EndsWith("\\");
            string target = OwnedPath(root, directory ? entry.FullName.TrimEnd('/', '\\') : entry.FullName);
            if (!entries.Add(target)) throw new IOException("Duplicate archive path.");
            if (directory) directories.Add(target);
            else files.Add(target, entry);
        }
        ZipArchiveEntry manifest;
        if (!files.TryGetValue(manifestPath, out manifest)) throw new IOException("The installer payload has no ownership manifest.");
        HashSet<string> next;
        using (StreamReader reader = new StreamReader(manifest.Open())) next = ManifestPaths(root, reader.ReadToEnd());
        if (!next.SetEquals(files.Keys)) throw new IOException("The installer payload and ownership manifest do not match.");
        Directory.CreateDirectory(root);
        foreach (string directory in directories) Directory.CreateDirectory(directory);
        foreach (KeyValuePair<string, ZipArchiveEntry> file in files) {
            if (String.Equals(file.Key, manifestPath, StringComparison.OrdinalIgnoreCase)) continue;
            Directory.CreateDirectory(Path.GetDirectoryName(file.Key));
            using (Stream src = file.Value.Open()) using (Stream dst = File.Create(file.Key)) src.CopyTo(dst);
        }
        foreach (string oldFile in previous) {
            if (!next.Contains(oldFile) && File.Exists(oldFile)) {
                // Recheck immediately before deletion; never recursively remove an old folder.
                OwnedPath(root, oldFile.Substring(root.TrimEnd(Path.DirectorySeparatorChar).Length + 1));
                File.Delete(oldFile);
                string parent = Path.GetDirectoryName(oldFile);
                while (!String.Equals(parent.TrimEnd(Path.DirectorySeparatorChar), root.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase)
                       && Directory.Exists(parent) && Directory.GetFileSystemEntries(parent).Length == 0) {
                    Directory.Delete(parent);
                    parent = Path.GetDirectoryName(parent);
                }
            }
        }
        // Preserve the previous ownership list until extraction and obsolete-file cleanup succeed.
        using (Stream src = manifest.Open()) using (Stream dst = File.Create(manifestPath)) src.CopyTo(dst);
    }

    [STAThread]
    static int Main(string[] args) {
        bool silent = Array.IndexOf(args, "/silent") >= 0;
        bool extractOnly = Array.IndexOf(args, "/extract-only") >= 0;
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "FormatWheel");
        foreach (string arg in args) if (arg.StartsWith("/dir=", StringComparison.OrdinalIgnoreCase)) root = Path.GetFullPath(arg.Substring(5));
        if (!silent && MessageBox.Show("Install FormatWheel for your Windows account?\n\n" + root + "\n\nNo administrator access is required.", "FormatWheel Setup", MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK) return 0;
        try {
            root = Path.GetFullPath(root);
            string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            foreach (Process process in Process.GetProcessesByName("FormatWheel")) {
                try { if (process.MainModule.FileName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("Quit FormatWheel from its tray menu before updating."); }
                catch (System.ComponentModel.Win32Exception) { }
            }
            using (Stream data = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
            using (ZipArchive archive = new ZipArchive(data, ZipArchiveMode.Read)) {
                ExtractAndUpdate(root, archive);
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
                key.SetValue("DisplayVersion", "1.0.0.windows.2");
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
