$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }

Set-Location -LiteralPath $projectRoot
$env:PYTHONIOENCODING = "utf-8"

function Invoke-PythonStep {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Write-Host "[test] Unit tests"
Invoke-PythonStep -m unittest discover -s tests -v

Write-Host "[test] Catalog and solution validation"
Invoke-PythonStep tools/validate_content.py

Write-Host "[test] AI development tool pins"
Invoke-PythonStep tools/validate_ai_tools.py

Write-Host "[test] Version pins and generated Project Interface"
Invoke-PythonStep tools/validate_versions.py
Invoke-PythonStep tools/generate_interface.py --check

Write-Host "[test] Python compile check"
Invoke-PythonStep -m compileall -q agent tools tests

Write-Host "[test] Python static type check"
& npm run typecheck
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "[test] MaaFramework schema validation"
Invoke-PythonStep tools/validate_schema.py `
    --schema-dir deps/tools `
    --resource-dirs assets/resource `
    --exclude-dirs assets/resource/solutions assets/resource/layouts `
    --interface-files assets/interface.json

Write-Host "[test] All checks passed"
