# Examples: .\Run-Dubbing.ps1 plan; .\Run-Dubbing.ps1 run --scene 01_00_00_Cinema
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot 'work\qwen-env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Qwen environment not found: $pythonPath" }
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
Push-Location $projectRoot
try {
    & $pythonPath (Join-Path $projectRoot 'scripts\dub.py') @args
    if ($LASTEXITCODE -ne 0) { throw "Dubbing command failed ($LASTEXITCODE). Read outputs\<run>\events.jsonl" }
} finally { Pop-Location }
