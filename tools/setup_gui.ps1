param()

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$localDotnet = Join-Path $projectRoot ".dotnet\dotnet.exe"

if (-not (Test-Path -LiteralPath $localDotnet)) {
    Write-Host "Downloading the local .NET 10 SDK for MaaSVWB..."
    $installerPath = Join-Path ([IO.Path]::GetTempPath()) "dotnet-install-maasvwb.ps1"
    Invoke-WebRequest -Uri "https://dot.net/v1/dotnet-install.ps1" -OutFile $installerPath
    & $installerPath -Channel "10.0" -InstallDir (Join-Path $projectRoot ".dotnet") -NoPath
    if ($LASTEXITCODE -ne 0) {
        throw ".NET SDK installation failed with exit code $LASTEXITCODE."
    }
}

& $localDotnet restore (Join-Path $projectRoot "gui\MaaSVWB.Desktop\MaaSVWB.Desktop.csproj")
if ($LASTEXITCODE -ne 0) {
    throw "GUI dependency restore failed with exit code $LASTEXITCODE."
}

Write-Host "The GUI development environment is ready."
