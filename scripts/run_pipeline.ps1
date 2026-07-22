param(
    [string]$PythonPath = "C:\Users\maweihua\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    [switch]$SkipEmail
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "runtime"
$logPath = Join-Path $logDir "pipeline.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

try {
    "[$(Get-Date -Format o)] candidate collection started" | Add-Content -LiteralPath $logPath
    & $PythonPath (Join-Path $PSScriptRoot "fetch_candidates.py") 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "Candidate collection failed (exit code $LASTEXITCODE)" }
    & $PythonPath (Join-Path $PSScriptRoot "validate_news.py") 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "news.json validation failed" }
    "[$(Get-Date -Format o)] pipeline checks completed" | Add-Content -LiteralPath $logPath
}
catch {
    $detail = "Xiaoma News daily update failed.`r`n`r`nTime: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')`r`nStage: collection or validation`r`nError: $($_.Exception.Message)`r`nWebsite: the last successful edition remains online."
    if (-not $SkipEmail) {
        & (Join-Path $PSScriptRoot "send_alert.ps1") -Subject "[Xiaoma News] Daily update failed" -Body $detail
    }
    $detail | Add-Content -LiteralPath $logPath
    throw
}
