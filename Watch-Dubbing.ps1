param([string]$Output = 'outputs\full-dub', [int]$Interval = 3, [switch]$Once)
$ErrorActionPreference = 'Stop'
$statusFile = Join-Path (Join-Path $PSScriptRoot $Output) 'status.json'
do {
    if (Test-Path -LiteralPath $statusFile) {
        $state = Get-Content -LiteralPath $statusFile -Raw -Encoding utf8 | ConvertFrom-Json
        $state | Format-List
    } else { Write-Host 'Run has not started.' }
    if (-not $Once) { Start-Sleep -Seconds $Interval }
} while (-not $Once)
