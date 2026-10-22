param([switch]$SkipInstall, [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $venvPython)) { python -m venv (Join-Path $PSScriptRoot '.venv'); if ($LASTEXITCODE) { throw 'Python 3.11 x64 is required.' } }
if (!$SkipInstall) { & $venvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-lock.txt'); if ($LASTEXITCODE) { throw 'Dependency installation failed.' } }
Push-Location $projectRoot
try {
    & $venvPython windows/tools/prepare_model.py
    if ($LASTEXITCODE) { throw 'Model preparation failed.' }
    if (!$SkipTests) { & $venvPython -m pytest windows/tests -q; if ($LASTEXITCODE) { throw 'Tests failed.' } }
    & $venvPython windows/tools/package.py
    if ($LASTEXITCODE) { throw 'Packaging failed.' }
    & $venvPython windows/tools/smoke_package.py
    if ($LASTEXITCODE) { throw 'Packaged conversion smoke tests failed.' }
} finally { Pop-Location }
