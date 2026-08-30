param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$versions = Get-Content -LiteralPath (Join-Path $projectRoot "tools\project_versions.json") -Raw | ConvertFrom-Json
$requiredPython = [string]$versions.python

Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "[setup] Creating Python virtual environment: $venvPath"
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        & $pyLauncher.Source "-$requiredPython" -m venv $venvPath
    }
    else {
        python -m venv $venvPath
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the Python $requiredPython virtual environment."
    }
}

$actualPython = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($actualPython -ne $requiredPython) {
    Write-Warning "The existing .venv uses Python $actualPython; the canonical development and release version is $requiredPython. Recreate .venv with Python $requiredPython when preparing a release."
}

Write-Host "[setup] Installing Python development dependencies"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}
& $venvPython -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install dependencies."
}

Write-Host "[setup] Python environment is ready"
& $venvPython -c "import maa; import importlib.metadata as m; print('Python:', m.version('maafw'))"

Write-Host "[setup] Preparing MaaFramework OCR model"
& $venvPython tools/setup_ocr.py
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare the OCR model."
}

if (-not $SkipTests) {
    & (Join-Path $PSScriptRoot "test.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Tests failed."
    }
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Start the Android emulator and enable ADB."
Write-Host "2. Run .\.venv\Scripts\python tools\run_android.py"
Write-Host "   If auto-discovery fails, add --adb PATH_TO_ADB_EXE."
Write-Host "3. Open the puzzle list, then run the puzzle task with --execute."
