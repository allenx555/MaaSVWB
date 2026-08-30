param(
    [switch]$Force,
    [switch]$WithMaaMcp
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $PSScriptRoot "ai-tools.lock.json"
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$skill = $lock.skills | Where-Object { $_.name -eq "maaframework" } | Select-Object -First 1

if (-not $skill) {
    throw "The maaframework skill is not pinned in tools/ai-tools.lock.json."
}

function Resolve-ProjectPath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $root = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
    $resolved = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $RelativePath))
    if (-not $resolved.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes the project root: $RelativePath"
    }
    return $resolved
}

function Install-MaaFrameworkSkill {
    $target = Resolve-ProjectPath -RelativePath $skill.install_path
    $marker = Join-Path $target ".maasvwb-source.json"

    if ((Test-Path -LiteralPath $marker) -and -not $Force) {
        $installed = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
        if ($installed.commit -eq $skill.commit) {
            Write-Host "[ai] MaaFramework skill is already installed at the pinned commit."
            return
        }
    }

    if ((Test-Path -LiteralPath $target) -and -not $Force) {
        throw "Skill target already exists. Re-run with -Force to replace only $target"
    }

    $repo = ([System.Uri]$skill.source).AbsolutePath.Trim('/').TrimEnd('.git')
    $archiveUrl = "https://codeload.github.com/$repo/zip/$($skill.commit)"
    $systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $tempRoot = Join-Path $systemTemp ("MaaSVWB-ai-" + [System.Guid]::NewGuid().ToString("N"))
    $tempRoot = [System.IO.Path]::GetFullPath($tempRoot)
    if (-not $tempRoot.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Temporary path validation failed."
    }

    try {
        New-Item -ItemType Directory -Path $tempRoot | Out-Null
        $archive = Join-Path $tempRoot "skill.zip"
        $expanded = Join-Path $tempRoot "expanded"
        Write-Host "[ai] Downloading MaaFramework skill commit $($skill.commit)"
        Invoke-WebRequest -Uri $archiveUrl -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $expanded

        $archiveRoot = Get-ChildItem -LiteralPath $expanded -Directory | Select-Object -First 1
        if (-not $archiveRoot) {
            throw "Downloaded skill archive is empty."
        }
        $source = Join-Path $archiveRoot.FullName ($skill.subdirectory -replace '/', '\')
        if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md"))) {
            throw "Downloaded archive does not contain the expected SKILL.md."
        }

        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Recurse

        $sourceRecord = [ordered]@{
            source = $skill.source
            commit = $skill.commit
            subdirectory = $skill.subdirectory
            installed_at_utc = [DateTime]::UtcNow.ToString("o")
        } | ConvertTo-Json
        [System.IO.File]::WriteAllText(
            $marker,
            $sourceRecord + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host "[ai] Installed project skill: $target"
    }
    finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}

function Install-MaaMcp {
    $server = $lock.mcp_servers | Where-Object { $_.name -eq "MaaMCP" } | Select-Object -First 1
    if (-not $server) {
        throw "MaaMCP is not pinned in tools/ai-tools.lock.json."
    }

    $environment = Resolve-ProjectPath -RelativePath ".ai-tools/maa-mcp"
    $environmentPython = Join-Path $environment "Scripts\python.exe"
    $pythonCommand = Get-Command python -ErrorAction Stop

    if (-not (Test-Path -LiteralPath $environmentPython)) {
        Write-Host "[ai] Creating isolated MaaMCP environment: $environment"
        & $pythonCommand.Source -m venv $environment
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the MaaMCP virtual environment."
        }
    }

    Write-Host "[ai] Installing MaaMCP $($server.version) in the isolated environment"
    & $environmentPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip in the MaaMCP environment."
    }
    & $environmentPython -m pip install --upgrade "$($server.package)==$($server.version)"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install MaaMCP."
    }
    Write-Host "[ai] MaaMCP command: $(Join-Path $environment 'Scripts\maa-mcp.exe')"
}

Set-Location -LiteralPath $projectRoot
& python tools/validate_ai_tools.py
if ($LASTEXITCODE -ne 0) {
    throw "AI tool lock validation failed."
}

Install-MaaFrameworkSkill
if ($WithMaaMcp) {
    Install-MaaMcp
}

Write-Host ""
Write-Host "AI development setup completed."
Write-Host "Read docs/zh_cn/develop/ai-development.md for client configuration and safety notes."
