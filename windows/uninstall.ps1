$ErrorActionPreference = 'Stop'
$installRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$manifestPath = Join-Path $installRoot 'installed-files.json'
if (!(Test-Path -LiteralPath $manifestPath)) { throw 'Missing installation manifest. No files were removed.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$regPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FormatWheel'
$registeredHere = (Get-ItemProperty -LiteralPath $regPath -ErrorAction SilentlyContinue).InstallLocation -eq $installRoot
$targets = foreach ($relative in $manifest) {
    $absolute = [System.IO.Path]::GetFullPath((Join-Path $installRoot $relative))
    if (!$absolute.StartsWith($installRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid installation manifest. No files were removed.' }
    $absolute
}
$running = Get-Process FormatWheel -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($installRoot + '\', [System.StringComparison]::OrdinalIgnoreCase) }
if ($running) { throw 'Quit FormatWheel from its tray menu before uninstalling.' }
foreach ($target in $targets) { if (Test-Path -LiteralPath $target -PathType Leaf) { Remove-Item -LiteralPath $target -Force } }
$menuRoot = Join-Path ([Environment]::GetFolderPath('Programs')) 'FormatWheel'
$shortcutPath = Join-Path $menuRoot 'FormatWheel.lnk'
if ($registeredHere) {
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath -Force }
    if ((Test-Path -LiteralPath $menuRoot) -and !(Get-ChildItem -LiteralPath $menuRoot -Force)) { Remove-Item -LiteralPath $menuRoot }
    Remove-Item -LiteralPath $regPath
}
$runPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$startupValue = (Get-ItemProperty -LiteralPath $runPath -ErrorAction SilentlyContinue).FormatWheel
if ($startupValue -and $startupValue.Contains($installRoot)) { Remove-ItemProperty -LiteralPath $runPath -Name FormatWheel }
# Only remove empty directories; never recursively delete files added by the user.
Get-ChildItem -LiteralPath $installRoot -Directory -Recurse | Sort-Object { $_.FullName.Length } -Descending | ForEach-Object { if (!(Get-ChildItem -LiteralPath $_.FullName -Force)) { Remove-Item -LiteralPath $_.FullName } }
if (!(Get-ChildItem -LiteralPath $installRoot -Force)) { Remove-Item -LiteralPath $installRoot }
