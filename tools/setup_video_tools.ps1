$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$videoEnv = Join-Path $projectRoot ".ai-tools\video"
$videoPython = Join-Path $videoEnv "Scripts\python.exe"

foreach ($command in @("ffmpeg", "ffprobe")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is missing from PATH. Install FFmpeg, then rerun this script."
    }
}
if (-not (Test-Path -LiteralPath $videoPython)) {
    & python -m venv $videoEnv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $videoPython -m pip install -r (Join-Path $PSScriptRoot "requirements-video.txt") --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $videoPython (Join-Path $PSScriptRoot "puzzle_video.py") doctor
exit $LASTEXITCODE
