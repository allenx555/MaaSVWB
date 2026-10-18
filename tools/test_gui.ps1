$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonCandidates = @(
    (Join-Path $projectRoot ".venv/Scripts/python.exe"),
    (Join-Path $projectRoot ".venv/bin/python")
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) { $python = (Get-Command python -ErrorAction Stop).Source }
$dotnetCandidates = @(
    (Join-Path $projectRoot ".dotnet/dotnet.exe"),
    (Join-Path $projectRoot ".dotnet/dotnet")
)
$dotnet = $dotnetCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $dotnet) { $dotnet = "dotnet" }
$project = Join-Path $projectRoot "gui\MaaSVWB.Desktop.IntegrationTests\MaaSVWB.Desktop.IntegrationTests.csproj"

& $dotnet run --project $project -- $projectRoot $python
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
