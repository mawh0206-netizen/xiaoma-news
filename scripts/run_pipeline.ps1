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
    $detail = "小马看世界每日更新失败。`r`n`r`n时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')`r`n失败阶段：采集或校验`r`n错误信息：$($_.Exception.Message)`r`n网站继续显示上一版成功内容。"
    if (-not $SkipEmail) {
        & (Join-Path $PSScriptRoot "send_alert.ps1") -Subject "【小马看世界】每日更新失败" -Body $detail
    }
    $detail | Add-Content -LiteralPath $logPath
    throw
}
