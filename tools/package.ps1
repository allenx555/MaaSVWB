param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [ValidateSet("win", "linux", "macos")]
    [string]$Os,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeIdentifier
)

$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$installPath = [IO.Path]::GetFullPath((Join-Path $projectRoot "install"))
if ([IO.Path]::GetDirectoryName($installPath) -ne $projectRoot) {
    throw "Refusing to clean an install directory outside the project root: $installPath"
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
$localDotnet = Join-Path $projectRoot ".dotnet\dotnet.exe"
$dotnet = if (Test-Path -LiteralPath $localDotnet) { $localDotnet } else { "dotnet" }
$projectFile = Join-Path $projectRoot "gui\MaaSVWB.Desktop\MaaSVWB.Desktop.csproj"

if (Test-Path -LiteralPath $installPath) {
    Remove-Item -LiteralPath $installPath -Recurse -Force
}

Push-Location -LiteralPath $projectRoot
try {
    & $python tools/install.py $Version $Os
    if ($LASTEXITCODE -ne 0) {
        throw "Resource installation failed with exit code $LASTEXITCODE."
    }

    & $python tools/build_runner.py
    if ($LASTEXITCODE -ne 0) {
        throw "Bundled runner build failed with exit code $LASTEXITCODE."
    }

    & $dotnet publish $projectFile `
        --configuration Release `
        --runtime $RuntimeIdentifier `
        --self-contained true `
        --output $installPath
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop publish failed with exit code $LASTEXITCODE."
    }

    $dotnetCommand = Get-Command $dotnet -ErrorAction Stop
    $dotnetRoot = Split-Path -Parent $dotnetCommand.Source
    $licensesPath = Join-Path $installPath "licenses"
    foreach ($notice in @("LICENSE.txt", "ThirdPartyNotices.txt")) {
        $source = Join-Path $dotnetRoot $notice
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $licensesPath "dotnet-$notice") -Force
        }
    }
}
finally {
    Pop-Location
}

Write-Host "Release package created in $installPath"
