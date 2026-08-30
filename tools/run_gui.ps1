param()

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$localDotnet = Join-Path $projectRoot ".dotnet\dotnet.exe"
$projectFile = Join-Path $projectRoot "gui\MaaSVWB.Desktop\MaaSVWB.Desktop.csproj"

if (-not (Test-Path -LiteralPath $localDotnet)) {
    throw "GUI environment is not ready. Run: powershell -ExecutionPolicy Bypass -File .\tools\setup_gui.ps1"
}

& $localDotnet run --project $projectFile
exit $LASTEXITCODE
