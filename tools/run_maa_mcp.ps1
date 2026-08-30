$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$server = Join-Path $projectRoot ".ai-tools\maa-mcp\Scripts\maa-mcp.exe"

if (-not (Test-Path -LiteralPath $server)) {
    throw "MaaMCP is not installed. Run tools/setup_ai_dev.ps1 -WithMaaMcp first."
}

& $server @args
exit $LASTEXITCODE
