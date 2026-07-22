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
    if ($LASTEXITCODE -ne 0) { throw "候选新闻不足或部分来源不可用（退出码 $LASTEXITCODE）" }
    & $PythonPath (Join-Path $PSScriptRoot "validate_news.py") 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw "news.json 校验失败" }
    "[$(Get-Date -Format o)] pipeline checks completed" | Add-Content -LiteralPath $logPath
}
catch {
    $detail = "小马看世界每日更新发生异常。`r`n`r`n时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')`r`n环节：新闻抓取或内容校验`r`n错误：$($_.Exception.Message)`r`n网站状态：继续保留上一版内容。"
    if (-not $SkipEmail) {
        & (Join-Path $PSScriptRoot "send_alert.ps1") -Subject "[小马看世界] 每日更新异常" -Body $detail
    }
    $detail | Add-Content -LiteralPath $logPath
    throw
}
