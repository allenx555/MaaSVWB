param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonCandidates = @(
    (Join-Path $projectRoot ".ai-tools\maa-mcp\Scripts\python.exe"),
    (Join-Path $projectRoot ".ai-tools/maa-mcp/bin/python")
)
$mcpPython = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $mcpPython) {
    throw "MaaMCP is not installed. Run tools/setup_ai_dev.ps1 -WithMaaMcp first."
}

$dataDir = (& $mcpPython -c "from maa_mcp.paths import get_data_dir; print(get_data_dir())").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($dataDir)) {
    throw "Failed to resolve the MaaMCP data directory."
}

$pipelinesRoot = [System.IO.Path]::GetFullPath((Join-Path $dataDir "pipelines"))
$destination = [System.IO.Path]::GetFullPath((Join-Path $pipelinesRoot "MaaSVWB"))
$expectedPrefix = $pipelinesRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $destination.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Resolved MaaMCP pipeline destination escapes its pipelines directory."
}

New-Item -ItemType Directory -Path $destination -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $projectRoot "assets/resource/pipeline") -Filter "*.json" -File |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $destination -Force }
Copy-Item -LiteralPath (Join-Path $projectRoot "assets/resource/default_pipeline.json") -Destination $destination -Force

Write-Host "MaaSVWB Pipeline files synchronized to: $destination"
Write-Host "Pass files under this directory to MaaMCP load_pipeline; project source paths are rejected by MaaMCP's sandbox."
