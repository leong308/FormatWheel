param([switch]$WithCutout, [switch]$ModelsOnly)
$ErrorActionPreference = 'Stop'
if (!$ModelsOnly) {
    if (!(Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Install App Installer from Microsoft Store to obtain winget, or install FFmpeg, LibreOffice and Tesseract manually.' }
    foreach ($packageId in @('Gyan.FFmpeg', 'TheDocumentFoundation.LibreOffice', 'UB-Mannheim.TesseractOCR')) {
        & winget install --id $packageId --exact --source winget --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) { throw "Could not install $packageId. Install it manually and rerun this script." }
    }
    $dataRoot = Join-Path $env:LOCALAPPDATA 'FormatWheel\tessdata'
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    foreach ($language in @('eng', 'chi_sim', 'chi_tra')) {
        $destination = Join-Path $dataRoot ($language + '.traineddata')
        if (!(Test-Path -LiteralPath $destination)) {
            Invoke-WebRequest -UseBasicParsing -Uri ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/' + $language + '.traineddata') -OutFile $destination
        }
    }
}
if ($WithCutout -or $ModelsOnly) {
    $modelRoot = Join-Path $env:LOCALAPPDATA 'FormatWheel\models'
    New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null
    $destination = Join-Path $modelRoot 'u2netp.onnx'
    if (!(Test-Path -LiteralPath $destination)) {
        Invoke-WebRequest -UseBasicParsing 'https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx' -OutFile $destination
    }
    if ((Get-FileHash -LiteralPath $destination -Algorithm MD5).Hash.ToLowerInvariant() -ne '8e83ca70e441ab06c318d82300c84806') {
        Remove-Item -LiteralPath $destination
        throw 'The background-removal model failed verification. Rerun to download it again.'
    }
}
Write-Output 'Dependencies prepared. Restart FormatWheel; conversions run locally without downloads.'
